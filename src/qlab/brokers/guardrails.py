"""Broker safety guardrails (EVO-13 §3 硬要求).

These are the reusable, broker-agnostic safety primitives every live trade path
must go through. All are pure-stdlib and unit-tested without any broker SDK:

- :class:`KillSwitch`   全局急停: process flag + optional file + env, fail-safe.
- :class:`RateLimiter`  限频: sliding-window cap on order submission.
- :func:`mask_secret`   日志脱敏: never log a full account id / password / token.
- :func:`call_with_retry` 连接异常重连/降级: bounded retry with backoff.

Time and sleep are injectable so the logic is deterministic in tests.
"""

from __future__ import annotations

import os
import time
from collections import deque
from typing import Callable


class SafetyError(RuntimeError):
    """Raised when a guardrail blocks an action (kill switch, rate cap, mode, ...)."""


def mask_secret(value: str | None, *, keep: int = 2) -> str:
    """Mask a secret for logging: keep at most the last ``keep`` chars.

    ``None``/empty -> ``"<unset>"``. ``keep <= 0`` (or values no longer than
    ``keep``) are fully masked so nothing sensitive (account id, unlock password,
    token) is ever logged in the clear. ``keep=0`` is the right choice for
    low-entropy secrets such as a 6-digit unlock PIN, where even the tail leaks
    too much.
    """
    if not value:
        return "<unset>"
    if keep <= 0 or len(value) <= keep:
        return "*" * len(value)
    return "*" * (len(value) - keep) + value[-keep:]


class KillSwitch:
    """Global emergency stop. Fail-safe: when in doubt, treat as tripped.

    Tripped state is true if ANY of: the in-process flag is set, the env var is
    truthy, or the sentinel file exists. The file lets an operator (or another
    process) halt all trading out-of-band by simply creating it.
    """

    def __init__(self, path: str | None = None, env_var: str = "MOOMOO_KILL_SWITCH") -> None:
        self.path = path
        self.env_var = env_var
        self._tripped = False
        self._reason = ""

    def trip(self, reason: str = "manual") -> None:
        self._tripped = True
        self._reason = reason
        if self.path:
            try:
                with open(self.path, "w", encoding="utf-8") as fh:
                    fh.write(reason)
            except OSError:
                pass  # in-process flag still holds; never crash the kill path

    def reset(self) -> None:
        self._tripped = False
        self._reason = ""
        if self.path and os.path.exists(self.path):
            try:
                os.remove(self.path)
            except OSError:
                pass

    def is_tripped(self) -> bool:
        if self._tripped:
            return True
        env = os.environ.get(self.env_var, "")
        if env.strip().lower() in {"1", "true", "yes", "on"}:
            return True
        return bool(self.path and os.path.exists(self.path))

    @property
    def reason(self) -> str:
        return self._reason

    def require_clear(self) -> None:
        if self.is_tripped():
            raise SafetyError(f"kill switch is tripped (reason={self._reason or 'external'})")


class RateLimiter:
    """Sliding-window rate limiter: at most ``max_calls`` per ``per_seconds``.

    ``allow()`` is non-blocking and records the call if permitted; ``acquire()``
    raises :class:`SafetyError` when the cap is exceeded. ``time_fn`` is injectable
    for deterministic tests.
    """

    def __init__(
        self,
        max_calls: int,
        per_seconds: float,
        *,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_calls = max_calls
        self.per_seconds = per_seconds
        self._time = time_fn
        self._calls: deque[float] = deque()

    def allow(self, now: float | None = None) -> bool:
        now = self._time() if now is None else now
        while self._calls and now - self._calls[0] >= self.per_seconds:
            self._calls.popleft()
        if len(self._calls) < self.max_calls:
            self._calls.append(now)
            return True
        return False

    def acquire(self, now: float | None = None) -> None:
        if not self.allow(now):
            raise SafetyError(
                f"order rate limit exceeded ({self.max_calls}/{self.per_seconds:g}s)"
            )


def call_with_retry(
    fn: Callable[[], object],
    *,
    retries: int = 3,
    backoff_seconds: float = 0.5,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    sleep_fn: Callable[[float], None] = time.sleep,
):
    """Call ``fn`` with bounded linear backoff. Re-raises after ``retries`` attempts.

    Used to wrap broker connect / query so a transient OpenD hiccup reconnects
    rather than crashing; callers degrade to fail-safe (no trade) on final failure.
    """
    attempt = 0
    while True:
        try:
            return fn()
        except exceptions:
            attempt += 1
            if attempt > retries:
                raise
            sleep_fn(backoff_seconds * attempt)
