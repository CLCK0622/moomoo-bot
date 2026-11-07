"""C08 input boundary: unchanged three-state predicate and actor-specific B reads.

Necessary M comes only from the shared C06 RiskBook. There is no risk/quantity
algorithm here. C04 still owns accounting and C09 still must bind actual source
capabilities; collecting inputs and a complete M never grants runtime credit.
"""

from copy import deepcopy

from .contract import code_sha, digest, is_sha
from .conventions import load_conventions
from .fees import finite
from .execution_cash import check_cash_state
from .execution_risk import RiskBook
from .noncash_v3 import CONSUMERS, assert_consumer_symbols
from .reference_noncash import numeric_read, origin
from .reference_profile_v301 import validate_solo_profile
from .reference_v3_scope import validate_scope


class BookScopedInputs:
    """Read-only declared snapshot and scope; production provenance is separate.

    No result, orders, M, callback from an input wire, or replacement snapshot
    can be supplied to read(). The callable is an owned host capability, as in
    reference_compile_v3; C09 must bind its source before any real reception.
    """

    def __init__(
        self,
        profile,
        scope,
        book_id,
        state,
        initial,
        expected_state_sha256,
        *,
        policy=None,
        cash_proof=None,
        release_context=None,
        expected_release_identity_bytes=None,
    ):
        self._policy = policy or load_conventions()
        self._release_context = release_context
        self._release_identity_bytes = expected_release_identity_bytes
        self._cash_proof = cash_proof
        self._profile = validate_solo_profile(profile)
        if not is_sha(book_id):
            raise ValueError("reference.book_identity_required")
        self._book_id = book_id
        self._actor = "reference/" + self._profile["definition"]["member_id"]
        self._scope = deepcopy(scope)
        self._state = deepcopy(state)
        self._initial = deepcopy(initial)
        self._expected_state_sha256 = expected_state_sha256
        self._validate()

    def _validate(self):
        scope = self._scope
        validate_scope(
            scope,
            dict(train=scope["train"], warmup=scope["warmup"]),
            {
                k: self._policy.binding[k]
                for k in (
                    "conventions_version",
                    "conventions_sha256",
                    "prereg_sha256",
                    "common_profile_sha256",
                )
            },
            policy=self._policy,
            release_context=self._release_context,
            expected_release_identity_bytes=self._release_identity_bytes,
        )
        self._release_identity_bytes = RiskBook.release_guard(
            scope["guard"],
            self._policy,
            self._release_context,
            self._release_identity_bytes,
        )
        initial = self._initial
        if (
            type(initial) is not dict
            or not {"initial_state", "source_sha256"}.issubset(initial)
            or origin(
                scope["guard"],
                self._actor,
                initial["initial_state"],
                initial["source_sha256"],
                self._policy,
                release_context=self._release_context,
                expected_release_identity_bytes=self._release_identity_bytes,
            )
            != initial
        ):
            raise ValueError("reference.separate_zero_origin_required")
        if (
            not is_sha(self._expected_state_sha256)
            or digest(self._state) != self._expected_state_sha256
        ):
            raise ValueError("reference.book_snapshot_identity_mismatch")
        # Reuse the original R2/B check. Never clear unknowns, rights or holdings
        # to manufacture a zero origin, and never reconstruct an initial book.
        check_cash_state(
            self._state,
            scope["guard"],
            self._cash_proof,
            policy=self._policy,
            release_context=self._release_context,
            expected_release_identity_bytes=self._release_identity_bytes,
        )
        if (
            type(self._state.get("initialization_count")) is not int
            or self._state["initialization_count"] != 1
        ):
            raise ValueError("state.R2_necessary_state_unknown")

    @property
    def retained_state(self):
        return deepcopy(self._state)

    def read(
        self,
        date,
        consumer,
        symbols,
        reader,
        *,
        risk_scope,
        close_session,
        prior_risk,
        fees_x2,
        clock_binding,
        expected_prior_risk_sha256,
        expected_clock_binding_sha256,
        expected_ruling_sha256,
        expected_snapshot_sha256,
        signal,
        expected_signal_sha256,
    ):
        self._validate()
        scope, state = self._scope, self._state
        if date not in scope["train"]:
            raise ValueError("reference.execution_date_outside_train")
        if consumer not in CONSUMERS:
            raise ValueError("reference.numeric_consumer_required")
        if (
            type(symbols) is not list
            or not all(type(s) is str for s in symbols)
            or len(symbols) != len(set(symbols))
        ):
            raise ValueError("reference.numeric_symbol_list_required")
        symbols = list(symbols)
        # Validate the complete batch before invoking the first callback. The
        # B predicate precedes even a membership/eligibility-based read filter.
        assert_consumer_symbols(
            scope["guard"],
            consumer,
            symbols,
            self._policy,
            release_context=self._release_context,
            expected_release_identity_bytes=self._release_identity_bytes,
        )
        eligible = set(scope["numeric_symbols"][date])
        if consumer in {"score", "label", "calibration"}:
            allowed = eligible | ({"QQQ"} if consumer == "label" else set())
        else:
            # A held clean name can leave E(t). Keep it for M and valuation;
            # isolation is neither a sale nor permission to erase its position.
            held = {s for s, q in state["inventory"].items() if q}
            allowed = eligible | held | {"QQQ"}
        if not set(symbols).issubset(allowed):
            raise ValueError("reference.numeric_read_outside_role_scope")
        definition = self._profile["definition"]
        if type(risk_scope) is not dict or any(
            risk_scope.get(k) != definition[k]
            for k in ("member_id", "recipe_id", "execution_role")
        ):
            raise ValueError("reference.risk_member_scope_mismatch")
        if type(signal) is not dict or signal.get("execution_session") != date:
            raise ValueError("reference.execution_date_binding_mismatch")
        # Own the same B and original state on both paths. All remaining inputs
        # are verbatim C06 constructor parameters, with host-expected hashes.
        # C06 alone validates/generates M and its refusal reasons.
        risk = RiskBook(
            book_id=self._book_id,
            scope=risk_scope,
            close_session=close_session,
            state=state,
            prior_risk=prior_risk,
            fees_x2=fees_x2,
            canonical_scenario="x2",
            expected_original_state_sha256=self._expected_state_sha256,
            expected_prior_risk_sha256=expected_prior_risk_sha256,
            guard=scope["guard"],
            clock_binding=clock_binding,
            expected_clock_binding_sha256=expected_clock_binding_sha256,
            expected_ruling_sha256=expected_ruling_sha256,
            policy=self._policy,
            cash_proof=self._cash_proof,
            release_context=self._release_context,
            expected_release_identity_bytes=self._release_identity_bytes,
        )
        required = risk.required_m(
            signal,
            expected_book_id=self._book_id,
            expected_close_session=close_session,
            expected_snapshot_sha256=expected_snapshot_sha256,
            expected_original_state_sha256=self._expected_state_sha256,
            expected_signal_sha256=expected_signal_sha256,
        )
        calls = []

        def read_symbol(symbol):
            calls.append(symbol)
            return reader(date, symbol)

        values, receipt = {}, None
        if required["complete"]:
            values, receipt = numeric_read(
                scope["guard"],
                self._actor,
                consumer,
                symbols,
                read_symbol,
                self._policy,
                initial=self._initial,
                release_context=self._release_context,
                expected_release_identity_bytes=self._release_identity_bytes,
            )
        if any(type(v) not in (int, float) or not finite(v) for v in values.values()):
            raise ValueError("reference.execution_numeric_value_unknown")
        day = scope["days"][date]
        payload = dict(
            schema="EVO884.ReferenceInputRead/v1",
            actor=self._actor,
            book_id=self._book_id,
            date=date,
            quantity_state=day["quantity_state"],
            new_tilt_allowed=day["new_tilt_allowed"],
            scope_sha256=scope["scope_sha256"],
            profile_sha256=self._profile["profile_sha256"],
            retained_state_sha256=digest(state),
            close_session=close_session,
            risk_scope_sha256=digest(risk_scope),
            risk_snapshot_sha256=required["snapshot_sha256"],
            fees_x2=fees_x2,
            reader_source_sha256=code_sha(reader),
            receipt=receipt,
            numeric_reader_calls=len(calls),
            accessed_roles=[consumer] if calls else [],
            worker_roles=[],
            inputs_complete=required["complete"],
            accounting_required=True,
            accounting_executed=False,
            required_M=deepcopy(required["M"]),
            required_m_receipt=required,
            reasons=list(required["reasons"])
            or ["execution.C04_accounting_and_C09_reception_not_connected"],
            complete=False,
            runtime_consumable=False,
            certifiable=False,
        )
        return values, dict(payload, input_read_sha256=digest(payload))
