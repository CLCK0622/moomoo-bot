from __future__ import annotations
import pandas as pd
import numpy as np
from config import Config
from strategy.combiner import build_entry_evaluator
from strategy.exit_manager import ExitManager
from strategy.gap_and_go import gap_and_go_entry, vwap_bounce_entry
from backtest.portfolio import Portfolio
from backtest.metrics import compute_metrics


class BacktestEngine:
    def __init__(self, config: Config):
        self.config = config

    def run(self, data: dict[str, pd.DataFrame], params: dict) -> dict:
        portfolio = Portfolio(
            initial_capital=self.config.initial_capital,
            max_positions=self.config.max_positions,
            commission=self.config.commission_per_trade,
            slippage_pct=self.config.slippage_pct,
        )
        entry_eval = build_entry_evaluator(params)
        exit_mgr = ExitManager(params)
        orb_lock_minutes = params.get("orb_lock_minutes", 15)
        use_gap_go = params.get("use_gap_and_go", False)
        use_vwap_bounce = params.get("use_vwap_bounce", False)
        daily_loss_limit = params.get("daily_loss_limit_pct", 0.015)

        all_dates = set()
        for sym_df in data.values():
            all_dates.update(sym_df["date"].unique())
        all_dates = sorted(all_dates)

        prev_closes = {}

        for date in all_dates:
            day_data = {}
            for symbol, df in data.items():
                day_df = df[df["date"] == date].sort_values("time").reset_index(drop=True)
                if not day_df.empty:
                    day_data[symbol] = day_df

            if not day_data:
                continue

            self._run_day(portfolio, day_data, entry_eval, exit_mgr, params,
                          orb_lock_minutes, use_gap_go, use_vwap_bounce,
                          prev_closes, daily_loss_limit)
            portfolio.record_daily_pnl(date)

            for sym, ddf in day_data.items():
                if not ddf.empty:
                    prev_closes[sym] = ddf.iloc[-1]["close"]

        return {
            "metrics": compute_metrics(portfolio.trade_log, portfolio.daily_pnl),
            "trade_log": portfolio.trade_log,
            "daily_pnl": portfolio.daily_pnl,
        }

    def _run_day(self, portfolio, day_data, entry_eval, exit_mgr, params,
                 orb_lock_minutes, use_gap_go, use_vwap_bounce,
                 prev_closes, daily_loss_limit):
        first_df = next(iter(day_data.values()))
        n_bars = len(first_df)
        allow_reentry = params.get("allow_reentry", True)
        blocked_today = set()
        day_realized_loss = 0.0
        day_start_equity = portfolio._day_start_equity
        daily_loss_cap = day_start_equity * daily_loss_limit
        halted = False

        for bar_idx in range(n_bars):
            rows = {}
            for symbol, df in day_data.items():
                if bar_idx < len(df):
                    rows[symbol] = df.iloc[bar_idx]

            if not rows:
                continue

            sample_row = next(iter(rows.values()))
            time_val = sample_row["time"]
            minutes_since_open = time_val.hour * 60 + time_val.minute - (9 * 60 + 30)

            if minutes_since_open < orb_lock_minutes:
                continue

            # Exit scan (always runs even if halted)
            for symbol in list(portfolio.positions.keys()):
                if symbol not in rows:
                    continue
                row = rows[symbol]
                pos = portfolio.positions[symbol]
                signal = exit_mgr.evaluate(pos, row)
                if signal:
                    portfolio.close_position(symbol, row["close"], signal.quantity_pct, signal.reason, time_val)
                    if signal.quantity_pct >= 1.0:
                        last_trade = portfolio.trade_log[-1] if portfolio.trade_log else None
                        if last_trade:
                            if last_trade["pnl"] < 0:
                                day_realized_loss += abs(last_trade["pnl"])
                                blocked_today.add(symbol)
                                if day_realized_loss >= daily_loss_cap:
                                    halted = True

            # Daily loss halt: stop opening new positions
            if halted:
                continue

            # Entry scan
            max_entry_hour = params.get("max_entry_hour", 15)
            entry_allowed = time_val.hour < max_entry_hour or (time_val.hour == max_entry_hour and time_val.minute == 0)
            if portfolio.available_slots > 0 and entry_allowed:
                candidates = []
                for symbol, row in rows.items():
                    if symbol in portfolio.positions:
                        continue
                    if not allow_reentry and symbol in blocked_today:
                        continue
                    if pd.isna(row.get("orb_high")) or pd.isna(row.get("orb_low")):
                        continue

                    entered = False

                    # Strategy 1: ORB Breakout (core)
                    if entry_eval(row, params):
                        breakout_str = (row["close"] - row["orb_high"]) / row["orb_high"]
                        vol_ratio = 1.5 if row.get("volume_spike") else 1.0
                        score = breakout_str * vol_ratio
                        candidates.append((symbol, row, score, "orb_breakout"))
                        entered = True

                    # Strategy 2: Gap-and-Go
                    if not entered and use_gap_go and symbol in prev_closes:
                        if gap_and_go_entry(row, params, prev_closes[symbol]):
                            gap = abs(row["open"] - prev_closes[symbol]) / prev_closes[symbol]
                            candidates.append((symbol, row, gap, "gap_and_go"))
                            entered = True

                    # Strategy 3: VWAP Bounce
                    if not entered and use_vwap_bounce:
                        if vwap_bounce_entry(row, params):
                            candidates.append((symbol, row, 0.5, "vwap_bounce"))

                candidates.sort(key=lambda x: x[2], reverse=True)
                dd_scale_start = params.get("dd_scale_start", 0.05)
                dd_scale_min = params.get("dd_scale_min", 0.4)
                pos_size = portfolio.current_position_size(dd_scale_start, dd_scale_min)

                for symbol, row, _, strategy in candidates[:portfolio.available_slots]:
                    portfolio.open_position(
                        symbol, price=row["close"], size=pos_size,
                        orb_low=row["orb_low"], time=time_val,
                    )
                    if symbol in portfolio.positions:
                        portfolio.positions[symbol]["strategy"] = strategy
