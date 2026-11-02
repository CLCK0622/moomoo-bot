"""Independent training-book genesis and the existing three-session startup.

This component neither runs a reference nor opens an authority/account store.
The caller owns persistence of export_bytes() and its separate current receipt.
Restore requires that externally bound current SHA and replays the accounting
events, rather than trusting a caller-supplied terminal state. Source acceptance,
general daily accounting and risk transitions belong to C09/C04/C06 respectively.
"""

from copy import deepcopy
from functools import wraps
import json
import math
from threading import RLock

from .contract import canonical, digest, sha256
from .conventions import authoritative, load_conventions
from .execution import initial_build_turnover_check, lock_startup_intent
from .execution_closure import fee_context, reference_model, validate_execution_binding
from .fees import finite
from .pipeline import price_basis_check
from .reference_definition_v301 import FROZEN, frozen_documents, reference_definitions
from .reference_profile_v301 import solo_profile
from .reference_validation import utc_instant


CONTRACT_SHA256 = "f7a0623da88a7e2874ef5e372750ad04a1edca9796acc0c3fee02616f766a496"

INITIAL_FIELDS = {
    "asof",
    "inventory",
    "cash",
    "nav",
    "fees_x2",
    "age",
    "origin",
    "rights",
    "receivables",
    "pending_orders",
    "unknown_components",
    "initialization_count",
    "peak",
    "risk_latch",
}


def _number(value, *, positive=False):
    return (
        type(value) in (int, float)
        and finite(value)
        and (value > 0 if positive else value >= 0)
    )


def _locked(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return call


def _transition(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            if self._transitioning:
                raise ValueError("startup.reentrant_state_transition_forbidden")
            self._transitioning = True
            try:
                with fee_context(self._execution_binding):
                    return method(self, *args, **kwargs)
            finally:
                self._transitioning = False

    return call


class _Journal:
    def __init__(self):
        self.rows = {}

    def recorded(self, key):
        return deepcopy(self.rows.get(key))

    def record(self, key, value):
        if key in self.rows and self.rows[key] != value:
            raise ValueError("startup.record_conflict")
        self.rows[key] = deepcopy(value)


def _candidate_startup_binding(member_id, execution_role):
    """Project registered definitions into startup identity, not a new profile.

    The common profile supplies the finite family/window grammar and unchanged
    initialization. META retains its original selection-layer role. This
    binding introduces no quantity, risk, signal or pool-selection algorithm.
    """
    documents = frozen_documents()
    common = documents["EVO883-D12-common-profile-v3.0.1.json"]
    shared = documents["EVO883-D12-shared-execution-contract-v3.0.1.json"]
    recipes = {
        f"{family['id']}-L{window:03}": dict(family, window=window)
        for family in common["signal_params"]["families"]
        for window in common["signal_params"]["windows"]
    }
    role = (
        "candidate_solo_probe"
        if member_id in recipes
        else "current_META_POLICY_execution_layer"
        if member_id == "META_POLICY_V3"
        else None
    )
    if role is None:
        raise ValueError("reference.member_not_registered_or_incomplete")
    if execution_role != role or role not in shared["applies_to"]:
        raise ValueError("reference.execution_role_mismatch")
    definition = dict(
        schema="EVO884.CandidateStartupBinding/v1",
        member_id=member_id,
        recipe_id=member_id,
        execution_role=role,
        fixed_recipe=recipes.get(member_id),
        registered_sources=deepcopy(FROZEN),
    )
    profile = dict(
        definition=definition,
        common_profile=common,
        purpose="startup identity only; unchanged common three-session algorithm",
    )
    return dict(definition_sha256=digest(definition)), dict(
        profile_sha256=digest(profile)
    )


class StartupBook:
    """One member × frozen fold × actual attempt; no cross-book state copying.

    Prices are supplied by an already scoped reader, never acquired here. Close
    valuation components are explicit known inputs from the daily-accounting
    boundary: missing components refuse, they are never inferred as zero. This
    class does not certify the reader or these inputs as production evidence.
    """

    def __init__(
        self,
        member_id,
        fold_id,
        attempt_id,
        initial_state,
        context,
        *,
        execution_binding,
        execution_role=None,
        policy=None,
    ):
        self._execution_binding = validate_execution_binding(execution_binding)
        self._policy = policy or load_conventions()
        if (
            not authoritative(self._policy)
            or self._policy.document["version"] != "v3.0.0"
        ):
            raise ValueError("startup.frozen_v3_required")
        definitions = {d["member_id"]: d for d in reference_definitions()}
        if type(member_id) is not str:
            raise ValueError("reference.member_not_registered_or_incomplete")
        if member_id in definitions:
            definition = definitions[member_id]
            if execution_role not in (None, definition["execution_role"]):
                raise ValueError("reference.execution_role_mismatch")
            profile = solo_profile(definition)
        else:
            definition, profile = _candidate_startup_binding(member_id, execution_role)
        if (
            type(fold_id) is not str
            or type(attempt_id) is not str
            or not attempt_id.strip()
        ):
            raise ValueError("startup.book_identity_required")
        folds = self._policy.fold_manifest()["folds"]
        fold = next((row for row in folds if row["fold_id"] == fold_id), None)
        if fold is None:
            raise ValueError("startup.frozen_fold_required")
        calendar = list(self._policy.calendar)
        start = calendar.index(fold["train_start"])
        end = calendar.index(fold["train_end"])
        self._sessions = calendar[start - 1 : end + 1]
        if start == 0 or len(self._sessions) < 7:
            raise ValueError("startup.previous_close_and_train_calendar_required")
        price_basis_check(context)
        self._context = deepcopy(context)
        state = deepcopy(initial_state)
        domain = set(self._policy.profile["universe"]) | {"QQQ"}
        e0 = self._policy.document["initialization"]["initial_cash_usd"]
        if not isinstance(state, dict) or set(state) != INITIAL_FIELDS:
            raise ValueError("startup.complete_initial_state_required")
        if (
            not isinstance(state["inventory"], dict)
            or set(state["inventory"]) != domain
        ):
            raise ValueError("startup.complete_initial_inventory_required")
        if any(type(q) is not int or q != 0 for q in state["inventory"].values()):
            raise ValueError("startup.initial_inventory_must_be_zero")
        if any(
            type(state[k]) is not dict or state[k]
            for k in ("age", "origin", "rights", "receivables")
        ):
            raise ValueError("startup.initial_rights_or_position_state_not_empty")
        if any(
            type(state[k]) is not list or state[k]
            for k in ("pending_orders", "unknown_components")
        ):
            raise ValueError("startup.initial_orders_or_unknown_state_not_empty")
        if (
            any(not _number(state[k]) for k in ("cash", "nav", "fees_x2", "peak"))
            or state["cash"] != e0
            or state["nav"] != e0
            or state["peak"] != e0
            or state["fees_x2"] != 0
            or state["risk_latch"] is not False
            or type(state["initialization_count"]) is not int
            or state["initialization_count"] != 1
            or utc_instant(state["asof"]).date().isoformat() != self._sessions[0]
        ):
            raise ValueError("startup.O0_requires_proven_E0_state")
        self._identity = dict(
            member_id=member_id,
            fold_id=fold_id,
            attempt_id=attempt_id,
            scope="independent_training",
            first_open=self._sessions[1],
            shared_execution_contract_sha256=CONTRACT_SHA256,
            member_definition_sha256=definition["definition_sha256"],
            solo_profile_sha256=profile["profile_sha256"],
            execution_binding=deepcopy(self._execution_binding),
            **self._policy.binding,
        )
        if member_id not in definitions:
            self._identity["execution_role"] = execution_role
        self._book_id = digest(self._identity)
        self._model = reference_model(
            self._execution_binding,
            book_id=self._book_id,
            scope=self._identity["scope"],
        )
        self._genesis = state
        self._state = deepcopy(state)
        # These fields describe the verified genesis only. C06 owns later risk
        # transitions; a copied initial false latch is not a current risk state.
        for key in (
            "peak",
            "risk_latch",
            "age",
            "origin",
            "rights",
            "receivables",
            "pending_orders",
            "unknown_components",
        ):
            del self._state[key]
        self._journal = _Journal()
        self._events = []
        self._position = 0
        self._intent = None
        self._needs_close = False
        self._halt = None
        self._previous_close_nav = e0
        self._valuation = dict(
            rights_value=0, receivables_value=0, components_known=True
        )
        self._lock = RLock()
        self._transitioning = False

    @property
    def sessions(self):
        return tuple(self._sessions)

    @property
    def book_id(self):
        return self._book_id

    @property
    def identity(self):
        return deepcopy(self._identity)

    @_locked
    def snapshot(self):
        return deepcopy(
            dict(
                book_id=self._book_id,
                identity=self._identity,
                genesis=self._genesis,
                model_receipt=self._model,
                account_state=self._state,
                valued_components=self._valuation,
                complete_account_state=None,
                complete_account_reason="execution.shared_daily_accounting_and_risk_require_C04_C06",
                position=self._position,
                pending_intent=self._intent,
                pending_close=self._needs_close,
                startup_complete=self._position == 3 and not self._needs_close,
                first_regular_signal_close=self._sessions[6],
                first_regular_open=self._sessions[7]
                if len(self._sessions) > 7
                else None,
                current_risk_state=None,
                current_risk_reason="execution.risk_transition_requires_C06",
                halt_reason=self._halt,
                runtime_consumable=False,
                certifiable=False,
            )
        )

    def _ready(self):
        if self._halt:
            raise ValueError("startup.book_halted:" + self._halt)
        if self._position >= 3:
            raise ValueError("startup.phase_finished_no_extension_or_topup")

    @_transition
    def prepare_next_open(self):
        self._ready()
        if self._needs_close:
            raise ValueError("startup.verified_previous_close_required")
        if self._intent is not None:
            raise ValueError("startup.intent_already_locked")
        inv = {"QQQ": self._state["inventory"]["QQQ"]}
        intent = lock_startup_intent(
            self._position,
            self._state["nav"],
            inv,
            self._state["asof"],
            policy=self._policy,
            ledger=self._journal,
            start_id=self._book_id,
            scope_id=self._book_id,
        )
        self._intent = intent
        self._events.append(dict(kind="intent", output=deepcopy(intent)))
        return deepcopy(intent)

    @_transition
    def execute_open(self, timestamp, reader):
        self._ready()
        if self._needs_close or self._intent is None:
            raise ValueError("startup.preclose_intent_receipt_missing")
        instant = utc_instant(timestamp)
        if instant.date().isoformat() != self._sessions[
            self._position + 1
        ] or instant <= utc_instant(self._intent["previous_close"]):
            raise ValueError("startup.reference_session_mismatch")
        # All identity, phase, state and date checks precede the only price read.
        price_basis_check(self._context)
        try:
            price = reader(self._sessions[self._position + 1], "QQQ")
        except Exception as exc:
            self._halt = "data.startup_price_read_failed"
            self._events.append(
                dict(kind="failed_read", timestamp=timestamp, reason=self._halt)
            )
            raise ValueError(self._halt) from exc
        if not _number(price, positive=True):
            self._halt = "data.raw_open_price_invalid"
            self._events.append(
                dict(
                    kind="failed_open",
                    timestamp=timestamp,
                    price=price,
                    reason=self._halt,
                )
            )
            raise ValueError(self._halt)
        request = dict(
            intent=deepcopy(self._intent),
            context=deepcopy(self._context),
            previous_close=self._intent["previous_close"],
            reference_sessions=list(self._sessions[:4]),
            raw_open_prices={"QQQ": price},
            cash=self._state["cash"],
            open_timestamp=timestamp,
            sell_date=instant.date().isoformat(),
            rate_basis="research_restored",
            start_id=self._book_id,
        )
        report = initial_build_turnover_check(
            request, conventions=self._policy, ledger=self._journal
        )
        if not report["ok"]:
            self._halt = report["reasons"][0]
            self._events.append(
                dict(
                    kind="failed_open",
                    timestamp=timestamp,
                    price=price,
                    reason=self._halt,
                )
            )
            raise ValueError(self._halt)
        actual = deepcopy(report["metrics"])
        actual.update(
            plan_accepted=True,
            planned_quantity=actual["quantity"],
            modeled_filled_quantity=actual["quantity"],
            model_receipt=deepcopy(self._model),
            execution_verified=False,
        )
        self._previous_close_nav = self._state["nav"]
        self._state["inventory"]["QQQ"] = actual["inventory"]["QQQ"]
        self._state["cash"] = actual["cash"]
        self._state["fees_x2"] += actual["fee_x2"]
        self._state["asof"] = timestamp
        self._state["nav"] = math.fsum(
            (
                actual["cash"],
                actual["inventory"]["QQQ"] * price,
                self._valuation["rights_value"],
                self._valuation["receivables_value"],
            )
        )
        self._needs_close = True
        self._events.append(
            dict(kind="open", timestamp=timestamp, price=price, output=deepcopy(actual))
        )
        return deepcopy(actual)

    @_transition
    def close_session(self, timestamp, raw_qqq_close, valuation):
        """Record a known close, keeping explicit rights/receivables separate.

        C04 supplies these already reconciled components; no event, entitlement,
        payment-date or fractional-TR inference occurs in startup accounting.
        The book never accepts an externally supplied inventory, NAV or return.
        """
        self._ready()
        if not self._needs_close:
            raise ValueError("startup.actual_open_required_before_close")
        if (
            utc_instant(timestamp).date().isoformat()
            != self._sessions[self._position + 1]
            or utc_instant(timestamp) <= utc_instant(self._events[-1]["timestamp"])
            or not _number(raw_qqq_close, positive=True)
            or not isinstance(valuation, dict)
            or set(valuation)
            != {"rights_value", "receivables_value", "components_known"}
            or valuation["components_known"] is not True
            or not all(
                _number(valuation[k]) for k in ("rights_value", "receivables_value")
            )
        ):
            raise ValueError("startup.necessary_close_valuation_unknown")
        prior_nav = self._previous_close_nav
        nav = math.fsum(
            (
                self._state["cash"],
                self._state["inventory"]["QQQ"] * raw_qqq_close,
                valuation["rights_value"],
                valuation["receivables_value"],
            )
        )
        if not _number(nav, positive=True):
            raise ValueError("startup.necessary_close_valuation_unknown")
        self._state.update(asof=timestamp, nav=nav)
        self._valuation = deepcopy(valuation)
        output = dict(
            session=self._sessions[self._position + 1],
            position=self._position,
            previous_nav=prior_nav,
            nav=nav,
            day_return=nav / prior_nav - 1,
            cash=self._state["cash"],
            inventory=deepcopy(self._state["inventory"]),
            fees_x2=self._state["fees_x2"],
            valuation=deepcopy(valuation),
        )
        self._events.append(
            dict(
                kind="close",
                timestamp=timestamp,
                price=raw_qqq_close,
                valuation=deepcopy(valuation),
                output=deepcopy(output),
            )
        )
        self._position += 1
        self._intent = None
        self._needs_close = False
        return output

    @_locked
    def export_bytes(self):
        return canonical(
            dict(
                schema="execution.startup_book/v1",
                identity=self._identity,
                genesis=self._genesis,
                context=self._context,
                events=self._events,
            )
        )

    @classmethod
    def restore(
        cls, raw, *, expected_sha256, member_id, fold_id, attempt_id, policy=None
    ):
        """Replay actual receipts into a fresh object; no terminal-state fallback."""
        if sha256(raw) != expected_sha256:
            raise ValueError("startup.current_book_bytes_mismatch")
        document = json.loads(raw)
        if (
            set(document) != {"schema", "identity", "genesis", "context", "events"}
            or document["schema"] != "execution.startup_book/v1"
        ):
            raise ValueError("startup.book_schema_invalid")
        book = cls(
            member_id,
            fold_id,
            attempt_id,
            document["genesis"],
            document["context"],
            execution_binding=document["identity"].get("execution_binding"),
            execution_role=document["identity"].get("execution_role"),
            policy=policy,
        )
        if book.identity != document["identity"]:
            raise ValueError("startup.independent_book_identity_mismatch")
        for event in document["events"]:
            if event["kind"] == "intent":
                book.prepare_next_open()
            elif event["kind"] in ("open", "failed_open", "failed_read"):

                def reader(*_):
                    if event["kind"] == "failed_read":
                        raise ValueError("recorded unsuccessful read")
                    return event["price"]

                try:
                    book.execute_open(event["timestamp"], reader)
                except ValueError:
                    if event["kind"] not in ("failed_open", "failed_read"):
                        raise
            elif event["kind"] == "close":
                book.close_session(
                    event["timestamp"], event["price"], event["valuation"]
                )
            else:
                raise ValueError("startup.book_event_invalid")
        if book.export_bytes() != raw:
            raise ValueError("startup.book_replay_mismatch")
        return book
