import os
import tempfile
import unittest

from qlab.data.fixture import FixtureDataSource
from qlab.model.base import load_model
from qlab.model.momentum import MomentumModel


class TestMomentumModel(unittest.TestCase):
    def setUp(self):
        self.bars = FixtureDataSource("/nonexistent", synthetic_days=200).load("DEMO")

    def test_fit_returns_self_and_sets_lookback(self):
        model = MomentumModel().fit(self.bars)
        self.assertIn(model.lookback, (5, 10, 20, 40, 60))

    def test_predict_one_per_bar_and_bounded(self):
        model = MomentumModel().fit(self.bars)
        preds = model.predict(self.bars)
        self.assertEqual(len(preds), len(self.bars))
        self.assertTrue(all(p in (0.0, 1.0) for p in preds))

    def test_persistence_roundtrip(self):
        model = MomentumModel().fit(self.bars)
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "m.json")
            model.save(path)
            self.assertTrue(os.path.exists(path))
            reloaded = load_model(path)
            self.assertIsInstance(reloaded, MomentumModel)
            self.assertEqual(reloaded.predict(self.bars), model.predict(self.bars))

    def test_unknown_kind_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bad.json")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write('{"kind": "nope", "params": {}}')
            with self.assertRaises(KeyError):
                load_model(path)


if __name__ == "__main__":
    unittest.main()
