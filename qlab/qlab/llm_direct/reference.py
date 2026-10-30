"""Frozen MOM20/REV20 arithmetic and daily, non-backfillable source books."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from qlab.shadow15k.fees import decimal_arithmetic
from qlab.shadow15k.ledger import timestamp

from .contract import FIXTURES, PROFILE_SHA, bindings, digest, sha
from .snapshot import verify_decision

ROLES = ["C0_LLM", "R1_MOM20", "R2_REV20"]


@decimal_arithmetic
def signal(role, decision):
    """Only causal market input and the caller's OWN state; no C0/R-other input."""
    verify_decision(decision)
    if role not in ROLES[1:]:
        raise ValueError("reference.role_invalid")
    tr = decision["derived_TR"]
    q = [Decimal(x) for x in tr["QQQ"][-21:]]

    def clip(v, limit):
        return min(limit, max(-limit, v))

    mu_q = clip(10 * sum(q[i] / q[i - 1] - 1 for i in range(1, 21)) / 20, Decimal(1))
    forecasts, alphas = {"QQQ": str(mu_q)}, {}
    for s, eligibility in decision["eligibility"].items():
        if eligibility != "VERIFIED_ELIGIBLE":
            continue
        alpha = clip(
            (Decimal(tr[s][-1]) / Decimal(tr[s][-21]) - 1 - (q[-1] / q[0] - 1)) / 2,
            Decimal("0.10"),
        )
        signed = alpha if role == "R1_MOM20" else -alpha
        alphas[s] = signed
        forecasts[s] = str(clip(mu_q + signed, Decimal(1)))
    return dict(
        role=role,
        ranked_symbols=sorted(alphas, key=lambda s: (-alphas[s], s)),
        forecasts_h10_fraction=forecasts,
        input_sha256=decision["input_sha256"],
        profile_sha256=PROFILE_SHA,
    )


class ReferenceBook:
    def __init__(self, archive, role):
        if role not in ROLES[1:]:
            raise ValueError("reference.role_invalid")
        self.archive, self.role = archive, role

    def freeze(self, *, at, sessions, producer_source_sha256):
        bindings()
        if (
            not sessions
            or sessions != sorted(set(sessions))
            or timestamp(at).date().isoformat() >= sessions[0]
        ):
            raise ValueError("reference.freeze_must_precede_D0")
        if producer_source_sha256 != sha(Path(__file__).read_bytes()):
            raise ValueError("reference.source_sha_mismatch")
        profile = (FIXTURES / "EVO896-common-profile-v0.1.2.json").read_bytes()
        import json

        algorithms = {
            r: json.loads(profile)["roles"][r]["algorithm"] for r in ROLES[1:]
        }
        value = dict(
            kind="reference_freeze",
            role=self.role,
            members=ROLES,
            algorithms=algorithms,
            profile_sha256=PROFILE_SHA,
            producer_source_sha256=producer_source_sha256,
            at=at,
            sessions=sessions,
        )
        return self.archive.append("reference:freeze", value)

    def seal_day(
        self, *, session, at, source_bytes, ledger_bytes, return_bytes, source_run_id
    ):
        events = self.archive.events()
        frozen = next(
            (e["body"] for e in events if e["id"] == "reference:freeze"), None
        )
        if frozen is None or frozen["role"] != self.role:
            raise ValueError("reference.registry_missing_or_wrong_role")
        if timestamp(at).date().isoformat() != session or not source_run_id:
            raise ValueError("reference.backfill_or_source_identity_invalid")
        hashes = [
            self.archive.put(b) for b in (source_bytes, ledger_bytes, return_bytes)
        ]
        body = dict(
            kind="reference_day",
            role=self.role,
            session=session,
            at=at,
            source_run_id=source_run_id,
            profile_sha256=PROFILE_SHA,
            source_sha256=hashes[0],
            ledger_sha256=hashes[1],
            returns_sha256=hashes[2],
            blob_sha256s=hashes,
        )

        def validate(rows):
            days = [e["body"] for e in rows if e["body"]["kind"] == "reference_day"]
            if (
                len(days) >= len(frozen["sessions"])
                or frozen["sessions"][len(days)] != session
            ):
                raise ValueError("reference.missing_day_no_backfill_or_skip")
            if any(d["source_run_id"] == source_run_id for d in days):
                raise ValueError("reference.source_run_reused")

        event = self.archive.append("reference:" + session, body, validate=validate)
        return dict(
            manifest_sha256=digest(event), event=event, runtime_consumable=False
        )
