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


if __name__ == "__main__":
    unittest.main()
