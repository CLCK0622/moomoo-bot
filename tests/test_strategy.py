import unittest

from qlab.data.base import Bar
from qlab.strategy.sma_cross import SmaCrossStrategy


def _bars(closes):
    return [Bar(f"2022-01-{i + 1:02d}", c, c, c, c) for i, c in enumerate(closes)]


class TestSmaCross(unittest.TestCase):
    def test_one_weight_per_bar(self):
        bars = _bars([float(i) for i in range(50)])
        w = SmaCrossStrategy(5, 10).target_weights(bars)
        self.assertEqual(len(w), len(bars))

    def test_warmup_is_flat(self):
        bars = _bars([float(i) for i in range(50)])
        w = SmaCrossStrategy(5, 10).target_weights(bars)
        self.assertTrue(all(x == 0.0 for x in w[:9]))

    def test_uptrend_goes_long(self):
        bars = _bars([float(i) for i in range(1, 51)])  # monotonic up
        w = SmaCrossStrategy(5, 10).target_weights(bars)
        self.assertEqual(w[-1], 1.0)

    def test_no_short_by_default(self):
        bars = _bars([float(i) for i in range(50, 0, -1)])  # monotonic down
        w = SmaCrossStrategy(5, 10).target_weights(bars)
        self.assertTrue(all(x >= 0.0 for x in w))

    def test_short_when_enabled(self):
        bars = _bars([float(i) for i in range(50, 0, -1)])
        w = SmaCrossStrategy(5, 10, allow_short=True).target_weights(bars)
        self.assertEqual(w[-1], -1.0)

    def test_invalid_windows(self):
        with self.assertRaises(ValueError):
            SmaCrossStrategy(10, 10)


if __name__ == "__main__":
    unittest.main()
