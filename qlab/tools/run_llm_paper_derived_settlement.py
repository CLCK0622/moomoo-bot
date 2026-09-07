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
from qlab.llm_paper.derived_settlement import (write_lower_bound_settlement,  # noqa: E402
                                                write_settlement_invocation)


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=_REPO_ROOT, check=False,
                          text=True, capture_output=True)


def _last_commit(paths: Iterable[Path]) -> str | None:
    relative = [str((path if path.is_absolute() else _REPO_ROOT / path)
                    .resolve().relative_to(_REPO_ROOT)) for path in paths]
    result = _git("log", "-1", "--format=%H", "--", *relative)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def _records_unchanged(paths: Iterable[Path], evidence_commit: str | None) -> bool:
    """Prove records match a named commit and have no staged/unstaged edits."""
    relative = [str((path if path.is_absolute() else _REPO_ROOT / path)
                    .resolve().relative_to(_REPO_ROOT)) for path in paths]
    if not evidence_commit:
        return False
    commit = _git("cat-file", "-e", f"{evidence_commit}^{{commit}}")
    tracked = _git("ls-files", "--error-unmatch", *relative)
    unstaged = _git("diff", "--quiet", "--", *relative)
    staged = _git("diff", "--cached", "--quiet", "--", *relative)
    matches_evidence = _git("diff", "--quiet", evidence_commit, "--", *relative)
    return all(result.returncode == 0 for result in (
        commit, tracked, unstaged, staged, matches_evidence))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default="qlab/reports/llm_paper",
                        help="LLM-paper report directory (default: %(default)s)")
    parser.add_argument("--equivalence-round",
                        help="also audit this persisted YYYYMMDD parallel-control round")
    parser.add_argument("--evidence-commit",
                        help="commit whose exact immutable records the equivalence audit proves")
    parser.add_argument("--expected-input-manifest-sha256",
                        help="fail unless the stable calculation inputs match this digest")
    parser.add_argument("--expected-implementation-version",
                        help="fail unless the settlement algorithm has this version")
    parser.add_argument("--expected-implementation-source-sha256",
                        help="fail unless the settlement implementation source matches this digest")
    parser.add_argument("--expected-settlement-content-sha256",
                        help="fail unless the complete v2 calculation artifact has this digest")
    args = parser.parse_args(argv)

    out = Path(args.out_dir)
    records: list[Path] = []
    evidence_commit = args.evidence_commit
    if args.equivalence_round:
        records = [out / f"round_{args.equivalence_round}.json",
                   out / "control_multi_book" / f"round_{args.equivalence_round}.json",
                   out / f"CONTROL_{args.equivalence_round}.json"]
        evidence_commit = evidence_commit or _last_commit(records)
    elif evidence_commit:
        parser.error("--evidence-commit requires --equivalence-round")

    head = _git("rev-parse", "HEAD")
    invocation_commit = head.stdout.strip() if head.returncode == 0 else None
    settlement = write_lower_bound_settlement(args.out_dir)
    expected = {
        "input manifest": (args.expected_input_manifest_sha256,
                           settlement["input_manifest_sha256"]),
        "implementation version": (args.expected_implementation_version,
                                   settlement["implementation_version"]),
        "implementation source": (args.expected_implementation_source_sha256,
                                  settlement["implementation_source_sha256"]),
        "settlement content": (args.expected_settlement_content_sha256,
                               settlement["content_sha256"]),
    }
    for label, (wanted, actual) in expected.items():
        if wanted is not None and wanted != actual:
            parser.error(f"{label} mismatch: expected {wanted}, actual {actual}")
    command = {
        "out_dir": args.out_dir,
        "equivalence_round": args.equivalence_round,
        "evidence_commit": evidence_commit,
        "expected_input_manifest_sha256": args.expected_input_manifest_sha256,
        "expected_implementation_version": args.expected_implementation_version,
        "expected_implementation_source_sha256": args.expected_implementation_source_sha256,
        "expected_settlement_content_sha256": args.expected_settlement_content_sha256,
    }
    invocation = write_settlement_invocation(
        args.out_dir, settlement=settlement, branch_head_commit=invocation_commit,
        command=command)
    summary = {
        "settlement_file": settlement["settlement_file"],
        "settlement_content_sha256": settlement["content_sha256"],
        "settlement_input_manifest_sha256": settlement["input_manifest_sha256"],
        "settlement_implementation_version": settlement["implementation_version"],
        "settlement_implementation_source_sha256": settlement[
            "implementation_source_sha256"],
        "settlement_summary": settlement["payload"].get("summary"),
        "invocation_file": invocation["invocation_file"],
        "invocation_content_sha256": invocation["content_sha256"],
        "invocation_branch_head_commit": invocation_commit,
    }

    if args.equivalence_round:
        freeze_sha = load_anchor().get("freeze_sha")
        ancestry = (_git("merge-base", "--is-ancestor", str(freeze_sha), str(evidence_commit))
                    if freeze_sha and evidence_commit else None)
        equivalence = write_derived_equivalence(
            args.out_dir, stamp=args.equivalence_round,
            evidence_commit=evidence_commit,
            freeze_is_ancestor=bool(ancestry and ancestry.returncode == 0),
            records_unchanged=_records_unchanged(records, evidence_commit))
        summary.update({
            "equivalence_file": equivalence["equivalence_file"],
            "equivalence_content_sha256": equivalence["content_sha256"],
            "equivalence_summary": equivalence["payload"]["summary"],
        })
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
