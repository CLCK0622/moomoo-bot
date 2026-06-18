"""End-to-end: evaluate_candidate + 评估卡 assembly (B/C/D/E) on fixtures."""

import json
import os
import tempfile
import unittest

from qlab.model.momentum import MomentumModel
from qlab.pipeline import evaluate_candidate
from qlab.report.evaluation_card import build_card_dict, to_markdown, write_card
from qlab.strategy.sma_cross import SmaCrossStrategy


class TestEvaluateCandidate(unittest.TestCase):
    def test_static_strategy_full_chain(self):
        ev = evaluate_candidate("DEMO", strategy=SmaCrossStrategy(10, 30))
        # Core metrics populated.
        self.assertGreater(ev.core.n_closed_trades, 0)
        self.assertLessEqual(ev.core.max_drawdown, 1.0)
        # Four gates present (hold-out includes gate4).
        self.assertEqual(len(ev.holdout.gates), 4)
        self.assertIn(ev.holdout.verdict, ["候选通过", "稳定性不足，未过线", "基线未达标"])
        # Cost x2 stress computed.
        self.assertIsInstance(ev.cost_stress.stressed_pass, bool)
        # No walk-forward for a static strategy.
        self.assertIsNone(ev.walk_forward)

    def test_model_with_walk_forward(self):
        ev = evaluate_candidate(
            "DEMO", model_factory=MomentumModel, walk_forward=True,
            wf_train_bars=252, wf_test_bars=63,
        )
        self.assertIsNotNone(ev.walk_forward)
        self.assertGreater(ev.wf_meta["n_folds"], 1)
        # WF curve judged on gates 1-3 only (no hold-out gate4).
        self.assertEqual(len(ev.walk_forward.gates), 3)


class TestCardRendering(unittest.TestCase):
    def setUp(self):
        self.ev = evaluate_candidate("DEMO", strategy=SmaCrossStrategy(10, 30))

    def test_markdown_has_all_sections(self):
        md = to_markdown(self.ev)
        for section in ["## B.", "## C.", "## D.", "## E.", "成本×2", "几何 CAGR", "门禁四关"]:
            self.assertIn(section, md)
        self.assertIn("fixture", md)  # disclaimer present

    def test_dict_structure(self):
        d = build_card_dict(self.ev)
        for key in ["meta", "B_cost_registration", "C_core_metrics", "D_gates", "E_bias_checklist"]:
            self.assertIn(key, d)
        self.assertIn("cost_x2_pass", d["B_cost_registration"])
        self.assertEqual(len(d["E_bias_checklist"]), 7)

    def test_write_card_files(self):
        with tempfile.TemporaryDirectory() as out:
            paths = write_card(self.ev, out)
            self.assertTrue(os.path.exists(paths["markdown"]))
            self.assertTrue(os.path.exists(paths["json"]))
            with open(paths["json"], encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertIn("C_core_metrics", data)


class TestCardJsonInfSerialization(unittest.TestCase):
    """Regression: a zero-loss (all-wins) candidate must still write strict JSON.

    With every closed trade profitable, ``trade_stats`` sets profit_factor and
    profit_loss_ratio to ``float('inf')``. The JSON card must coerce those to
    ``null`` and never emit non-standard ``Infinity``/``NaN`` tokens, so strict
    ``json.loads`` succeeds for downstream consumers.
    """

    def _all_wins_ev(self):
        from qlab.metrics.trades import trade_stats

        # All-profit round trips → inf ratios, exercising the JSON path.
        stats = trade_stats([100.0, 50.0, 25.0])
        self.assertEqual(stats.profit_factor, float("inf"))
        self.assertEqual(stats.profit_loss_ratio, float("inf"))

        ev = evaluate_candidate("DEMO", strategy=SmaCrossStrategy(10, 30))
        # Inject the inf-bearing trade stats into the core metrics.
        ev.core.profit_factor = stats.profit_factor
        ev.core.profit_loss_ratio = stats.profit_loss_ratio
        return ev

    def test_build_card_dict_carries_inf(self):
        ev = self._all_wins_ev()
        d = build_card_dict(ev)
        self.assertEqual(d["C_core_metrics"]["profit_factor"], float("inf"))

    def test_written_json_is_strictly_parseable_and_finite(self):
        ev = self._all_wins_ev()
        with tempfile.TemporaryDirectory() as out:
            paths = write_card(ev, out)
            with open(paths["json"], encoding="utf-8") as fh:
                raw = fh.read()
            # No non-standard JSON tokens in the serialized text.
            self.assertNotIn("Infinity", raw)
            self.assertNotIn("NaN", raw)
            # Strict parser must accept it (json.loads rejects Infinity/NaN-free text only).
            data = json.loads(raw)
            core = data["C_core_metrics"]
            self.assertIsNone(core["profit_factor"])
            self.assertIsNone(core["profit_loss_ratio"])

    def test_markdown_still_shows_infinity_symbol(self):
        # Markdown rendering keeps ∞ — only the JSON path is normalised.
        ev = self._all_wins_ev()
        md = to_markdown(ev)
        self.assertIn("∞", md)


if __name__ == "__main__":
    unittest.main()
