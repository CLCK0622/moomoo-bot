import json
import os
import tempfile
import unittest

from qlab.backtest.engine import BacktestRunner
from qlab.config import BacktestConfig, CostConfig
from qlab.data.fixture import FixtureDataSource
from qlab.report.metrics import compute_metrics
from qlab.report.report import ReportGenerator
from qlab.strategy.sma_cross import SmaCrossStrategy


class TestMetricsAndReport(unittest.TestCase):
    def setUp(self):
        bars = FixtureDataSource("/nonexistent", synthetic_days=400).load("DEMO")
        runner = BacktestRunner(CostConfig(), BacktestConfig(oos_fraction=0.3))
        self.result = runner.run("DEMO", bars, SmaCrossStrategy(10, 30))

    def test_hubu_fields_present(self):
        m = compute_metrics(self.result)
        # 户部口径 fields must all be produced.
        self.assertIsInstance(m.annualized_return, float)  # 年化收益
        self.assertLessEqual(m.max_drawdown, 0.0)  # 最大回撤 (<=0)
        self.assertGreater(len(m.yearly_returns), 0)  # 分年度表现
        self.assertGreaterEqual(m.total_commission, 0.0)  # 交易成本
        self.assertGreaterEqual(m.total_slippage, 0.0)  # 滑点
        self.assertIsNotNone(m.oos_period)  # 样本外区间
        self.assertIsNotNone(m.in_sample)
        self.assertIsNotNone(m.out_of_sample)

    def test_markdown_has_disclaimer(self):
        md = ReportGenerator().to_markdown(self.result)
        self.assertIn("fixture", md)
        self.assertIn("年化收益", md)
        self.assertIn("样本外", md)

    def test_write_produces_files(self):
        with tempfile.TemporaryDirectory() as d:
            paths = ReportGenerator().write(self.result, d)
            self.assertTrue(os.path.exists(paths["markdown"]))
            self.assertTrue(os.path.exists(paths["json"]))
            with open(paths["json"], encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertIn("annualized_return", data)
            self.assertIn("yearly_returns", data)


if __name__ == "__main__":
    unittest.main()
