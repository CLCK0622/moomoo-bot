"""Host-owned preparation request, not a source or runtime approval."""

from copy import deepcopy
import json
from weakref import WeakKeyDictionary

from ..contract import digest
from .input_envelope import prepare_input_envelope


_RUNS = WeakKeyDictionary()


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
    return run


def read_preparation(run):
    if type(run) is not InputPreparation or run not in _RUNS:
        raise ValueError("execution_input.host_preparation_required")
    return deepcopy(_RUNS[run])
