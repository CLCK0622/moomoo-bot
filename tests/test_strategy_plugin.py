"""Tests for the quant-strategies plugin接入点 (EVO-13 §4).

Shows an external-style strategy plugging in via the Strategy interface and being
re-validated through qlab's own gates — no performance claim is taken on faith.
"""

import unittest

from qlab.data.base import Bar
from qlab.pipeline import evaluate_candidate
from qlab.strategy.base import Strategy
from qlab.strategy.plugin import FunctionStrategy, load_strategy


def _flat_weights(bars):
    return [0.0 for _ in bars]


class TestFunctionStrategy(unittest.TestCase):
    def test_wraps_and_clamps(self):
        s = FunctionStrategy("ext", lambda bars: [5.0 for _ in bars])  # out of range
        bars = [Bar("2022-01-01", 1, 1, 1, 1), Bar("2022-01-02", 1, 1, 1, 1)]
        self.assertEqual(s.target_weights(bars), [1.0, 1.0])  # clamped to [-1, 1]

    def test_length_mismatch_raises(self):
        s = FunctionStrategy("ext", lambda bars: [1.0])
        with self.assertRaises(ValueError):
            s.target_weights([Bar("2022-01-01", 1, 1, 1, 1), Bar("2022-01-02", 1, 1, 1, 1)])


class TestLoadStrategy(unittest.TestCase):
    def test_loads_qlab_strategy_class(self):
        s = load_strategy("qlab.strategy.sma_cross:SmaCrossStrategy", fast=5, slow=20)
        self.assertIsInstance(s, Strategy)
        self.assertEqual(s.name, "sma_cross")

    def test_bad_spec(self):
        with self.assertRaises(ValueError):
            load_strategy("no_colon_here")

    def test_missing_attr(self):
        with self.assertRaises(ImportError):
            load_strategy("qlab.strategy.sma_cross:DoesNotExist")

    def test_non_strategy_rejected(self):
        # load_config() returns an AppConfig, not a Strategy -> rejected.
        with self.assertRaises(TypeError):
            load_strategy("qlab.config:load_config")


class TestPluginThroughGates(unittest.TestCase):
    def test_external_plugin_is_revalidated(self):
        # An external candidate (here a trivial flat plugin) must run the full gate
        # chain regardless of any claimed return. We assert the gates ran, not that
        # it passed.
        plugin = FunctionStrategy("external_candidate", _flat_weights)
        ev = evaluate_candidate("DEMO", strategy=plugin)
        self.assertEqual(len(ev.holdout.gates), 4)
        self.assertIn(
            ev.holdout.verdict,
            ["候选通过", "稳定性不足，未过线", "基线未达标"],
        )


if __name__ == "__main__":
    unittest.main()
