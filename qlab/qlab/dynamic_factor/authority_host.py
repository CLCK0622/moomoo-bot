"""Opaque same-operation host objects; no installation or request-mintable trust.

Production approval-source wiring is deliberately unavailable before the
separately approved deployment/permission prerequisites. Private tests replace
that source adapter; they do not install a deployment or enable this adapter.
"""

from .arm_n import MISSING

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from weakref import WeakKeyDictionary, ref

from .contract import canonical, digest, sha256


_HOSTS = WeakKeyDictionary()
_SNAPSHOTS = WeakKeyDictionary()
_PINS = WeakKeyDictionary()
_VIEWS = WeakKeyDictionary()
_LATEST_SNAPSHOT = WeakKeyDictionary()


def reader_manifest():
    root = Path(__file__).parent
    names = (
        "authority_host.py",
        "authority_ledger.py",
        "authority_record_types.py",
        "authority_release.py",
        "authority_prefix.py",
        "authority_install_receipt.py",
        "authority_binding.py",
        "reception_v2.py",
        "reception_schema.py",
        "reception_entrypoints_v3.py",
        "contract.py",
        "arm_n.py",
        "statistics.py",
        "ledger.py",
        "pipeline.py",
        "__main__.py",
        "dsr_v0.py",
        "continuity.py",
        "reference_boundary.py",
    )
    paths = [root / name for name in names] + sorted(
        (root / "reception_contracts").glob("*.json")
    )
    return {
        str(path.relative_to(root)): sha256(path.read_bytes())
        if path.is_file()
        else None
        for path in paths
    }


def fingerprint(value):
    if type(value) is bytes:
        return {"raw_sha256": sha256(value), "raw_bytes": len(value)}
    if type(value) is dict:
        return {key: fingerprint(item) for key, item in value.items()}
    if type(value) in (list, tuple):
        return [fingerprint(item) for item in value]
    return value


def context_digest(source):
    return digest(fingerprint(source))


@dataclass(frozen=True, eq=False)
class ControlledHostContext:
    def __init__(self):
        raise TypeError("ledger.trusted_project_installation_required")


@dataclass(frozen=True, eq=False)
class InstalledAuthoritySnapshot:
    def __init__(self):
        raise TypeError("ledger.trusted_project_installation_required")


@dataclass(frozen=True, eq=False)
class RunPin:
    def __init__(self):
        raise TypeError("reception.N_stage_pin_changed")


def _read_approved_deployment():
    # No D or writer principal has been approved. No caller/env/path override.
    # The original permission/deployment adapter is a separately gated input.
    raise ValueError("ledger.trusted_project_installation_required")


def open_host_context():
    source = _read_approved_deployment()
    if type(source) is not dict or source.get("source_verified") is not True:
        raise ValueError("ledger.trusted_project_installation_required")
    if not source.get("approval_bytes") or not source.get("published_anchor_bytes"):
        raise ValueError("ledger.trusted_project_installation_required")
    context = object.__new__(ControlledHostContext)
    _HOSTS[context] = deepcopy(source)
    # Actual file observations are checked independently of the receipt claims.
    observe(context)
    return context


def host_data(context):
    if type(context) is not ControlledHostContext or context not in _HOSTS:
        raise ValueError("ledger.trusted_project_installation_required")
    return deepcopy(_HOSTS[context])


def observe(context):
    source = host_data(context)
    if source.get("reader_sources") != reader_manifest() or source[
        "module_path"
    ] != str(Path(__file__).with_name("authority_ledger.py").resolve()):
        raise ValueError("ledger.observed_object_drift")
    for role in ("module", "chain", "witness"):
        path = Path(source[role + "_path"])
        if (
            path.is_symlink()
            or not path.is_file()
            or str(path.resolve()) != source[role + "_path"]
        ):
            raise ValueError("ledger.observed_object_drift")
        raw = path.read_bytes()
        if sha256(raw) != source[role + "_sha256"]:
            raise ValueError("ledger.observed_object_drift")
        if role == "chain" and raw != source["chain_raw"]:
            raise ValueError("ledger.observed_object_drift")
        if role == "witness":
            from .reception_schema import strict_json
            from .authority_ledger import FIELDS

            measured = strict_json(raw)
            if (
                measured != source["witness"]
                or set(measured) != set(FIELDS) | {"ledger_file", "ledger_file_sha256"}
                or canonical(measured) + b"\n" != raw
            ):
                raise ValueError("ledger.tail_or_high_water_mismatch")
    expected = dict(
        chain_sha256=source["chain_sha256"],
        witness_sha256=source["witness_sha256"],
        anchor_sha256=sha256(source["published_anchor_bytes"]),
        reader_source_sha256=digest(source["reader_sources"]),
    )
    if any(source["identities"].get(key) != value for key, value in expected.items()):
        raise ValueError("reception.N_object_or_coverage_mismatch")
    return deepcopy(source)


def pin_run(context, *, arm_tag, run_id):
    from .arm_n import require_label

    require_label(arm_tag)
    source = observe(context)
    if type(run_id) is not str or not run_id.strip():
        raise ValueError("reception.N_stage_pin_changed")
    pin = object.__new__(RunPin)
    _PINS[pin] = (context, arm_tag, run_id, context_digest(source))
    return pin


def check_pin(context, pin, arm_tag):
    source = observe(context)
    if type(pin) is not RunPin or pin not in _PINS:
        raise ValueError("reception.N_stage_pin_changed")
    owner, arm, run, identity = _PINS[pin]
    if owner is not context or arm != arm_tag:
        raise ValueError("reception.N_arm_pin_conflict")
    if identity != context_digest(source):
        raise ValueError("reception.N_stage_pin_changed")
    return digest([identity, arm, run])


def _retain_snapshot(context, installation_result, replay, coverage):
    # Called only after N03 actual schema, source, byte, prefix and group checks.
    snapshot = object.__new__(InstalledAuthoritySnapshot)
    _SNAPSHOTS[snapshot] = (
        ref(context),
        deepcopy(installation_result),
        deepcopy(replay),
        coverage,
        context_digest(observe(context)),
    )
    _LATEST_SNAPSHOT[context] = snapshot
    return snapshot


def check_snapshot(context, snapshot):
    source = observe(context)
    if type(snapshot) is not InstalledAuthoritySnapshot or snapshot not in _SNAPSHOTS:
        raise ValueError("ledger.trusted_project_installation_required")
    owner, receipt, replay, coverage, identity = _SNAPSHOTS[snapshot]
    if owner() is not context or receipt["accepted"] is not True:
        raise ValueError("ledger.trusted_project_installation_required")
    if identity != context_digest(source):
        raise ValueError("reception.N_stage_pin_changed")
    return source, deepcopy(replay), coverage


def installed_snapshot(context):
    # Serialized receipts never mint capabilities. Return a host-retained object.
    snapshot = _LATEST_SNAPSHOT.get(context)
    if snapshot is not None:
        check_snapshot(context, snapshot)
        return snapshot
    raise ValueError("ledger.trusted_project_installation_required")


def snapshot_high_water(snapshot):
    if type(snapshot) is not InstalledAuthoritySnapshot or snapshot not in _SNAPSHOTS:
        raise ValueError("ledger.trusted_project_installation_required")
    owner = _SNAPSHOTS[snapshot][0]()
    if owner is None:
        raise ValueError("ledger.trusted_project_installation_required")
    _, replay, _ = check_snapshot(owner, snapshot)
    return replay["high_water"]


def host_view(context, snapshot, pin, arm_tag):
    check_snapshot(context, snapshot)
    check_pin(context, pin, arm_tag)
    view = object.__new__(InstalledAuthorityView)
    _VIEWS[view] = (context, snapshot, pin, arm_tag)
    return view


class InstalledAuthorityView:
    def __init__(self):
        raise TypeError("reception.N_caller_ledger_not_authoritative")

    def arm_readout(self, arm_tag=MISSING):
        from .reception_entrypoints_v3 import bound_readout

        return bound_readout(self, arm_tag, "authority.arm_readout")

    def snapshot(self):
        context, snapshot, pin, arm = _VIEWS[self]
        source, replay, _ = check_snapshot(context, snapshot)
        check_pin(context, pin, arm)
        from .authority_ledger import records

        rows = records(source["chain_raw"])
        witness = source["witness"]
        # Diagnostic omission cannot inherit a prefilled caller/book bound.
        # All own-arm formal values come exclusively from bind_formal_n.
        return dict(
            authority_ledger=True,
            genesis=rows[0],
            events=rows[1:],
            recorded_N=replay["book_N"],
            n_high_water=replay["high_water"],
            authority_tip=witness["tip"],
            authority_sequence=witness["sequence"],
            local_attempts_n=None,
            local_counted_n=None,
            cumulative_n=None,
            cumulative_n_lower_bound=None,
            n_complete=False,
            complete_N=None,
            certifiable=False,
            n_ledger_hash=source["chain_sha256"],
            reasons=["ledger_history_incomplete"],
            current_published_anchor=deepcopy(source["anchor"]),
            historical_published_anchor=None,
            is_current_authority=True,
        )

    safe_snapshot = snapshot


def view_binding(view):
    if type(view) is not InstalledAuthorityView or view not in _VIEWS:
        raise ValueError("reception.N_caller_ledger_not_authoritative")
    return _VIEWS[view]


def open_formal_view(*, arm_tag, run_id):
    """Readonly same-operation handshake; no installation or caller source input."""
    from .arm_n import require_label
    from .authority_install_receipt import verify_installation_readonly

    require_label(arm_tag)
    context = open_host_context()
    source = observe(context)
    checked = verify_installation_readonly(
        host_context=context,
        runtime_module_path=source["module_path"],
        installation_receipt_bytes=source.get("installation_receipt_bytes"),
        published_anchor_bytes=source["published_anchor_bytes"],
        acceptance_bytes=source.get("installation_acceptance_bytes"),
    )
    if not checked["accepted"]:
        raise ValueError(checked["reasons"][0])
    snapshot = installed_snapshot(context)
    pin = pin_run(context, arm_tag=arm_tag, run_id=run_id)
    return host_view(context, snapshot, pin, arm_tag)
