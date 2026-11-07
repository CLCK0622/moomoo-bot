"""Owned C04 cash witnesses; no market reader, analytical TR or account writer.

Host hashes refer to already received sources. They do not certify reception;
C09 still owns that boundary. A wire dictionary cannot substitute for CashProof.
"""

from copy import deepcopy
from datetime import date
import json

from .contract import canonical, digest, is_sha, sha256
from .execution_numbers import amount, decimal_text
from .input_disposition import cash_source_reason
from .input_scope import reject_b2_inputs
from .reference_validation import utc_instant


_ISSUER = object()
IDENTITY_FIELDS = (
    "asof",
    "inventory",
    "cash",
    "nav",
    "rights",
    "receivables",
    "initialization_count",
    "unknown_components",
)


class CashProof:
    """Capability issued only from a fully reconciled owned account close.

    This proves the classification of retained cash receivables at the B
    boundary. It grants no permission for noncash rights or original B names.
    """

    @staticmethod
    def _pairs(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("B.release_context_encoding_invalid")
            value[key] = item
        return value

    @staticmethod
    def _constant(value):
        raise ValueError("B.release_context_encoding_invalid")

    @staticmethod
    def binding_bytes(value):
        """An identity record is data, never a way to construct a capability."""
        fields = {
            "schema",
            "context_version",
            "release_id",
            "release_version",
            "adoption_sha256",
            "h_a",
            "h_r",
            "h_p",
            "h_c",
            "h_d",
            "receiver_id",
            "implementation_id",
            "implementation_sha256",
            "accepted_at",
            "acceptance_time_evidence_sha256",
            "policy_binding",
            "annotation_binding",
        }
        if (
            type(value) is not dict
            or set(value) != {"schema", "identity", "identity_sha256"}
            or value["schema"] != "EVO884.BReleaseContextBinding/v1"
            or type(value["identity"]) is not dict
            or set(value["identity"]) != fields
            or value["identity"].get("schema") != "EVO884.BReleaseContextIdentity/v1"
            or not is_sha(value["identity_sha256"])
            or sha256(canonical(value["identity"])) != value["identity_sha256"]
        ):
            raise ValueError("B.release_context_encoding_invalid")
        identity = value["identity"]
        if any(
            type(identity[k]) is not str or not identity[k]
            for k in fields - {"policy_binding", "annotation_binding"}
        ):
            raise ValueError("B.release_context_encoding_invalid")
        if any(
            not is_sha(identity[k])
            for k in (
                "adoption_sha256",
                "h_a",
                "h_r",
                "h_p",
                "h_c",
                "h_d",
                "implementation_sha256",
                "acceptance_time_evidence_sha256",
            )
        ):
            raise ValueError("B.release_context_encoding_invalid")
        policy = identity["policy_binding"]
        annotation = identity["annotation_binding"]
        if (
            type(policy) is not dict
            or set(policy)
            != {
                "conventions_version",
                "conventions_sha256",
                "conventions_status",
                "profile_sha256",
                "prereg_sha256",
                "prereg_version",
                "common_profile_sha256",
                "date_manifest_sha256",
                "common_calendar_sha256",
                "universe",
            }
            or type(annotation) is not dict
            or set(annotation)
            != {
                "issue_id",
                "comment_id",
                "revision",
                "content_sha256",
            }
            or type(annotation["revision"]) is not int
            or annotation["revision"] < 1
            or any(
                type(annotation[k]) is not str or not annotation[k]
                for k in ("issue_id", "comment_id", "content_sha256")
            )
            or not is_sha(annotation["content_sha256"])
            or type(policy["universe"]) is not list
            or len(policy["universe"]) != 64
            or any(type(v) is not str or not v for v in policy["universe"])
            or len(set(policy["universe"])) != 64
            or any(
                type(v) is not str or not v
                for k, v in policy.items()
                if k != "universe"
            )
            or any(not is_sha(v) for k, v in policy.items() if k.endswith("sha256"))
        ):
            raise ValueError("B.release_context_encoding_invalid")
        for key in ("issue_id", "comment_id"):
            identifier = annotation[key]
            if (
                len(identifier) != 36
                or [i for i, c in enumerate(identifier) if c == "-"] != [8, 13, 18, 23]
                or any(c not in "0123456789abcdef" for c in identifier.replace("-", ""))
            ):
                raise ValueError("B.release_context_encoding_invalid")
        try:
            utc_instant(identity["accepted_at"])
        except ValueError as exc:
            raise ValueError("B.release_context_encoding_invalid") from exc
        if not identity["accepted_at"].endswith(("Z", "+00:00")):
            raise ValueError("B.release_context_encoding_invalid")
        raw = canonical(value)
        # Do not inherit contract.clean's NaN/Infinity-to-null normalization.
        try:
            strict = json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("B.release_context_encoding_invalid") from exc
        if strict != raw:
            raise ValueError("B.release_context_encoding_invalid")
        return raw

    @staticmethod
    def binding_value(raw):
        try:
            if type(raw) is not bytes:
                raise ValueError("B.release_context_encoding_invalid")
            value = json.loads(
                raw,
                object_pairs_hook=CashProof._pairs,
                parse_constant=CashProof._constant,
            )
            if CashProof.binding_bytes(value) != raw:
                raise ValueError("B.release_context_encoding_invalid")
            return value
        except (TypeError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("B.release_context_encoding_invalid") from exc

    @staticmethod
    def release_requested(guard, release_context, expected_release_identity_bytes):
        return type(guard) is dict and (
            guard.get("schema") == "EVO883.BRuntimeGuard/v1"
            or any(
                guard.get(key) is not None
                for key in (
                    "B_catalog_release_sha256",
                    "B_release_acceptance_sha256",
                    "accepted_catalog_sha256",
                    "release_context_binding",
                )
            )
            or (
                type(guard.get("request")) is dict
                and "release_binding" in guard["request"]
            )
        )

    @staticmethod
    def release_guard(
        guard, policy, release_context=None, expected_release_identity_bytes=None
    ):
        """Forward to B01/B02; this bridge cannot receive or issue an A."""
        if not CashProof.release_requested(
            guard, release_context, expected_release_identity_bytes
        ):
            if (
                release_context is not None
                or expected_release_identity_bytes is not None
            ):
                raise ValueError("B.release_context_scope_mismatch")
            return None
        try:
            from .noncash_v3 import ReleaseContext, check_release_context, checked_guard
        except ImportError as exc:
            raise ValueError("B.release_context_implementation_unavailable") from exc
        if release_context is None:
            raise ValueError("B.release_context_required")
        if type(release_context) is not ReleaseContext:
            raise ValueError("B.release_context_type_mismatch")
        raw = check_release_context(
            release_context,
            policy=policy,
            request=guard["request"],
            expected_release_identity_bytes=expected_release_identity_bytes,
        )
        CashProof.binding_value(raw)
        if (
            expected_release_identity_bytes is not None
            and raw != expected_release_identity_bytes
        ):
            raise ValueError("B.release_context_persistent_identity_mismatch")
        checked_guard(
            guard,
            policy,
            release_context=release_context,
            expected_release_identity_bytes=raw,
        )
        return raw

    @staticmethod
    def bind_payload(payload, raw):
        if raw is not None:
            payload = dict(payload)
            payload["schema"] += "-BR1"
            payload["release_context_binding"] = CashProof.binding_value(raw)
        return payload

    def __init__(
        self,
        issuer,
        state,
        book_id,
        guard,
        ledger_sha256,
        *,
        release_context=None,
        expected_release_identity_bytes=None,
        policy=None,
    ):
        if issuer is not _ISSUER:
            raise ValueError("accounting.owned_cash_proof_required")
        self._release_context = release_context
        self._release_identity_bytes = self.release_guard(
            guard, policy, release_context, expected_release_identity_bytes
        )
        self._state_bytes = canonical({k: deepcopy(state[k]) for k in IDENTITY_FIELDS})
        self._book_id = book_id
        self._guard_sha = digest(guard)
        self._ledger_sha = ledger_sha256
        self._identity = sha256(self._state_bytes)
        self._sealed = True

    def __setattr__(self, key, value):
        if getattr(self, "_sealed", False):
            raise ValueError("accounting.cash_proof_is_immutable")
        object.__setattr__(self, key, value)

    def __deepcopy__(self, memo):
        return self

    @property
    def sha256(self):
        value = dict(
            state_sha256=self._identity,
            book_id=self._book_id,
            guard_sha256=self._guard_sha,
            ledger_sha256=self._ledger_sha,
        )
        if self._release_identity_bytes is not None:
            value["release_context_binding"] = self.binding_value(
                self._release_identity_bytes
            )
        return digest(value)

    def check(
        self,
        state,
        guard,
        *,
        release_context=None,
        expected_release_identity_bytes=None,
        policy=None,
    ):
        if (
            digest({k: state[k] for k in IDENTITY_FIELDS}) != self._identity
            or digest(guard) != self._guard_sha
            or state.get("_risk_clock", {}).get("book_id") != self._book_id
            or state["rights"]
            or state["unknown_components"]
        ):
            raise ValueError("accounting.cash_proof_state_or_scope_mismatch")
        expected = self._release_identity_bytes
        if not self.release_requested(
            guard, release_context, expected_release_identity_bytes
        ) and (
            release_context is not None or expected_release_identity_bytes is not None
        ):
            raise ValueError("B.release_context_scope_mismatch")
        if (
            expected_release_identity_bytes is not None
            and expected_release_identity_bytes != expected
        ):
            raise ValueError("B.release_context_persistent_identity_mismatch")
        raw = self.release_guard(
            guard,
            policy,
            self._release_context if release_context is None else release_context,
            expected,
        )
        if raw != expected:
            raise ValueError("B.release_context_persistent_identity_mismatch")
        from .noncash_v3 import allowed_symbols

        allowed = allowed_symbols(guard)
        for row in state["receivables"].values():
            if (
                row["kind"] not in {"cash_dividend", "sale_proceeds"}
                or row["symbol"] not in allowed
                or not is_sha(row["source_sha256"])
                or amount(row["amount"]) < 0
            ):
                raise ValueError("accounting.non_cash_or_unproven_receivable")
        return self.value

    @property
    def value(self):
        return sum(
            (
                amount(r["amount"])
                for r in json.loads(self._state_bytes)["receivables"].values()
            ),
            amount(0),
        )


def check_cash_state(
    state,
    guard,
    cash_proof,
    *,
    initial=False,
    release_context=None,
    expected_release_identity_bytes=None,
    policy=None,
):
    """Classify proven cash for the unchanged legacy noncash-only proof.

    The raw state, its SHA and every retained receivable stay intact. This
    temporary view is exclusively for the noncash inventory guard; no monetary
    value or economic state is imputed/erased. D1/NAV consume the full amount.
    """
    from .execution_exposure import verify_execution_exposure
    from .execution_state import necessary_execution_state_known

    necessary_execution_state_known(state)
    CashProof.release_guard(
        guard, policy, release_context, expected_release_identity_bytes
    )
    if state["receivables"] and not initial:
        if type(cash_proof) is not CashProof:
            raise ValueError("accounting.owned_cash_proof_required")
        cash_proof.check(
            state,
            guard,
            release_context=release_context,
            expected_release_identity_bytes=expected_release_identity_bytes,
            policy=policy,
        )
        view = deepcopy(state)
        view["receivables"] = {}
        verify_execution_exposure(view, guard)
        return cash_proof.value
    verify_execution_exposure(state, guard, initial=initial)
    return amount(0)


def issue_cash_proof(
    state,
    *,
    book_id,
    guard,
    ledger_sha256,
    release_context=None,
    expected_release_identity_bytes=None,
    policy=None,
):
    """Internal producer boundary, called after C04 reconciliation, not on wire."""
    if (
        not is_sha(book_id)
        or not is_sha(ledger_sha256)
        or state["rights"]
        or state["unknown_components"]
        or amount(state["cash"]) < 0
        or amount(state["nav"]) <= 0
    ):
        raise ValueError("accounting.complete_cash_close_required")
    return CashProof(
        _ISSUER,
        state,
        book_id,
        guard,
        ledger_sha256,
        release_context=release_context,
        expected_release_identity_bytes=expected_release_identity_bytes,
        policy=policy,
    )


def _cash_lineage(event):
    from .lineage_schema import EVENT, validate_consumer
    from .event_quarantine import quarantine_check

    extra = {
        "event_id",
        "book_id",
        "kind",
        "cash_basis",
        "receivable_id",
        "amount",
        "available_at",
        "confirmed_at",
    }
    validate_consumer(event, schema=dict(EVENT, **dict.fromkeys(extra, "scalar")))
    result = quarantine_check({"event": {k: v for k, v in event.items() if k in EVENT}})
    if not result["ok"]:
        raise ValueError(
            "accounting.cash_lineage_rejected:" + ";".join(result["reasons"])
        )


def dividend_entitlement(
    event,
    *,
    book_id,
    previous_inventory,
    session,
    expected_event_sha256,
    guard,
    policy,
    release_context=None,
    expected_release_identity_bytes=None,
):
    """Derive integer entitlement from the retained pre-ex-open inventory.

    Source acceptance is a host capability, not a caller's verified boolean.
    QQQ additionally retains the existing pinned cash-source restriction.
    """
    from .noncash_v3 import assert_consumer_symbols

    reject_b2_inputs(event, "holdings_cash")
    _cash_lineage(event)
    symbol = event.get("symbol")
    CashProof.release_guard(
        guard, policy, release_context, expected_release_identity_bytes
    )
    assert_consumer_symbols(guard, "cash_valuation", [symbol], policy)
    if (
        not is_sha(expected_event_sha256)
        or digest(event) != expected_event_sha256
        or event.get("book_id") != book_id
        or not is_sha(event.get("source_sha256"))
        or event.get("kind") != "cash_dividend"
        or event.get("ex_date") != session
        or event.get("ex_date_status") != "verified"
        or event.get("exact_amount_status") != "verified_exact"
        or event.get("cash_basis") != "integer_pre_tax_cash"
        or symbol not in previous_inventory
    ):
        raise ValueError("accounting.cash_event_source_or_units_unknown")
    if symbol == "QQQ":
        reason = cash_source_reason(event)
        if reason:
            raise ValueError(reason)
    q = previous_inventory[symbol]
    if type(q) is not int or q < 0 or event.get("entitled_integer_shares") != q:
        raise ValueError("accounting.entitlement_not_previous_close_inventory")
    per_share = amount(event["declared_cash_amount"])
    if per_share < 0:
        raise ValueError("accounting.dividend_amount_unknown")
    pay = event.get("pay_date")
    if pay is not None and (
        date.fromisoformat(pay).isoformat() != pay or pay < session
    ):
        raise ValueError("accounting.payment_date_unknown_or_precedes_exdate")
    total = per_share * q
    return dict(
        kind="cash_dividend",
        symbol=symbol,
        amount=decimal_text(total),
        entitlement_shares=q,
        ex_date=session,
        pay_date=pay or "UNKNOWN",
        source_sha256=event["source_sha256"],
        payment_state="UNPAID" if pay is not None else "PAYDATE_UNKNOWN",
    )


def payment_amount(event, *, book_id, receivable, expected_event_sha256, asof):
    reject_b2_inputs(event, "holdings_cash")
    _cash_lineage(event)
    if (
        not is_sha(expected_event_sha256)
        or digest(event) != expected_event_sha256
        or event.get("book_id") != book_id
        or not is_sha(event.get("source_sha256"))
        or event.get("kind") != "cash_available"
        or event.get("cash_basis") != "integer_pre_tax_cash"
        or receivable["payment_state"] != "UNPAID"
        or event.get("symbol") != receivable["symbol"]
        or utc_instant(event["available_at"]) > utc_instant(event["confirmed_at"])
        or utc_instant(event["confirmed_at"]) > utc_instant(asof)
        or (
            receivable["kind"] == "cash_dividend"
            and utc_instant(event["available_at"]).date().isoformat()
            < receivable["pay_date"]
        )
        or amount(event["amount"]) != amount(receivable["amount"])
    ):
        raise ValueError("accounting.available_cash_receipt_required")
    return amount(event["amount"])
