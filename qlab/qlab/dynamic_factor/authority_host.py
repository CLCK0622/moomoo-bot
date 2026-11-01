"""Opaque same-operation host objects; no installation or request-mintable trust.

Production approval-source wiring is deliberately unavailable before the
separately approved deployment/permission prerequisites. Private tests replace
that source adapter; they do not install a deployment or enable this adapter.
"""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from weakref import WeakKeyDictionary

from .contract import digest, sha256


_HOSTS = WeakKeyDictionary()
_SNAPSHOTS = WeakKeyDictionary()
_PINS = WeakKeyDictionary()
_VIEWS = WeakKeyDictionary()


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
        context,
        deepcopy(installation_result),
        deepcopy(replay),
        coverage,
        context_digest(observe(context)),
    )
    return snapshot


def check_snapshot(context, snapshot):
    source = observe(context)
    if type(snapshot) is not InstalledAuthoritySnapshot or snapshot not in _SNAPSHOTS:
        raise ValueError("ledger.trusted_project_installation_required")
    owner, receipt, replay, coverage, identity = _SNAPSHOTS[snapshot]
    if owner is not context or receipt["accepted"] is not True:
        raise ValueError("ledger.trusted_project_installation_required")
    if identity != context_digest(source):
        raise ValueError("reception.N_stage_pin_changed")
    return source, deepcopy(replay), coverage


def installed_snapshot(context):
    # Serialized receipts never mint capabilities. Return a host-retained object.
    for snapshot, record in list(_SNAPSHOTS.items()):
        if record[0] is context:
            check_snapshot(context, snapshot)
            return snapshot
    raise ValueError("ledger.trusted_project_installation_required")


def host_view(context, snapshot, pin, arm_tag):
    check_snapshot(context, snapshot)
    check_pin(context, pin, arm_tag)
    view = object.__new__(InstalledAuthorityView)
    _VIEWS[view] = (context, snapshot, pin, arm_tag)
    return view


class InstalledAuthorityView:
    def __init__(self):
        raise TypeError("reception.N_caller_ledger_not_authoritative")

    def arm_readout(self, arm_tag=None):
        from .reception_entrypoints_v3 import bound_readout

        return bound_readout(self, arm_tag, "authority.arm_readout")

    def snapshot(self):
        context, snapshot, pin, arm = _VIEWS[self]
        source, _, _ = check_snapshot(context, snapshot)
        check_pin(context, pin, arm)
        return deepcopy(source["diagnostic_snapshot"])

    safe_snapshot = snapshot


def view_binding(view):
    if type(view) is not InstalledAuthorityView or view not in _VIEWS:
        raise ValueError("reception.N_caller_ledger_not_authoritative")
    return _VIEWS[view]
