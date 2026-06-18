"""Unit tests for the broker safety guardrails (EVO-13 §3)."""

import os
import tempfile
import unittest

from qlab.brokers.guardrails import (
    KillSwitch,
    RateLimiter,
    SafetyError,
    call_with_retry,
    mask_secret,
)


class TestMaskSecret(unittest.TestCase):
    def test_none_and_empty(self):
        self.assertEqual(mask_secret(None), "<unset>")
        self.assertEqual(mask_secret(""), "<unset>")

    def test_short_fully_masked(self):
        self.assertEqual(mask_secret("ab", keep=2), "**")

    def test_keeps_tail_only(self):
        self.assertEqual(mask_secret("762185", keep=2), "****85")
        self.assertNotIn("762185", mask_secret("762185"))


class TestKillSwitch(unittest.TestCase):
    def test_trip_reset_in_process(self):
        ks = KillSwitch()
        self.assertFalse(ks.is_tripped())
        ks.trip("panic")
        self.assertTrue(ks.is_tripped())
        self.assertEqual(ks.reason, "panic")
        with self.assertRaises(SafetyError):
            ks.require_clear()
        ks.reset()
        self.assertFalse(ks.is_tripped())

    def test_file_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "kill")
            KillSwitch(path).trip("ops")
            # A fresh instance pointed at the same file sees the trip (cross-process).
            self.assertTrue(KillSwitch(path).is_tripped())
            KillSwitch(path).reset()
            self.assertFalse(KillSwitch(path).is_tripped())

    def test_env_var(self):
        ks = KillSwitch(env_var="QLAB_TEST_KILL")
        os.environ["QLAB_TEST_KILL"] = "1"
        try:
            self.assertTrue(ks.is_tripped())
        finally:
            del os.environ["QLAB_TEST_KILL"]


class TestRateLimiter(unittest.TestCase):
    def test_cap_and_window(self):
        rl = RateLimiter(2, 10.0)
        self.assertTrue(rl.allow(now=0.0))
        self.assertTrue(rl.allow(now=1.0))
        self.assertFalse(rl.allow(now=2.0))  # cap hit
        self.assertTrue(rl.allow(now=11.5))  # first call aged out

    def test_acquire_raises(self):
        rl = RateLimiter(1, 100.0)
        rl.acquire(now=0.0)
        with self.assertRaises(SafetyError):
            rl.acquire(now=1.0)


class TestRetry(unittest.TestCase):
    def test_succeeds_after_failures(self):
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ConnectionError("transient")
            return "ok"

        out = call_with_retry(flaky, retries=3, sleep_fn=lambda *_: None)
        self.assertEqual(out, "ok")
        self.assertEqual(calls["n"], 3)

    def test_exhausts_and_raises(self):
        def always_fail():
            raise ConnectionError("down")

        with self.assertRaises(ConnectionError):
            call_with_retry(always_fail, retries=2, sleep_fn=lambda *_: None)


if __name__ == "__main__":
    unittest.main()
