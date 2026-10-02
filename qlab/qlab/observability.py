"""Structured, desensitized observability sink.

One JSONL file per channel under the run directory:
``signals, orders, fills, positions, equity, broker_events, errors, heartbeat``.
Plus a human-readable ``run.log``. All records pass through :func:`_redact`,
which strips anything that looks like a credential before it is written.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

CHANNELS = ["signals", "orders", "fills", "positions", "equity",
            "broker_events", "errors", "heartbeat"]

_SECRET_KEYS = re.compile(r"(password|passwd|pwd|token|secret|api[_-]?key|unlock)", re.I)


def _redact(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if _SECRET_KEYS.search(str(k)):
                out[k] = "***REDACTED***"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    return obj


class Observability:
    def __init__(self, run_dir: str | Path, also_stdout: bool = True):
        self.run_dir = Path(run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.also_stdout = also_stdout
        self._fh = {ch: open(self.run_dir / f"{ch}.jsonl", "a", encoding="utf-8")
                    for ch in CHANNELS}
        self._log = open(self.run_dir / "run.log", "a", encoding="utf-8")

    def _write(self, channel: str, record: dict) -> None:
        record = {"ts": time.time(), **_redact(record)}
        line = json.dumps(record, default=str)
        self._fh[channel].write(line + "\n")
        self._fh[channel].flush()
        if self.also_stdout:
            print(f"[{channel}] {line}")

    # --- typed channels ---
    def signal(self, **kw): self._write("signals", kw)
    def order(self, **kw): self._write("orders", kw)
    def fill(self, **kw): self._write("fills", kw)
    def position_snapshot(self, **kw): self._write("positions", kw)
    def equity(self, **kw): self._write("equity", kw)
    def broker_event(self, broker: str, event: str, **kw):
        self._write("broker_events", {"broker": broker, "event": event, **kw})
    def error(self, where: str, message: str, **kw):
        self._write("errors", {"where": where, "message": message, **kw})
    def heartbeat(self, **kw): self._write("heartbeat", kw)

    def text(self, msg: str) -> None:
        self._log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n")
        self._log.flush()
        if self.also_stdout:
            print(msg)

    def close(self) -> None:
        for fh in self._fh.values():
            fh.close()
        self._log.close()
