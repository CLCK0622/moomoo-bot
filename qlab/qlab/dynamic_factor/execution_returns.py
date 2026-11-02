"""C07 readout of an owned C04 journal; no strategy, source reader or runtime.

The terminal row is a separate prearranged historical reference settlement,
not a broker fill or a checkpoint for the continuing D2 account. Original C04
closes, inventory, cash availability and rights are retained verbatim. This
readout never feeds an x1 or liquidated state back into D1/D2.
"""

from copy import deepcopy
from fractions import Fraction
import math

from .contract import canonical, code_sha, digest, is_sha, sha256
from .execution_accounting import ExecutionAccount
from .execution_closure import validate_execution_binding
from .execution_numbers import amount, decimal_text
from .fees import finite
from .fold_split import train_dates
from .pipeline import moments


class TrainingReturns:
    """One frozen member/fold/attempt, bound before its first accounting close.

    Expected hashes are host capabilities after C09 source acceptance, not
    self-reported credentials. Only benchmark returns may cross this boundary;
    strategy returns come exclusively from the owned account's actual journal.
    A complete synthetic diagnostic remains execution_verified=false.
    """

    def __init__(self, account, *, expected_account_sha256, execution_binding):
        if type(account) is not ExecutionAccount:
            raise ValueError("returns.owned_C04_account_required")
        with account._lock:
            binding = validate_execution_binding(execution_binding)
            snap = account.snapshot()
            original = account._initial_snapshot
            policy = account._policy
            scope = original["scope"]
            fold = next(
                (
                    f
                    for f in policy.fold_manifest()["folds"]
                    if f["fold_id"] == scope["fold_id"]
                ),
                None,
            )
            if (
                not is_sha(expected_account_sha256)
                or expected_account_sha256 != snap["account_sha256"]
                or not snap["complete"]
                or account.close_receipts()
                or account._declarations
                or scope["kind"] != "independent_training"
                or fold is None
                or digest(binding) != digest(account._binding)
                or account._mode != "named_training_diagnostic"
            ):
                raise ValueError("returns.preexecution_training_binding_required")
            lo = policy.calendar.index(fold["train_start"])
            dates = list(train_dates(policy.calendar, fold))
            state = original["state"]
            if (
                len(dates) != policy.document["folds"]["train_days"]
                or len(dates) != 1260
                or original["close_session"] != policy.calendar[lo - 1]
                or amount(state["cash"]) != 15000
                or amount(state["nav"]) != 15000
                or amount(original["fees_x2"]) != 0
                or any(state["inventory"].values())
                or any(
                    state[k]
                    for k in (
                        "rights",
                        "receivables",
                        "pending_orders",
                        "unknown_components",
                    )
                )
                or state["initialization_count"] != 1
            ):
                raise ValueError("returns.complete_zero_E0_genesis_required")
            self._account, self._policy = account, policy
            self._binding, self._dates = binding, dates
            self._plan = dict(
                schema="EVO884.TrainingReturnPlan/v1",
                book_id=snap["book_id"],
                scope=deepcopy(scope),
                initial_account_sha256=expected_account_sha256,
                initial_snapshot_sha256=account._initial_snapshot_sha256,
                train_calendar_sha256=digest(dates),
                first_session=dates[0],
                terminal_session=dates[-1],
                terminal_rule=policy.profile["metrics"]["historical_terminal"],
                execution_closure_sha256=binding["adoption_sha256"],
                clock_ruling_sha256=original["ruling_sha256"],
            )
            self._terminal = None

    def plan(self):
        return deepcopy(self._plan)

    def _journal(self):
        account = self._account
        snapshot = account.snapshot()
        if not snapshot["complete"] or not account._book.snapshot()["complete"]:
            raise ValueError("returns.R2_incomplete_account")
        closes = account.close_receipts()
        if [r["session"] for r in closes] != self._dates:
            raise ValueError("returns.exact_1260_dates_required_no_omission")
        previous, previous_x1, fee = Fraction(15000), Fraction(15000), Fraction(0)
        x2, x1 = [], []
        for date, row in zip(self._dates, closes):
            state = row["accounting"]
            nav, next_fee = amount(state["nav"]), amount(state["fees_x2"])
            replay = row["x1_replay"]
            nav_x1 = amount(replay["NAV"])
            if (
                row["book_id"] != self._plan["book_id"]
                or row["execution_closure_sha256"] != self._binding["adoption_sha256"]
                or row["execution_mode"] != "named_training_diagnostic"
                or row["execution_verified"] is not False
                or state["asof"][:10] != date
                or nav <= 0
                or nav_x1 <= 0
                or amount(row["previous_close_NAV"]) != previous
                or Fraction(row["return_ratio"]) != nav / previous - 1
                or next_fee < fee
                or state["rights"]
                or state["unknown_components"]
                or state["pending_orders"]
                or replay["same_orders_and_quantities"] is not True
                or replay["additional_orders"]
                or replay["canonical"] is not False
            ):
                raise ValueError("returns.cross_day_account_reconciliation_failed")
            # Known cash receivables stay in NAV, never become spendable cash.
            if any(amount(r["amount"]) < 0 for r in state["receivables"].values()):
                raise ValueError("returns.R2_receivable_unknown")
            x2.append(nav / previous - 1)
            x1.append(nav_x1 / previous_x1 - 1)
            previous, previous_x1, fee = nav, nav_x1, next_fee
        if any(
            snapshot["retained_state"][k] != closes[-1]["accounting"][k]
            for k in ("inventory", "cash", "nav", "rights", "receivables")
        ):
            raise ValueError("returns.account_changed_after_final_close")
        return snapshot, closes, x2, x1

    def _settle(self, snapshot, closes):
        account, last = self._account, closes[-1]
        identity = digest([self._plan, snapshot["account_sha256"], closes])
        if self._terminal is not None:
            if self._terminal["source_journal_sha256"] != identity:
                raise ValueError("returns.closed_terminal_journal_changed")
            return deepcopy(self._terminal)
        # Consume the exact successful close evidence retained by C04. Caller
        # prices/terminal dates/returns cannot override or repair the journal.
        declaration = next(
            (
                d
                for d in reversed(account._declarations)
                if d["operation"] == "close_session" and d["status"] == "verified"
            ),
            None,
        )
        evidence = declaration["args"][0] if declaration else None
        if (
            evidence is None
            or digest(evidence) != last["close_evidence_sha256"]
            or evidence["session"] != self._plan["terminal_session"]
        ):
            raise ValueError("returns.bound_terminal_raw_close_required")
        state = deepcopy(last["accounting"])
        orders, gross, fee2, fee1 = [], Fraction(0), Fraction(0), Fraction(0)
        for symbol in sorted(state["inventory"]):
            quantity = state["inventory"][symbol]
            if not quantity:
                continue
            price = amount(evidence["prices"][symbol])
            if price <= 0:
                raise ValueError("returns.necessary_terminal_price_unknown")
            notional = quantity * price
            order = dict(symbol=symbol, session=last["session"])
            cost2 = account._fee(order, -quantity, notional, "x2")
            cost1 = account._fee(order, -quantity, notional, "x1")
            orders.append(
                dict(
                    order_id=digest([self._plan, "prearranged_close", symbol]),
                    symbol=symbol,
                    quantity=-quantity,
                    price=decimal_text(price),
                    notional=decimal_text(notional),
                    fee_x2=decimal_text(cost2),
                    fee_x1=decimal_text(cost1),
                )
            )
            gross += notional
            fee2 += cost2
            fee1 += cost1
            state["inventory"][symbol] = 0
        state["cash"] = decimal_text(amount(state["cash"]) + gross - fee2)
        state["nav"] = decimal_text(amount(state["nav"]) - fee2)
        state["fees_x2"] = decimal_text(amount(state["fees_x2"]) + fee2)
        if amount(state["cash"]) < 0 or amount(state["nav"]) <= 0:
            raise ValueError("returns.terminal_cash_or_NAV_infeasible")
        self._terminal = dict(
            schema="EVO884.HistoricalTerminalSettlement/v1",
            plan_sha256=digest(self._plan),
            source_journal_sha256=identity,
            session=last["session"],
            book_id=self._plan["book_id"],
            source_close_sha256=digest(last),
            close_evidence_sha256=digest(evidence),
            orders=orders,
            gross_sale_proceeds=decimal_text(gross),
            accounting=state,
            fee_x2=decimal_text(fee2),
            fee_x1=decimal_text(fee1),
            x1_NAV=decimal_text(amount(last["x1_replay"]["NAV"]) - fee1),
            model="prearranged_last_close_reference_liquidation_with_strategy_fees",
            settlement_phase="scheduled_historical_terminal_close",
            fee_order_scope="separate_close_order_per_symbol_and_trade_date",
            x1_same_orders_and_quantities=True,
            spendable_account_cash_attested=False,
            execution_verified=False,
            continuing_account_modified=False,
            runtime_consumable=False,
            certifiable=False,
        )
        return deepcopy(self._terminal)

    def terminal_settlement(self):
        """Read the posted historical settlement; no recomputation or restore."""
        with self._account._lock:
            return deepcopy(self._terminal)

    def export_bytes(self):
        """Reconciliation artifact, never an installed authority/checkpoint."""
        with self._account._lock:
            return canonical(
                dict(
                    schema="EVO884.TrainingReturnJournal/v1",
                    plan=self.plan(),
                    source_account_journal_sha256=sha256(self._account.export_bytes()),
                    historical_terminal_settlement=deepcopy(self._terminal),
                    runtime_consumable=False,
                    certifiable=False,
                )
            )

    def evaluate(self, benchmark, *, expected_benchmark_sha256):
        """Derive strategy returns; benchmark is a separately source-bound TR path.

        A source hash here is a binding, never an independent permission check.
        The benchmark adapter must be admitted by C09 before this method runs.
        No omissions, caller strategy-return vector, or scalar Sharpe is accepted.
        """
        output = dict(
            schema="EVO884.ExecutionReturns/v1",
            plan=self.plan(),
            dates=list(self._dates),
            daily_x2=None,
            daily_x1=None,
            active_daily=None,
            active_daily_x1=None,
            moments_daily=None,
            moments_daily_x1=None,
            annualized_IR=None,
            annualized_IR_x1=None,
            primary_A=None,
            primary_A_x1=None,
            terminal=None,
            complete=False,
            reasons=[],
            execution_verified=False,
            runtime_consumable=False,
            certifiable=False,
            producer_source_sha256=code_sha(TrainingReturns),
        )
        with self._account._lock:
            output["retained_account_sha256"] = self._account.snapshot()[
                "account_sha256"
            ]
            output["retained_close_count"] = len(self._account.close_receipts())
            try:
                benchmark = deepcopy(benchmark)
                snapshot, closes, x2, x1 = self._journal()
                terminal = self._settle(snapshot, closes)
                # Only the fixed terminal day pays this separate close order.
                # It cannot be netted against the same day's opening orders.
                previous = amount(closes[-2]["accounting"]["nav"])
                previous1 = amount(closes[-2]["x1_replay"]["NAV"])
                x2[-1] = amount(terminal["accounting"]["nav"]) / previous - 1
                x1[-1] = amount(terminal["x1_NAV"]) / previous1 - 1
                if (
                    type(benchmark) is not dict
                    or set(benchmark)
                    != {
                        "schema",
                        "dates",
                        "values",
                        "basis",
                        "source_sha256",
                        "symbol",
                        "role",
                    }
                    or benchmark["schema"] != "EVO884.BenchmarkDaily/v1"
                    or benchmark["basis"] != "analytical_TR"
                    or benchmark["symbol"] != "QQQ"
                    or benchmark["role"] != "B1"
                    or benchmark["dates"] != self._dates
                    or not is_sha(benchmark["source_sha256"])
                    or not is_sha(expected_benchmark_sha256)
                    or digest(benchmark) != expected_benchmark_sha256
                    or len(benchmark["values"]) != len(x2)
                    or any(not finite(v) or v <= -1 for v in benchmark["values"])
                ):
                    raise ValueError("returns.exact_source_bound_benchmark_required")
                values = [float(v) for v in x2]
                values1 = [float(v) for v in x1]
                active = [v - b for v, b in zip(values, benchmark["values"])]
                active1 = [v - b for v, b in zip(values1, benchmark["values"])]
                if not all(finite(v) for v in values + values1 + active + active1):
                    raise ValueError("returns.nonfinite_ratio_or_active_return")
                stats = moments(active, self._policy)
                stats1 = moments(active1, self._policy)
                ir, ir1 = (
                    math.sqrt(252) * stats["sharpe"],
                    math.sqrt(252) * stats1["sharpe"],
                )
                a, a1 = 252 * stats["mean"], 252 * stats1["mean"]
                if not all(
                    finite(v)
                    for v in list(stats.values())
                    + list(stats1.values())
                    + [ir, ir1, a, a1]
                ):
                    raise ValueError("returns.nonfinite_SR")
                output.update(
                    daily_x2=values,
                    daily_x1=values1,
                    active_daily=active,
                    active_daily_x1=active1,
                    moments_daily=stats,
                    moments_daily_x1=stats1,
                    annualized_IR=ir,
                    annualized_IR_x1=ir1,
                    primary_A=a,
                    primary_A_x1=a1,
                    terminal=terminal,
                    complete=True,
                    benchmark_sha256=expected_benchmark_sha256,
                    journal_sha256=digest(closes),
                )
            except (
                ValueError,
                KeyError,
                TypeError,
                ArithmeticError,
                IndexError,
            ) as exc:
                output["reasons"].append(
                    str(exc)
                    if isinstance(exc, ValueError)
                    else "returns.R2_necessary_state_unknown"
                )
        return dict(output, returns_sha256=digest(output))
