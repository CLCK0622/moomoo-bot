#!/usr/bin/env python3
"""Fixed CLI for natural M/W/F v2 schedule deliveries (offline, SIMULATE-only)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_QLAB_ROOT = Path(__file__).resolve().parents[1]
if str(_QLAB_ROOT) not in sys.path:
    sys.path.insert(0, str(_QLAB_ROOT))
_REPO_ROOT = _QLAB_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from qlab.llm_paper.scheduled_runner import (  # noqa: E402
    EXIT_INPUT,
    PipelineStageError,
    run_scheduled_delivery,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delivery", required=True, help="Frozen schedule-delivery JSON")
    parser.add_argument("--state-dir", required=True, help="Immutable output state directory")
    args = parser.parse_args(argv)
    try:
        result = run_scheduled_delivery(args.delivery, state_dir=args.state_dir)
    except PipelineStageError as exc:
        print(json.dumps({"status": "failed_closed", "stage": exc.stage,
                          "exit_code": exc.exit_code, "reason": exc.reason},
                         ensure_ascii=False, sort_keys=True))
        return exc.exit_code
    except Exception as exc:
        print(json.dumps({"status": "failed_closed", "stage": "input",
                          "exit_code": EXIT_INPUT, "reason": str(exc)},
                         ensure_ascii=False, sort_keys=True))
        return EXIT_INPUT
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
