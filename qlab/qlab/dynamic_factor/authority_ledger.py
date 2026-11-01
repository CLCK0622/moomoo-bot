"""EVO-891 JSONL reader/writer with a fixed externally published ancestor.

No contribution or historical byte is migrated/reinterpreted. Published counts
are recorded N, never complete N. The formal witness advances monotonically. Formal evaluation cannot select another project witness or
bootstrap a ledger through request fields. Unit SQLite bootstrap is separate.
"""

import fcntl
import json
import os
from .arm_n import MISSING

from pathlib import Path

from .contract import canonical, digest, sha256, result

FIXTURES = Path(__file__).parent / "fixtures" / "evo891"
PROJECT_ROOT = (
    Path(__file__).resolve().parents[3] / "research" / "dynamic_factor" / "authority"
)
PROJECT_LEDGER = PROJECT_ROOT / "EVO891-B-ledger-v2.jsonl"
PROJECT_WITNESS = PROJECT_ROOT / "project-tip.json"
PUBLISHED = {
    "ledger_id": "37a3871d39df8a641f64d39b335338c0f1d66bb1e20ed9b6c4cf456a508f02cc",
    "sequence": 20,
    "tip": "9e3220aa6aa6dcc7f2a03c4f1f917b2da40af78c90173156f6ca4e9efd8e9c0d",
    "n_high_water": 75,
}


def latest_external_witness():
    """Current release only; no import-time historical fixture or fallback."""
    from .authority_release import read_approved_release

    return read_approved_release()


SOURCE_SHA = "a8f50e02644ec4a86460f8038b89edcbc1811352e5bf320dca592cef6abcb87e"
TOOL_SHA = "36ab3dd0cfc7d9c68a0e9ab2f0cc5774f0f7ccb260a2db61b36abbe040181969"
FIELDS = (
    "ledger_id",
    "genesis_sha256",
    "sequence",
    "tip",
    "snapshot_sha256",
    "N",
    "n_high_water",
    "self_report_n",
)
ATTEMPT_FIELDS = (
    "attempt_id",
    "run_id",
    "n_trials_total",
    "n_evaluated",
    "n_contribution",
    "scope_labels",
    "evidence",
)


def validate_new_attempt(row, previous):
    """Only recorded delivery/continuation identity can exempt a new entry.

    Historical P02 stays untouched. Equal parameter cells alone never suffice.
    Evidence must bind the linked run and an already recorded artifact/log SHA.
    """
    from .authority_record_types import validate_attempt_fields

    validate_attempt_fields(row, mode="new_write", trusted_coverage=None)
    if row.get("n_contribution") != 0:
        if type(row.get("n_contribution")) is not int or row["n_contribution"] < 1:
            raise ValueError("ledger.contribution_or_attempt_id_invalid")
        if row["n_contribution"] < max(
            row.get("n_trials_total", 1), row.get("n_evaluated", 0), 1
        ):
            raise ValueError("ledger.recomputation_or_retry_must_count")
        return
    linked = next(
        (
            r
            for r in previous
            if r.get("event") == "attempt"
            and r.get("attempt_id") == row.get("same_cells_as")
        ),
        None,
    )
    proof = row.get("continuation_evidence") or {}
    if not isinstance(proof, dict):
        raise ValueError("ledger.same_parameter_cells_not_exempt")
    if (
        linked is None
        or proof.get("attempt_id") != linked["attempt_id"]
        or proof.get("run_id") != linked["run_id"]
        or row.get("run_id") != linked["run_id"]
        or proof.get("kind") not in ("same_attempt_delivery", "continuous_trial")
        or proof.get("artifact_or_log_sha256")
        not in {e["sha256"] for e in linked["evidence"]}
        or row.get("n_evaluated") != 0
        or row.get("n_trials_total") != 0
    ):
        raise ValueError("ledger.same_parameter_cells_not_exempt")


def records(raw):
    out = []
    for line in raw.split(b"\n"):
        if not line:
            continue
        row = json.loads(line)
        if canonical(row) != line:
            raise ValueError("ledger.line_not_canonical")
        out.append(row)
    return out


def state(rows, *, trusted_coverage=None):
    if (
        not rows
        or rows[0].get("event") != "genesis"
        or rows[0].get("seq") != 0
        or rows[0].get("previous_hash") is not None
    ):
        raise ValueError("ledger.genesis_missing_or_invalid")
    genesis = rows[0]
    n = high = reported = 0
    ids, checkpoint = set(), None
    for k, row in enumerate(rows[1:], 1):
        if row.get("seq") != k:
            raise ValueError("ledger.sequence_invalid")
        if row.get("previous_hash") != digest(rows[k - 1]):
            raise ValueError("ledger_hash_chain_invalid")
        kind = row.get("event")
        if kind == "attempt":
            if any(f not in row for f in ATTEMPT_FIELDS):
                raise ValueError("ledger.attempt_field_missing")
            c = row["n_contribution"]
            if type(c) is not int or c < 0 or row["attempt_id"] in ids:
                raise ValueError("ledger.contribution_or_attempt_id_invalid")
            ids.add(row["attempt_id"])
            if k > PUBLISHED["sequence"]:
                if row.get("n_evaluated") is None and trusted_coverage is not None:
                    from .authority_record_types import validate_attempt_fields

                    validate_attempt_fields(
                        row, mode="historical_replay", trusted_coverage=trusted_coverage
                    )
                else:
                    validate_new_attempt(row, rows[:k])
            # Preserve the published historical exception; new writes have a
            # stricter continuation rule checked separately, never rewrite P02.
            if c == 0 and not row.get("same_cells_as"):
                raise ValueError("ledger.zero_contribution_requires_existing_link")
            if row.get("same_cells_as") and row["same_cells_as"] not in ids:
                raise ValueError("ledger.same_cells_as_unknown")
            if not row["evidence"] or not all(
                len(e.get("sha256", "")) == 64 for e in row["evidence"]
            ):
                raise ValueError("ledger.evidence_sha_missing")
            n += c
            if row.get("n_after") != n:
                raise ValueError("ledger.n_after_mismatch")
        elif kind == "self_report_n":
            if type(row.get("value")) is not int or row["value"] < 0:
                raise ValueError("ledger.self_report_invalid")
            reported = max(reported, row["value"])
        elif kind in ("open_gap", "gap_update"):
            if "gap_id" not in row or "status" not in row:
                raise ValueError("ledger.gap_record_invalid")
        elif kind == "checkpoint":
            want = max(high, n, reported)
            if row.get("N") != n or row.get("n_high_water") != want:
                raise ValueError("ledger.checkpoint_mismatch")
            high, checkpoint = want, k
        else:
            raise ValueError("ledger.unknown_event")
    return dict(
        ledger_id=genesis["ledger_id"],
        genesis_sha256=digest(genesis),
        sequence=len(rows) - 1,
        tip=digest(rows[-1]),
        snapshot_sha256=digest(rows),
        N=n,
        n_high_water=max(high, n, reported),
        self_report_n=reported,
        last_checkpoint_seq=checkpoint,
    )


def verify_ancestor(rows, anchor, *, trusted_coverage=None):
    if not isinstance(anchor, dict) or any(k not in anchor for k in PUBLISHED):
        raise ValueError("ledger.external_anchor_required")
    seq = anchor["sequence"]
    if type(seq) is not int or seq < PUBLISHED["sequence"] or seq >= len(rows):
        raise ValueError("ledger.external_anchor_mismatch")
    prefix = state(rows[: seq + 1], trusted_coverage=trusted_coverage)
    if any(prefix[k] != anchor[k] for k in PUBLISHED):
        raise ValueError("ledger.external_anchor_mismatch")


def verify_bytes(raw, witness, external_anchor=None, *, trusted_coverage=None):
    rows = records(raw)
    cur = state(rows, trusted_coverage=trusted_coverage)
    if witness.get("migrated_to") or witness.get("migration_pending"):
        raise ValueError("ledger.migration_pending_or_source_retired")
    if any(witness.get(k) != cur[k] for k in FIELDS) or witness.get(
        "ledger_file_sha256"
    ) != sha256(raw):
        raise ValueError("ledger.tail_or_high_water_mismatch")
    if cur["last_checkpoint_seq"] != cur["sequence"]:
        raise ValueError("ledger.tail_not_checkpoint")
    if (
        len(rows) < 21
        or sha256(b"".join(canonical(r) + b"\n" for r in rows[:21])) != SOURCE_SHA
    ):
        raise ValueError("ledger.published_prefix_mismatch")
    verify_ancestor(rows, PUBLISHED, trusted_coverage=trusted_coverage)
    verify_ancestor(
        rows,
        PUBLISHED if external_anchor is None else external_anchor,
        trusted_coverage=trusted_coverage,
    )
    return cur, rows


class AuthorityLedger:
    def __init__(self, path, witness, *, external_anchor=None, writable=False):
        self.path, self.witness = Path(path), Path(witness)
        self.external_anchor = dict(
            PUBLISHED if external_anchor is None else external_anchor
        )
        if self.path.resolve() == PROJECT_LEDGER.resolve():
            latest = latest_external_witness()
            if self.witness.resolve() != PROJECT_WITNESS.resolve() or (
                external_anchor is not None and external_anchor != latest
            ):
                raise ValueError("ledger.formal_current_anchor_required")
            self.external_anchor = latest
        self.writable = writable
        if (
            self.path.resolve() == self.witness.resolve()
            or self.path.is_symlink()
            or self.witness.is_symlink()
        ):
            raise ValueError("ledger.independent_regular_witness_required")
        self.verify()

    @classmethod
    def open_project(cls, path, *, anchor_path=None, bootstrap_receipt=None):
        if bootstrap_receipt is not None or anchor_path is not None:
            raise ValueError("ledger.formal_bootstrap_or_anchor_override_forbidden")
        if Path(path).resolve() != PROJECT_LEDGER.resolve():
            raise ValueError("ledger.project_path_migration_receipt_required")
        # First installation is controlled outside evaluation requests. No
        # missing state is ever silently recreated from a request/receipt.
        if not PROJECT_LEDGER.is_file() or not PROJECT_WITNESS.is_file():
            raise ValueError("ledger.trusted_project_installation_required")
        return cls(PROJECT_LEDGER, PROJECT_WITNESS)

    def _verify(self):
        if self.path.resolve() == PROJECT_LEDGER.resolve():
            self.external_anchor = latest_external_witness()
        raw = self.path.read_bytes()
        witness = json.loads(self.witness.read_bytes())
        cur, rows = verify_bytes(raw, witness, self.external_anchor)
        return cur, rows, raw

    def verify(self):
        return self._verify()[0]

    def append(self, record):
        if not self.writable or self.path.resolve().is_relative_to(FIXTURES.resolve()):
            raise ValueError("ledger.authoritative_writer_required")
        lockfile = self.witness.with_name(self.witness.name + ".lock")
        with lockfile.open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            before, rows, raw = self._verify()
            r = dict(record)
            if r.get("event") not in ("attempt", "self_report_n", "gap_update"):
                raise ValueError("ledger.append_event_not_allowed")
            for k in ("seq", "previous_hash", "n_after"):
                r.pop(k, None)
            if r["event"] == "attempt":
                existing = next(
                    (
                        e
                        for e in rows
                        if e.get("event") == "attempt"
                        and e["attempt_id"] == r.get("attempt_id")
                    ),
                    None,
                )
                if existing is not None:
                    body = {
                        k: v
                        for k, v in existing.items()
                        if k not in ("seq", "previous_hash", "n_after")
                    }
                    if body != r:
                        raise ValueError("ledger.attempt_identity_payload_conflict")
                    return before  # Transport retry: identical bytes, no new trial.
                validate_new_attempt(r, rows)
            r.update(seq=len(rows), previous_hash=digest(rows[-1]))
            if r["event"] == "attempt":
                r["n_after"] = before["N"] + r.get("n_contribution", -1)
            intermediate = rows + [r]
            mid = state(intermediate)
            cp = dict(
                event="checkpoint",
                seq=len(intermediate),
                previous_hash=digest(r),
                N=mid["N"],
                n_high_water=max(
                    before["n_high_water"], mid["N"], mid["self_report_n"]
                ),
                note="auto checkpoint after append",
            )
            after = state(intermediate + [cp])
            if (
                after["N"] < before["N"]
                or after["n_high_water"] < before["n_high_water"]
            ):
                raise ValueError("ledger.high_water_decrease")
            with self.path.open("ab") as f:
                f.write(canonical(r) + b"\n" + canonical(cp) + b"\n")
                f.flush()
                os.fsync(f.fileno())
            from .ledger_anchor import write

            write(
                self.witness,
                {k: after[k] for k in FIELDS}
                | {
                    "ledger_file_sha256": sha256(self.path.read_bytes()),
                    "ledger_file": self.path.name,
                },
            )
            return self.verify()

    def snapshot(self):
        cur, rows, _ = self._verify()
        canonical_project = self.path.resolve() == PROJECT_LEDGER.resolve()
        if canonical_project:
            latest = latest_external_witness()
        else:
            from .historical_authority import historical_v4_witness

            latest = historical_v4_witness()
        try:
            verify_ancestor(rows, latest)
            current = canonical_project
        except ValueError:
            current = False
        return {
            "authority_ledger": True,
            "genesis": rows[0],
            "events": rows[1:],
            "recorded_N": cur["N"],
            "n_high_water": cur["n_high_water"],
            "authority_tip": cur["tip"],
            "authority_sequence": cur["sequence"],
            "local_attempts_n": None,
            "local_counted_n": None,
            "cumulative_n": None,
            "cumulative_n_lower_bound": cur["n_high_water"],
            "n_complete": False,
            "complete_N": None,
            "n_ledger_hash": cur["snapshot_sha256"],
            "certifiable": False,
            "reasons": ["ledger_history_incomplete"]
            + ([] if current else ["ledger.archival_snapshot_below_current_anchor"]),
            "external_anchor": dict(PUBLISHED),
            "current_published_anchor": latest if canonical_project else None,
            "historical_published_anchor": None if canonical_project else latest,
            "is_current_authority": current,
        }

    def safe_snapshot(self):
        try:
            return self.snapshot()
        except (ValueError, KeyError, TypeError, OSError):
            return {
                "genesis": None,
                "events": None,
                "cumulative_n": None,
                "cumulative_n_lower_bound": None,
                "n_ledger_hash": None,
                "certifiable": False,
                "reasons": ["ledger_unreadable_or_corrupt"],
            }

    def arm_readout(self, arm_tag=MISSING):
        from .reception_entrypoints_v3 import bound_readout

        return bound_readout(self, arm_tag, "authority.arm_readout")

    def diagnostic_arm_readout(self, arm_tag=None):
        """Explicit formal arm read; absent/invalid identity never reads the chain."""
        from .arm_n import readout

        return readout(self, arm_tag)

    def readout(self):
        cur = self.verify()
        return result(
            "authority_ledger_readout",
            cur,
            metrics={
                **cur,
                "recorded_N": cur["N"],
                "n_complete": False,
                "cumulative_n": None,
                "complete_N": None,
                "dsr": None,
                "current_published_anchor": self.snapshot()["current_published_anchor"],
                "is_current_authority": self.snapshot()["is_current_authority"],
            },
            missing=["complete_history_acceptance"],
            assumptions=[
                "Published recorded N is not complete N; G1-G5 and P02 require separate evidence acceptance."
            ],
        )

    def _unique_writer_required(self, *args, **kwargs):
        raise ValueError("ledger.authoritative_writer_required")

    begin = finish = record = recorded = declare_family = observe_self_report_n = (
        _unique_writer_required
    )


def replay_approved_archive(raw, *, trusted_release, witness):
    """Replay covered original bytes without interpreting unknown evaluation counts."""
    from .authority_record_types import covered_archive

    identity = covered_archive(raw, trusted_release)
    if (
        not raw.endswith(b"\n")
        or b"\r" in raw
        or any(not line for line in raw[:-1].split(b"\n"))
    ):
        raise ValueError("ledger.line_not_canonical")
    current, rows = verify_bytes(raw, witness, trusted_coverage=trusted_release)
    unknowns = [
        dict(
            seq=row["seq"],
            attempt_id=row["attempt_id"],
            raw_line_sha256=sha256(canonical(row)),
            n_evaluated=None,
            n_evaluated_null_reason=row["n_evaluated_null_reason"],
            classification="CONTROLLED_HISTORICAL_UNKNOWN",
        )
        for row in rows
        if row.get("event") == "attempt" and row.get("n_evaluated") is None
    ]
    return dict(
        schema="EVO884.T1-reception-result/v2.1",
        accepted=True,
        stage="archive",
        reasons=["ledger.controlled_historical_unknown"] if unknowns else [],
        source_archive_sha256=identity[0],
        approved_coverage_sha256=digest([identity[0], identity[1]]),
        source_rows_preserved=True,
        book_N=current["N"],
        high_water=current["n_high_water"],
        book_N_certified=False,
        own_arm_formal_bound_from_book=False,
        counted_as_zero=False,
        counted_as_not_evaluated=False,
        new_writes_relaxed=False,
        raw_unknown_rows=len(unknowns),
        unknown_rows=unknowns,
        relevant_unresolved_unknowns=len(unknowns),
        accepted_reconciliation_sha256=None,
        full_authority_projection_complete=False,
        complete_N=None,
        n_complete=False,
        gate_N=None,
        formal_lower_bound=None,
        formal_upper_bound=None,
        DSR=None,
        runtime_consumable=False,
        certifiable=False,
    )
