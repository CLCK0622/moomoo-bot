"""Materialize archived-bar settlement and optional post-round equivalence.

This command is offline: it does not fetch quotes, run a decision round, touch
the trial ledger, or rewrite prior artifacts.  Outputs are content-addressed
and append-only.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Iterable

_REPO_ROOT = Path(__file__).resolve().parents[2]
_QLAB_ROOT = _REPO_ROOT / "qlab"
for _path in (str(_QLAB_ROOT), str(_REPO_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from qlab.llm_paper.decision_chain import load_anchor  # noqa: E402
from qlab.llm_paper.derived_equivalence import write_derived_equivalence  # noqa: E402
from qlab.llm_paper.derived_settlement import write_lower_bound_settlement  # noqa: E402


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=_REPO_ROOT, check=False,
                          text=True, capture_output=True)


def _last_commit(paths: Iterable[Path]) -> str | None:
    relative = [str((path if path.is_absolute() else _REPO_ROOT / path)
                    .resolve().relative_to(_REPO_ROOT)) for path in paths]
    result = _git("log", "-1", "--format=%H", "--", *relative)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def _records_unchanged(paths: Iterable[Path]) -> bool:
    relative = [str((path if path.is_absolute() else _REPO_ROOT / path)
                    .resolve().relative_to(_REPO_ROOT)) for path in paths]
    tracked = _git("ls-files", "--error-unmatch", *relative)
    unchanged = _git("diff", "--quiet", "--", *relative)
    return tracked.returncode == 0 and unchanged.returncode == 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="qlab/reports/llm_paper",
                        help="LLM-paper report directory (default: %(default)s)")
    parser.add_argument("--equivalence-round",
                        help="also audit this persisted YYYYMMDD parallel-control round")
    args = parser.parse_args(argv)

    head = _git("rev-parse", "HEAD")
    source_commit = head.stdout.strip() if head.returncode == 0 else None
    settlement = write_lower_bound_settlement(args.out_dir, source_commit=source_commit)
    summary = {
        "settlement_file": settlement["settlement_file"],
        "settlement_content_sha256": settlement["content_sha256"],
        "settlement_summary": settlement["payload"].get("summary"),
        "source_commit": source_commit,
    }

    if args.equivalence_round:
        out = Path(args.out_dir)
        records = [out / f"round_{args.equivalence_round}.json",
                   out / "control_multi_book" / f"round_{args.equivalence_round}.json",
                   out / f"CONTROL_{args.equivalence_round}.json"]
        evidence_commit = _last_commit(records)
        freeze_sha = load_anchor().get("freeze_sha")
        ancestry = (_git("merge-base", "--is-ancestor", str(freeze_sha), str(evidence_commit))
                    if freeze_sha and evidence_commit else None)
        equivalence = write_derived_equivalence(
            args.out_dir, stamp=args.equivalence_round,
            evidence_commit=evidence_commit,
            freeze_is_ancestor=bool(ancestry and ancestry.returncode == 0),
            records_unchanged=_records_unchanged(records))
        summary.update({
            "equivalence_file": equivalence["equivalence_file"],
            "equivalence_content_sha256": equivalence["content_sha256"],
            "equivalence_summary": equivalence["payload"]["summary"],
        })
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
