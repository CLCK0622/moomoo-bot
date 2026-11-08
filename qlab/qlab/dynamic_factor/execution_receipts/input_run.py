"""Host-owned preparation request, not a source or runtime approval."""

from copy import deepcopy
import json
from weakref import WeakKeyDictionary

from ..contract import digest
from .input_envelope import prepare_input_envelope, release_identity


_RUNS = WeakKeyDictionary()
_CONTEXTS = WeakKeyDictionary()
_RELEASES = WeakKeyDictionary()


class InputPreparation:
    def __init__(self):
        raise TypeError("execution_input.host_preparation_required")


def prepare(profile, scope, manifest, **expected):
    checked = prepare_input_envelope(profile, scope, manifest, **expected)
    if not checked["prepared"]:
        raise ValueError(checked["reasons"][0])
    # Bootstrap bindings contain wire values, never native objects' custom
    # repr/deepcopy behavior. This serializes metadata, not economic state.
    manifest = json.loads(json.dumps(checked["manifest"], allow_nan=False))
    request = dict(schema="EVO884.ExecutionInputReadRequest/v1", manifest=manifest)
    binding = {
        k: manifest[k]
        for k in ("book_id", "run_id", "member_id", "scope_sha256", "profile_sha256")
    }
    binding.update(request_sha256=digest(request), manifest_sha256=digest(manifest))
    run = object.__new__(InputPreparation)
    _RUNS[run] = (deepcopy(request), deepcopy(binding))
    _CONTEXTS[run] = (deepcopy(profile), deepcopy(scope))
    context = expected.get("release_context")
    raw = release_identity(
        scope,
        policy=expected.get("policy"),
        release_context=context,
        expected_release_identity_bytes=expected.get("expected_release_identity_bytes"),
    )
    _RELEASES[run] = (context, raw, expected.get("policy"))
    if raw is not None:
        # Bootstrap metadata is plain JSON; the native context stays local.
        _CONTEXTS[run] = json.loads(json.dumps([profile, scope], allow_nan=False))
    return run


def read_preparation(run):
    if type(run) is not InputPreparation or run not in _RUNS:
        raise ValueError("execution_input.host_preparation_required")
    return deepcopy(_RUNS[run])


def read_context(run):
    read_preparation(run)
    return deepcopy(_CONTEXTS[run])


def read_release(run):
    read_preparation(run)
    context, raw, policy = _RELEASES[run]
    release_identity(
        _CONTEXTS[run][1],
        policy=policy,
        release_context=context,
        expected_release_identity_bytes=raw,
    )
    return context, raw
