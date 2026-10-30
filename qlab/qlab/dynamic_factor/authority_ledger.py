"""EVO-891 JSONL reader/writer with a fixed externally published ancestor.

No contribution or historical byte is migrated/reinterpreted. Published counts
are recorded N, never complete N. The formal witness advances monotonically. Formal evaluation cannot select another project witness or
bootstrap a ledger through request fields. Unit SQLite bootstrap is separate.
"""

import fcntl
import json
import os
from pathlib import Path

from .contract import canonical, digest, sha256, result, is_sha

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
CURRENT_FIXTURES = FIXTURES.parent / "evo893"
CURRENT_PUBLISHED = {
    "ledger_id": PUBLISHED["ledger_id"],
    "sequence": 182,
    "tip": "c9082ec0f045796754e12506cc468a09ac88a36873aee8cacbe5cf5d0769f851",
    "n_high_water": 280,
}
CURRENT_SOURCE_SHA = "8169337c4c8095cc93c1771d67ff6448de9628ca44c97ca9f8fd5711e7a99cf6"
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
    if (
        any(k not in row for k in ATTEMPT_FIELDS)
        or not isinstance(row["attempt_id"], str)
        or not row["attempt_id"]
        or not isinstance(row["run_id"], str)
        or not row["run_id"]
        or any(
            type(row[k]) is not int or row[k] < 0
            for k in ("n_trials_total", "n_evaluated")
        )
        or not isinstance(row["evidence"], list)
        or not row["evidence"]
        or any(
            not isinstance(e, dict) or not is_sha(e.get("sha256"))
            for e in row["evidence"]
        )
    ):
        raise ValueError("ledger.attempt_field_missing_or_invalid")
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


def state(rows):
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


def verify_ancestor(rows, anchor):
    if not isinstance(anchor, dict) or any(k not in anchor for k in PUBLISHED):
        raise ValueError("ledger.external_anchor_required")
    seq = anchor["sequence"]
    if type(seq) is not int or seq < PUBLISHED["sequence"] or seq >= len(rows):
        raise ValueError("ledger.external_anchor_mismatch")
    prefix = state(rows[: seq + 1])
    if any(prefix[k] != anchor[k] for k in PUBLISHED):
        raise ValueError("ledger.external_anchor_mismatch")


def verify_bytes(raw, witness, external_anchor=None):
    rows = records(raw)
    cur = state(rows)
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
    verify_ancestor(rows, PUBLISHED)
    verify_ancestor(rows, PUBLISHED if external_anchor is None else external_anchor)
    return cur, rows


class AuthorityLedger:
    def __init__(self, path, witness, *, external_anchor=None, writable=False):
        self.path, self.witness = Path(path), Path(witness)
        self.external_anchor = dict(
            PUBLISHED if external_anchor is None else external_anchor
        )
        if self.path.resolve() == PROJECT_LEDGER.resolve():
            if self.witness.resolve() != PROJECT_WITNESS.resolve() or (
                external_anchor is not None and external_anchor != CURRENT_PUBLISHED
            ):
                raise ValueError("ledger.formal_current_anchor_required")
            self.external_anchor = dict(CURRENT_PUBLISHED)
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
        return cls(PROJECT_LEDGER, PROJECT_WITNESS, external_anchor=CURRENT_PUBLISHED)

    def _verify(self):
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
        try:
            verify_ancestor(rows, CURRENT_PUBLISHED)
            current = True
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
            "current_published_anchor": dict(CURRENT_PUBLISHED),
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
                "current_published_anchor": dict(CURRENT_PUBLISHED),
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
