"""Run the non-round-day LLM-paper archive scanner for a scheduler.

Typical autopilot command (from the repository root)::

    python3 qlab/tools/run_llm_paper_archive_scan.py \
        --out-dir qlab/reports/llm_paper

Exit codes are deliberately machine-readable: 0 = clean (no quote call),
10 = compact bars captured, 20 = hard window alert (whether or not capture
succeeded), 30 = a real scan failure, and 40 = an expected safety refusal on a
non-scan day.  The scanner itself rejects Monday and weekends; this wrapper
never relaxes that safety boundary.  On an eligible day it imports only
``ALPHAVANTAGE_API_KEY`` from the owner-only existing
``~/.config/alphavantage/api.env`` into this process; it never sources a shell
profile or prints the value.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

_REPO_ROOT = Path(__file__).resolve().parents[2]
_QLAB_ROOT = _REPO_ROOT / "qlab"
for _path in (str(_QLAB_ROOT), str(_REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from qlab.llm_paper.archive_scanner import (ScanDayRefused, archive_scan_coverage,
                                             require_scan_day,
                                             scan_missing_archive_bars)  # noqa: E402

EXIT_CLEAN = 0
EXIT_CAPTURED = 10
EXIT_HARD_ALERT = 20
EXIT_FAILED = 30
EXIT_REFUSED_NON_SCAN_DAY = 40
_API_ENV_FILE = Path.home() / ".config" / "alphavantage" / "api.env"


class ApiEnvConfigError(RuntimeError):
    """The scanner's process-local credential file is present but unsafe."""


def _load_process_api_key() -> bool:
    """Load only ALPHAVANTAGE_API_KEY into this scanner process.

    No shell profile is sourced and no unrelated variable is imported.  A
    missing file remains the existing ``MissingApiKey`` failure in the quote
    client; an existing file must be a regular, owner-only file.
    """
    if os.environ.get("ALPHAVANTAGE_API_KEY"):
        return False
    path = _API_ENV_FILE
    if not path.exists():
        return False
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise ApiEnvConfigError("Alpha Vantage api.env 不是普通文件，拒绝加载")
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise ApiEnvConfigError("Alpha Vantage api.env 必须归当前用户所有且权限为 0600")

    candidates = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" in line:
            name, value = line.split("=", 1)
            if name.strip() != "ALPHAVANTAGE_API_KEY":
                continue
        else:
            value = line
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if value:
            candidates.append(value)
    if not candidates:
        return False
    if len(set(candidates)) != 1:
        raise ApiEnvConfigError("Alpha Vantage api.env 含多个不一致的 key，拒绝猜测")
    os.environ["ALPHAVANTAGE_API_KEY"] = candidates[0]
    return True


def _summary(result: Dict[str, Any], *, exit_code: int, status: str) -> Dict[str, Any]:
    coverage = result.get("coverage_after") or {}
    return {
        "status": status,
        "exit_code": exit_code,
        "requested_symbols": result.get("requested_symbols") or [],
        "coverage": {
            "missing_count": coverage.get("missing_count"),
            "oldest_missing": coverage.get("oldest_missing"),
            "hard_alert_count": len(coverage.get("hard_alerts") or []),
            "ageing_clock": coverage.get("ageing_clock"),
        },
        "scan_report": (result.get("scan_report") or {}).get("file"),
        "alert_file": (result.get("alert") or {}).get("file"),
    }


def _failure_coverage(out_dir: str, stamp: str) -> Dict[str, Any]:
    """Best-effort, read-only coverage for exit 30; never mask the root error."""
    try:
        coverage = archive_scan_coverage(out_dir, as_of=stamp)
    except Exception as exc:  # corrupt/missing evidence is itself useful diagnostics
        return {"diagnostic_error_type": type(exc).__name__, "diagnostic_error": str(exc)}
    return {
        "missing_count": coverage.get("missing_count"),
        "oldest_missing": coverage.get("oldest_missing"),
        "hard_alert_count": len(coverage.get("hard_alerts") or []),
        "ageing_clock": coverage.get("ageing_clock"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="qlab/reports/llm_paper",
                        help="LLM-paper report directory (default: %(default)s)")
    parser.add_argument("--stamp", default=datetime.now(timezone.utc).date().isoformat(),
                        help="scan date, YYYY-MM-DD or parseable timestamp (default: current UTC date)")
    parser.add_argument("--benchmark", default="SPY", help="archive benchmark symbol (default: %(default)s)")
    args = parser.parse_args(argv)
    try:
        # Preserve exit 40 independently of credential readiness: prohibited
        # scan days refuse before this process has any reason to load a key.
        require_scan_day(args.stamp)
        _load_process_api_key()
        result = scan_missing_archive_bars(args.out_dir, stamp=args.stamp, benchmark=args.benchmark)
    except ScanDayRefused as exc:
        # This refusal is an expected, zero-quota safety outcome.  It is a
        # stable scheduler contract rather than a caller-side string match.
        print(json.dumps({"status": "refused_non_scan_day", "exit_code": EXIT_REFUSED_NON_SCAN_DAY,
                          "error_type": type(exc).__name__, "error": str(exc)},
                         ensure_ascii=False, sort_keys=True))
        return EXIT_REFUSED_NON_SCAN_DAY
    except Exception as exc:  # scanner errors must remain scheduler-visible
        print(json.dumps({"status": "failed", "exit_code": EXIT_FAILED,
                          "error_type": type(exc).__name__, "error": str(exc),
                          "coverage": _failure_coverage(args.out_dir, args.stamp)},
                         ensure_ascii=False, sort_keys=True))
        return EXIT_FAILED

    if result.get("alert"):
        exit_code, status = EXIT_HARD_ALERT, "hard_alert"
    elif result.get("requested_symbols"):
        exit_code, status = EXIT_CAPTURED, "captured"
    else:
        exit_code, status = EXIT_CLEAN, "clean"
    print(json.dumps(_summary(result, exit_code=exit_code, status=status),
                     ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
