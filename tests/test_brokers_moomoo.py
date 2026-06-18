"""Unit tests for the moomoo trade gateway + quote source guardrails.

A fake OpenD context drives the real order-build / guardrail logic without the futu
SDK or a live gateway.
"""

import unittest

from qlab.brokers.guardrails import KillSwitch, RateLimiter, SafetyError
from qlab.brokers.moomoo import MoomooConfigError, MoomooQuoteSource, MoomooTradeGateway
from qlab.config import MoomooConfig


class FakeTradeCtx:
    def __init__(self, unlock_ret=0):
        self.calls = []
        self.unlock_ret = unlock_ret
        self.cancelled = False
        self.closed = False

    def unlock_trade(self, pwd):
        self.calls.append(("unlock", pwd))
        return (self.unlock_ret, {"msg": "ok"})

    def accinfo_query(self, trd_env):
        self.calls.append(("accinfo", trd_env))
        return (0, {"cash": [1000.0], "total_assets": [2000.0], "power": [1500.0]})

    def place_order(self, **kw):
        self.calls.append(("place", kw))
        return (0, {"order_id": ["OID123"], "code": [kw["code"]]})

    def position_list_query(self, trd_env):
        self.calls.append(("positions", trd_env))
        return (0, [{"code": "US.AAPL", "qty": 100, "cost_price": 50.0}])

    def order_list_query(self, trd_env):
        self.calls.append(("orders", trd_env))
        return (0, [{"order_id": "OID1", "code": "US.AAPL", "qty": 100}])

    def modify_order(self, **kw):
        self.calls.append(("modify", kw))
        return (0, {"order_id": [kw.get("order_id")]})

    def cancel_all_order(self):
        self.cancelled = True

    def close(self):
        self.closed = True


def _sim_config(**kw):
    base = dict(enabled=True, allow_orders=True, account_id="ACC-XYZ", trade_env="SIMULATE")
    base.update(kw)
    return MoomooConfig(**base)


def _gateway(config, ctx=None, **kw):
    ctx = ctx or FakeTradeCtx()
    gw = MoomooTradeGateway(config, context_factory=lambda: ctx, **kw)
    return gw, ctx


class TestGatewayGuardrails(unittest.TestCase):
    def test_disabled_refuses(self):
        gw, _ = _gateway(MoomooConfig(enabled=False))
        with self.assertRaises(MoomooConfigError):
            gw.place_market_order("AAPL", "BUY", 10)

    def test_auto_trading_off_by_default(self):
        gw, _ = _gateway(_sim_config(allow_orders=False))
        with self.assertRaises(SafetyError):
            gw.place_market_order("AAPL", "BUY", 10)

    def test_requires_account_id(self):
        gw, _ = _gateway(_sim_config(account_id=None))
        with self.assertRaises(MoomooConfigError):
            gw.place_market_order("AAPL", "BUY", 10)

    def test_simulate_order_placed(self):
        gw, ctx = _gateway(_sim_config())
        ack = gw.place_market_order("AAPL", "BUY", 10)
        self.assertEqual(ack["order_id"], "OID123")
        place = [c for c in ctx.calls if c[0] == "place"][0][1]
        self.assertEqual(place["code"], "US.AAPL")
        self.assertEqual(place["trd_side"], "BUY")
        self.assertEqual(place["trd_env"], "SIMULATE")

    def test_real_blocked_without_allow_real(self):
        gw, _ = _gateway(_sim_config(trade_env="REAL", unlock_pwd="pw"))
        with self.assertRaises(SafetyError):
            gw.place_market_order("AAPL", "BUY", 10)

    def test_real_requires_unlock_pwd(self):
        gw, _ = _gateway(_sim_config(trade_env="REAL", allow_real=True, unlock_pwd=None))
        with self.assertRaises(SafetyError):
            gw.place_market_order("AAPL", "BUY", 10)

    def test_real_unlocks_then_orders(self):
        cfg = _sim_config(trade_env="REAL", allow_real=True, unlock_pwd="secret")
        gw, ctx = _gateway(cfg)
        gw.place_market_order("AAPL", "BUY", 5)
        self.assertIn(("unlock", "secret"), ctx.calls)
        self.assertTrue(gw._unlocked)

    def test_kill_switch_blocks(self):
        ks = KillSwitch()
        ks.trip("halt")
        gw, _ = _gateway(_sim_config(), kill_switch=ks)
        with self.assertRaises(SafetyError):
            gw.place_market_order("AAPL", "BUY", 10)

    def test_emergency_stop_cancels(self):
        gw, ctx = _gateway(_sim_config())
        gw.account_info()  # establishes a connection
        gw.emergency_stop("panic")
        self.assertTrue(gw.kill.is_tripped())
        self.assertTrue(ctx.cancelled)

    def test_rate_limit(self):
        gw, _ = _gateway(_sim_config(), rate_limiter=RateLimiter(1, 100.0))
        gw.place_market_order("AAPL", "BUY", 1)
        with self.assertRaises(SafetyError):
            gw.place_market_order("AAPL", "BUY", 1)

    def test_positive_qty(self):
        gw, _ = _gateway(_sim_config())
        with self.assertRaises(ValueError):
            gw.place_market_order("AAPL", "BUY", 0)

    def test_max_order_qty_cap(self):
        gw, ctx = _gateway(_sim_config(max_order_qty=100))
        gw.place_market_order("AAPL", "BUY", 100)  # at the cap: allowed
        with self.assertRaises(SafetyError):
            gw.place_market_order("AAPL", "BUY", 101)  # over the cap: blocked
        # the rejected order must not have reached the broker
        self.assertEqual(len([c for c in ctx.calls if c[0] == "place"]), 1)

    def test_no_qty_cap_by_default(self):
        gw, _ = _gateway(_sim_config())  # max_order_qty None -> uncapped
        gw.place_market_order("AAPL", "BUY", 1_000_000)


class TestTargetPosition(unittest.TestCase):
    def test_buy_sell_and_noop(self):
        gw, ctx = _gateway(_sim_config())
        self.assertIsNone(gw.submit_target_position("AAPL", 100, 100))  # no delta
        gw.submit_target_position("AAPL", 100, 0)  # buy 100
        gw.submit_target_position("AAPL", 0, 100)  # sell 100
        sides = [c[1]["trd_side"] for c in ctx.calls if c[0] == "place"]
        self.assertEqual(sides, ["BUY", "SELL"])


class TestAccountInfo(unittest.TestCase):
    def test_account_info(self):
        gw, _ = _gateway(_sim_config())
        info = gw.account_info()
        self.assertEqual(info["cash"], 1000.0)
        self.assertEqual(info["total_assets"], 2000.0)


class TestPositionsOrdersCancel(unittest.TestCase):
    def test_positions(self):
        gw, _ = _gateway(_sim_config())
        pos = gw.positions()
        self.assertEqual(pos[0]["code"], "US.AAPL")
        self.assertEqual(pos[0]["qty"], 100)

    def test_open_orders(self):
        gw, _ = _gateway(_sim_config())
        orders = gw.open_orders()
        self.assertEqual(orders[0]["order_id"], "OID1")

    def test_cancel_order(self):
        gw, ctx = _gateway(_sim_config())
        gw.cancel_order("OID1")
        modify = [c for c in ctx.calls if c[0] == "modify"][0][1]
        self.assertEqual(modify["order_id"], "OID1")
        self.assertEqual(modify["modify_order_op"], "CANCEL")

    def test_cancel_blocked_by_kill_switch(self):
        ks = KillSwitch()
        ks.trip("halt")
        gw, _ = _gateway(_sim_config(), kill_switch=ks)
        with self.assertRaises(SafetyError):
            gw.cancel_order("OID1")


class FakeQuoteCtx:
    def __init__(self):
        self.closed = False

    def request_history_kline(self, code, start=None, end=None):
        rows = [
            {"time_key": "2022-01-03 00:00:00", "open": 10, "high": 11,
             "low": 9, "close": 10.5, "volume": 100},
            {"time_key": "2022-01-04 00:00:00", "open": 10.5, "high": 12,
             "low": 10, "close": 11, "volume": 120},
        ]
        return (0, rows)

    def close(self):
        self.closed = True


class TestQuoteSource(unittest.TestCase):
    def test_disabled_refuses(self):
        src = MoomooQuoteSource(MoomooConfig(enabled=False))
        with self.assertRaises(MoomooConfigError):
            src.load("US.AAPL")

    def test_fetch_maps_to_bars(self):
        ctx = FakeQuoteCtx()
        src = MoomooQuoteSource(MoomooConfig(enabled=True), context_factory=lambda: ctx)
        bars = src.load("AAPL")
        self.assertEqual(len(bars), 2)
        self.assertEqual(bars[0].ts, "2022-01-03")
        self.assertEqual(bars[1].close, 11.0)
        self.assertTrue(ctx.closed)


if __name__ == "__main__":
    unittest.main()
