"""Unit tests for the four-gate logic (v1.0 §3)."""

import unittest

from qlab.config import GateConfig
from qlab.metrics.gates import (
    GateResult,
    decide_verdict,
    evaluate_gates,
    gate1_baseline,
    gate2_yearly,
    gate3_rolling,
    gate4_holdout,
)


def _daily(year, n, start=1):
    return [f"{year}-{(start + i) // 28 + 1:02d}-{(start + i) % 28 + 1:02d}" for i in range(n)]


class TestGate1(unittest.TestCase):
    def test_pass(self):
        g = gate1_baseline([100, 200], 1, GateConfig())  # CAGR 100%, MDD 0
        self.assertTrue(g.passed)
        self.assertAlmostEqual(g.metrics["cagr"], 1.0)

    def test_fail(self):
        g = gate1_baseline([100, 100], 1, GateConfig())
        self.assertFalse(g.passed)


class TestGate2(unittest.TestCase):
    def setUp(self):
        # two "full" years at P=8 (full_threshold = 6 return-bars).
        self.ts = _daily("2021", 8) + _daily("2022", 8)

    def test_two_complete_years(self):
        equity = [100 + i for i in range(16)]  # monotonic up
        cfg = GateConfig(target_cagr=0.0, yearly_min_cagr=-1.0, max_mdd=1.0)
        g = gate2_yearly(self.ts, equity, 8, cfg)
        self.assertTrue(g.passed)
        self.assertEqual(g.metrics["n_complete_years"], 2)
        self.assertEqual(len(g.metrics["per_year"]), 2)

    def test_negative_year_fails(self):
        # 2021 rises to 140, 2022 falls back to 120 (negative year).
        equity = [100 + i * 5 for i in range(8)] + [135 - i * 2 for i in range(8)]
        cfg = GateConfig(target_cagr=0.0, yearly_min_cagr=-1.0, max_mdd=1.0)
        g = gate2_yearly(self.ts, equity, 8, cfg)
        self.assertFalse(g.passed)
        self.assertIn("为负", g.notes)

    def test_no_complete_year_inconclusive(self):
        equity = [100 + i for i in range(16)]
        g = gate2_yearly(self.ts, equity, 100, GateConfig())  # threshold 75 >> 8
        self.assertFalse(g.conclusive)
        self.assertFalse(g.passed)


class TestGate3(unittest.TestCase):
    def test_windows_and_pass(self):
        equity = [100 + i for i in range(10)]
        cfg = GateConfig(
            rolling_window_bars=3, rolling_step_bars=1,
            target_cagr=0.0, rolling_median_min=-1.0,
            rolling_hit_ratio_min=0.0, rolling_negative_max=1.0, max_mdd=1.0,
        )
        g = gate3_rolling(equity, 252, cfg)
        self.assertTrue(g.passed)
        self.assertEqual(g.metrics["n_windows"], 7)  # range(0, 10-3, 1)
        self.assertIn("median", g.metrics["annual_distribution"])

    def test_insufficient_data(self):
        g = gate3_rolling([100, 110, 120], 252, GateConfig(rolling_window_bars=3))
        self.assertFalse(g.conclusive)
        self.assertFalse(g.passed)


class TestGate4(unittest.TestCase):
    def test_holdout_degradation(self):
        ts = ["2021-01-01", "2021-06-01", "2021-12-01"]
        equity = [100, 200, 210]
        g = gate4_holdout(ts, equity, "2021-06-01", 1, GateConfig())
        self.assertFalse(g.passed)  # OOS CAGR 5% < 50%
        self.assertAlmostEqual(g.metrics["degradation"], 0.95, places=2)

    def test_no_oos_inconclusive(self):
        g = gate4_holdout(["2021-01-01", "2021-02-01"], [100, 110], None, 1, GateConfig())
        self.assertFalse(g.conclusive)


class TestVerdict(unittest.TestCase):
    def _r(self, key, passed):
        return GateResult(key=key, title=key, passed=passed)

    def test_all_pass(self):
        v = decide_verdict([self._r("gate1", True), self._r("gate2", True)])
        self.assertEqual(v.verdict, "候选通过")
        self.assertEqual(v.blocking, [])

    def test_baseline_fail(self):
        v = decide_verdict([self._r("gate1", False), self._r("gate2", True)])
        self.assertEqual(v.verdict, "基线未达标")

    def test_stability_fail(self):
        v = decide_verdict([self._r("gate1", True), self._r("gate3", False)])
        self.assertEqual(v.verdict, "稳定性不足，未过线")
        self.assertIn("gate3", v.blocking)

    def test_evaluate_gates_wf_skips_holdout(self):
        ts = _daily("2021", 8) + _daily("2022", 8)
        equity = [100 + i for i in range(16)]
        v = evaluate_gates(ts, equity, 8, GateConfig(), include_holdout=False)
        keys = [g.key for g in v.gates]
        self.assertNotIn("gate4", keys)
        self.assertEqual(len(v.gates), 3)


if __name__ == "__main__":
    unittest.main()
