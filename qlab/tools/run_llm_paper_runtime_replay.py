"""Replay the immutable 20260831 books through both real executor paths.

This command is offline.  It accepts no loose bars input, performs no quote
fetch or ledger registration, and writes one content-addressed append-only
runtime-equivalence artifact below the report directory.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_QLAB_ROOT = _REPO_ROOT / "qlab"
for _path in (str(_QLAB_ROOT), str(_REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from qlab.llm_paper.bar_archive import ArchiveIntegrityError  # noqa: E402
from qlab.llm_paper.runtime_replay import (DEFAULT_SETTLEMENT, RuntimeReplayError,  # noqa: E402
                                           replay_runtime_equivalence)


def _resolve_out_dir(value: str) -> Path:
    supplied = Path(value).expanduser()
    candidates = ([supplied] if supplied.is_absolute() else
                  [Path.cwd() / supplied, _REPO_ROOT / supplied, _QLAB_ROOT / supplied])
    existing = []
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_dir() and resolved not in existing:
            existing.append(resolved)
    if not existing:
        raise FileNotFoundError(f"report directory does not exist: {value}")
    if len(existing) > 1:
        raise ValueError(
            f"ambiguous report directory {value!r}: " + ", ".join(str(path) for path in existing))
    return existing[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="qlab/reports/llm_paper",
                        help="LLM-paper report directory (default: %(default)s)")
    parser.add_argument("--round", default="20260831",
                        help="immutable round to replay (only 20260831 is authorized)")
    parser.add_argument("--settlement-file", default=DEFAULT_SETTLEMENT,
                        help="existing derived settlement used only for reconciliation")
    parser.add_argument("--expected-content-sha256",
                        help="fail unless the complete replay artifact has this digest")
    args = parser.parse_args(argv)
    try:
        out = _resolve_out_dir(args.out_dir)
        result = replay_runtime_equivalence(
            str(out), stamp=args.round, settlement_file=args.settlement_file,
            expected_content_sha256=args.expected_content_sha256)
    except (ArchiveIntegrityError, FileNotFoundError, RuntimeReplayError, ValueError) as exc:
        parser.error(str(exc))
    summary = {
        "artifact_file": result["artifact_file"],
        "content_sha256": result["content_sha256"],
        "file_sha256": result["file_sha256"],
        "input_manifest_sha256": result["input_manifest_sha256"],
        "shared_bar_snapshot_content_sha256": result[
            "shared_bar_snapshot_content_sha256"],
        "implementation_source_sha256": result["implementation_source_sha256"],
        "runtime_source_bundle_sha256": result["runtime_source_bundle_sha256"],
        "executor_behavior_equivalence": result["payload"]["conclusions"][
            "executor_behavior_equivalence"],
        "may_take_over": result["payload"]["conclusions"]["may_take_over"],
        "switch_authorized": result["payload"]["conclusions"]["switch_authorized"],
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
