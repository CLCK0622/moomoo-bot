"""C11: collect current objects and existing evidence, without certifying them.

The host supplies its actual entry/shared-object registry. A registration time
or an old static seal cannot replace a new inventory. This is the collection
boundary used by C09/C10 later; it never opens a strategy or authority writer.
"""

from copy import deepcopy
from datetime import datetime
import re

from ..contract import digest, is_sha
from ..prefreeze.collection import collect
from .g14 import PROTOCOL_SHA256, adopted_protocol


def utc(value):
    if type(value) is not str or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z",
        value,
    ):
        raise ValueError("collection.utc_required")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def collect_execution(*, run_id, observed_at, **bindings):
    """Observe all four categories and list every gap, including every book.

    `bindings` is the prefreeze collector's explicit host registry and existing
    evidence paths. Original documents keep their own untrusted claims. Nothing
    in this return value asserts a DAG, B proof or nonauthor review is authentic.
    """
    utc(observed_at)
    if type(run_id) is not str or not run_id.strip():
        raise ValueError("collection.run_id_required")
    observed = collect(**bindings)
    gaps = list(observed["collection_gaps"])
    records = {
        **{
            f"sources/{role}/{name}": record
            for role, entries in observed["sources"].items()
            for name, record in entries.items()
        },
        "read_dag": observed["read_dag"],
        "scope": observed["scope"],
        **{
            "ledger_B_proofs/" + book: record
            for book, record in observed["ledger_B_proofs"].items()
        },
    }
    for key, record in records.items():
        gaps.extend(key + ":" + reason for reason in record["reasons"])
    body = dict(
        schema="EVO884.ExecutionCollection/v1",
        run_id=run_id,
        observed_at=observed_at,
        observations=observed,
        missing_items=gaps,
        certification=None,
        certification_reason="collection.nonauthor_review_and_reseal_required",
    )
    return dict(body, collection_sha256=digest(body))


def check_preperformance_collection(current, registered, *, performance_started_at):
    """Consistency/time check only; no runtime approval or seal is minted.

    `registered` must come from the host's externally retained preperformance
    inventory. A caller-provided inventory is not a trusted registration. The
    later formal receiver must independently establish this provenance.
    """
    for packet in (current, registered):
        if packet.get("schema") != "EVO884.ExecutionCollection/v1" or packet.get(
            "collection_sha256"
        ) != digest({k: v for k, v in packet.items() if k != "collection_sha256"}):
            raise ValueError("collection.inventory_identity_invalid")
        if packet["missing_items"]:
            raise ValueError("collection.required_evidence_missing")
    if current["run_id"] != registered["run_id"]:
        raise ValueError("collection.run_binding_changed")
    if current["observations"] != registered["observations"]:
        raise ValueError("collection.preperformance_inventory_changed")
    if not (
        utc(registered["observed_at"])
        <= utc(current["observed_at"])
        < utc(performance_started_at)
    ):
        raise ValueError("collection.inventory_not_preperformance")
    return deepcopy(current)


class ForwardAnchors:
    """In-memory append-only collection, not a prospective-OOS certification.

    Actual input/output timestamps and the previously retained log are host
    observations, never times accepted from an economic producer. This class
    cannot prove that host provenance; the formal receiver still needs it.
    No persistence, L0, sample acquisition, budget or clock reset is performed.
    """

    def __init__(self, *, run_id, rule_sha256, start_at, previous=()):
        adopted_protocol()
        utc(start_at)
        if not run_id or not is_sha(rule_sha256):
            raise ValueError("collection.forward_identity_required")
        self._run, self._rule, self._start = run_id, rule_sha256, start_at
        self._records = []
        self._pending = {}
        self._seen = set()
        for item in previous:
            self._retain(item)

    def _retain(self, item):
        body = {k: v for k, v in item.items() if k != "anchor_sha256"}
        if (
            set(body) != {"sequence", "previous_sha256", "input", "output"}
            or item.get("anchor_sha256") != digest(body)
            or body["sequence"] != len(self._records)
            or body["previous_sha256"]
            != (self._records[-1]["anchor_sha256"] if self._records else None)
        ):
            raise ValueError("collection.forward_log_rewritten")
        event = body["input"]
        self._check_input(event)
        self._check_output(event, body["output"])
        self._seen.add(event["sample_id"])
        self._records.append(deepcopy(item))

    def _check_input(self, event):
        if set(event) != {
            "run_id",
            "rule_sha256",
            "sample_id",
            "sample_origin",
            "first_evaluation_id",
            "event_at",
            "available_at",
            "decision_at",
            "observed_at",
            "visible_input_sha256",
            "input_manifest_sha256",
            "protocol_sha256",
        }:
            raise ValueError("collection.forward_input_schema")
        if (
            event["run_id"] != self._run
            or event["rule_sha256"] != self._rule
            or event["protocol_sha256"] != PROTOCOL_SHA256
            or type(event["sample_id"]) is not str
            or not event["sample_id"]
            or event["first_evaluation_id"] != event["sample_id"]
            or event["sample_origin"] != "actual_forward_unseen"
            or event["sample_id"] in self._seen
            or event["sample_id"] in self._pending
        ):
            raise ValueError("collection.not_new_unseen_forward_sample")
        if not all(
            is_sha(event[k]) for k in ("visible_input_sha256", "input_manifest_sha256")
        ):
            raise ValueError("collection.forward_input_identity")
        if not (
            utc(self._start)
            <= utc(event["event_at"])
            <= utc(event["available_at"])
            <= utc(event["observed_at"])
            <= utc(event["decision_at"])
        ):
            raise ValueError("collection.forward_input_visibility_or_time")

    def observe_input(self, event):
        self._check_input(event)
        self._pending[event["sample_id"]] = deepcopy(event)
        return digest(event)

    @staticmethod
    def _check_output(event, output):
        if (
            set(output)
            != {"input_anchor_sha256", "output_sha256", "produced_at", "observed_at"}
            or output["input_anchor_sha256"] != digest(event)
            or not is_sha(output["output_sha256"])
            or not utc(event["decision_at"])
            <= utc(output["produced_at"])
            <= utc(output["observed_at"])
        ):
            raise ValueError("collection.forward_output_binding_or_time")

    def observe_output(self, sample_id, output):
        event = self._pending.get(sample_id)
        if event is None:
            raise ValueError("collection.forward_input_anchor_required")
        self._check_output(event, output)
        body = dict(
            sequence=len(self._records),
            previous_sha256=self._records[-1]["anchor_sha256"]
            if self._records
            else None,
            input=event,
            output=deepcopy(output),
        )
        del self._pending[sample_id]
        self._retain(dict(body, anchor_sha256=digest(body)))
        return self.export()

    def export(self):
        return deepcopy(self._records)
