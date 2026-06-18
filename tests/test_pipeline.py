import os
import tempfile
import unittest

from qlab.config import load_config
from qlab.pipeline import run_backtest, train_and_backtest


class TestEndToEnd(unittest.TestCase):
    """Prove the whole chain runs on fixtures with no real market data."""

    def test_run_backtest_full_chain(self):
        out = run_backtest("DEMO")
        self.assertGreater(len(out.bars), 0)
        self.assertEqual(len(out.result.equity_curve), len(out.bars))
        self.assertIsNotNone(out.metrics.oos_period)

    def test_train_persist_and_backtest(self):
        with tempfile.TemporaryDirectory() as d:
            model_path = os.path.join(d, "model.json")
            out = train_and_backtest("DEMO", model_path=model_path)
            self.assertTrue(os.path.exists(model_path))
            self.assertEqual(out.result.strategy, "momentum_model")
            self.assertGreater(len(out.result.equity_curve), 0)

    def test_config_defaults(self):
        cfg = load_config()
        self.assertGreater(cfg.backtest.initial_cash, 0)
        self.assertFalse(cfg.moomoo.enabled)  # never auto-enabled


if __name__ == "__main__":
    unittest.main()
