import os
import tempfile
import unittest

from qlab.data.base import Bar, DataSource
from qlab.data.fixture import FixtureDataSource


class TestFixtureSource(unittest.TestCase):
    def test_synthetic_is_deterministic(self):
        src = FixtureDataSource(fixtures_dir="/nonexistent", synthetic_days=120)
        a = src.load("DEMO")
        b = src.load("DEMO")
        self.assertEqual(len(a), 120)
        self.assertEqual([x.close for x in a], [x.close for x in b])

    def test_bars_sorted_and_valid(self):
        bars = FixtureDataSource("/nonexistent", synthetic_days=60).load("AAPL")
        ts = [b.ts for b in bars]
        self.assertEqual(ts, sorted(ts))
        for bar in bars:
            self.assertGreaterEqual(bar.high, bar.low)
            self.assertGreater(bar.close, 0)

    def test_date_range_filter(self):
        bars = FixtureDataSource("/nonexistent", synthetic_days=200).load("X")
        start, end = bars[10].ts, bars[20].ts
        filtered = FixtureDataSource("/nonexistent", synthetic_days=200).load("X", start, end)
        self.assertTrue(all(start <= b.ts <= end for b in filtered))

    def test_csv_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "TST.csv")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("ts,open,high,low,close,volume\n")
                fh.write("2022-01-03,10,11,9,10.5,1000\n")
                fh.write("2022-01-04,10.5,12,10,11,1200\n")
            bars = FixtureDataSource(d).load("TST")
            self.assertEqual(len(bars), 2)
            self.assertEqual(bars[0].close, 10.5)


class TestNormalisation(unittest.TestCase):
    def test_rejects_high_below_low(self):
        class Bad(DataSource):
            def _fetch(self, symbol, start, end):
                return [Bar("2022-01-03", 10, 9, 11, 10)]

        with self.assertRaises(ValueError):
            Bad().load("X")

    def test_dedup(self):
        class Dup(DataSource):
            def _fetch(self, symbol, start, end):
                return [Bar("2022-01-03", 10, 11, 9, 10), Bar("2022-01-03", 10, 11, 9, 99)]

        bars = Dup().load("X")
        self.assertEqual(len(bars), 1)


if __name__ == "__main__":
    unittest.main()
