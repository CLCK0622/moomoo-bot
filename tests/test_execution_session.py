"""End-to-end paper session: signals → marks (fixture) → risk → paper broker."""

import unittest

from qlab.config import load_config
from qlab.execution.session import build_marks, run_execution
from qlab.execution.signals import SignalSet, TargetSignal


class TestPaperSession(unittest.TestCase):
    def setUp(self):
        self.sig = SignalSet(
            signals=[TargetSignal("TSLA", 0.2), TargetSignal("NVDA", 0.2)],
            source="test",
        )

    def test_marks_from_fixture(self):
        marks, prev = build_marks(["TSLA", "NVDA"], "fixtures")
        self.assertIn("TSLA", marks)
        self.assertGreater(marks["TSLA"], 0)
        self.assertIn("NVDA", prev)

    def test_paper_run_through(self):
        cfg = load_config({"QLAB_EXEC_MODE": "paper", "QLAB_EXEC_CASH": "100000"})
        rec = run_execution(self.sig, cfg, mode="paper")
        self.assertEqual(rec.mode, "paper")
        self.assertGreater(rec.equity_before, 0)
        # Either filled or risk-rejected, but the cycle ran and stayed observable.
        self.assertEqual(len(rec.filled) + len(rec.rejected) + len(rec.skipped), 2)

    def test_dry_run_mode(self):
        cfg = load_config({"QLAB_EXEC_MODE": "dry_run"})
        rec = run_execution(self.sig, cfg, mode="dry_run")
        self.assertEqual(rec.mode, "dry_run")


if __name__ == "__main__":
    unittest.main()
