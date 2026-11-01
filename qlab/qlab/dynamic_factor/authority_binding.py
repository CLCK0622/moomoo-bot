"""Host-held N03 identity bound to a worker's bootstrap, before data readers.

The worker receives expected bindings from the controlled host bootstrap, not
from request JSON. It reads code/schema identities only, never an authority file.
"""

import hashlib
import io
import json
from pathlib import Path
import sys


def _canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def make_worker_binding(context, snapshot, pin, arm_tag):
    from .authority_host import check_snapshot, check_pin, context_digest

    source, _, _ = check_snapshot(context, snapshot)
    body = dict(
        schema="EVO884.AuthorityWorkerBinding/v1",
        host_context_sha256=context_digest(source),
        run_pin_sha256=check_pin(context, pin, arm_tag),
        chain_sha256=source["chain_sha256"],
        witness_sha256=source["witness_sha256"],
        module_realpath=source["module_path"],
        source_manifest=source["reader_sources"],
    )
    return dict(body, binding_sha256=_sha(_canonical(body)))


def verify_worker_binding(supplied, expected):
    if type(expected) is not dict or type(supplied) is not dict or supplied != expected:
        raise ValueError("ledger.worker_authority_unbound")
    fields = {
        "schema",
        "host_context_sha256",
        "run_pin_sha256",
        "chain_sha256",
        "witness_sha256",
        "module_realpath",
        "source_manifest",
        "binding_sha256",
    }
    if (
        set(expected) != fields
        or expected["schema"] != "EVO884.AuthorityWorkerBinding/v1"
    ):
        raise ValueError("ledger.worker_authority_unbound")
    if expected["binding_sha256"] != _sha(
        _canonical(
            {key: value for key, value in expected.items() if key != "binding_sha256"}
        )
    ):
        raise ValueError("ledger.worker_authority_unbound")
    root = Path(__file__).resolve().parent
    if expected["module_realpath"] != str(root / "authority_ledger.py"):
        raise ValueError("ledger.observed_object_drift")
    manifest = expected["source_manifest"]
    if type(manifest) is not dict or not manifest:
        raise ValueError("ledger.worker_authority_unbound")
    for name, wanted in manifest.items():
        if (
            type(name) is not str
            or Path(name).is_absolute()
            or ".." in Path(name).parts
            or type(wanted) is not str
        ):
            raise ValueError("ledger.worker_authority_unbound")
        path = root / name
        if path.is_symlink() or not path.is_file() or _sha(path.read_bytes()) != wanted:
            raise ValueError("ledger.observed_object_drift")


def bind_stdin(expected):
    """Called in the host's bootstrap before importing the original producer."""

    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("ledger.worker_authority_unbound")
            result[key] = value
        return result

    try:
        request = json.loads(sys.stdin.readline(), object_pairs_hook=pairs)
        if type(request) is not dict:
            raise ValueError("ledger.worker_authority_unbound")
        verify_worker_binding(request.get("authority_binding"), expected)
        request = {
            key: value for key, value in request.items() if key != "authority_binding"
        }
        sys.stdin = io.StringIO(json.dumps(request, allow_nan=False) + "\n")
    except (ValueError, TypeError, OSError, KeyError) as exc:
        print(
            json.dumps(
                dict(
                    complete=False,
                    returns=None,
                    sr=None,
                    certifiable=False,
                    runtime_consumable=False,
                    reason=str(exc)
                    if isinstance(exc, ValueError)
                    else "ledger.worker_authority_unbound",
                    reader_calls=0,
                    accessed_roles=[],
                ),
                sort_keys=True,
            )
        )
        raise SystemExit(2)
