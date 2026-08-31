"""Run the non-round-day LLM-paper archive scanner for a scheduler.

Typical autopilot command (from the repository root)::

    python3 qlab/tools/run_llm_paper_archive_scan.py \
        --out-dir qlab/reports/llm_paper

Exit codes are deliberately machine-readable: 0 = clean (no quote call),
10 = compact bars captured, 20 = hard window alert (whether or not capture
succeeded), 30 = a real scan failure, and 40 = an expected safety refusal on a
non-scan day.  The scanner itself rejects Monday and weekends; this wrapper
never relaxes that safety boundary.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

_REPO_ROOT = Path(__file__).resolve().parents[2]
_QLAB_ROOT = _REPO_ROOT / "qlab"
for _path in (str(_QLAB_ROOT), str(_REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from qlab.llm_paper.archive_scanner import ScanDayRefused, scan_missing_archive_bars  # noqa: E402

EXIT_CLEAN = 0
EXIT_CAPTURED = 10
EXIT_HARD_ALERT = 20
EXIT_FAILED = 30
EXIT_REFUSED_NON_SCAN_DAY = 40


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
        },
        "scan_report": (result.get("scan_report") or {}).get("file"),
        "alert_file": (result.get("alert") or {}).get("file"),
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
                          "error_type": type(exc).__name__, "error": str(exc)},
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
