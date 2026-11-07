"""C09 input-manifest preparation, without data reads or source acceptance.

The four slots identify files and original source-receipt bytes. Neither a
matching hash nor a well-formed envelope authenticates that source. This
component is not connected to the legacy worker or formal runtime receiver.
"""

from copy import deepcopy
from datetime import date

from ..contract import digest, is_sha
from ..noncash_v3 import CONSUMERS, assert_consumer_symbols
from ..reference_profile_v301 import validate_solo_profile
from ..reference_v3_scope import validate_scope


SCHEMA = "EVO884.RestrictedExecutionInputManifest/v1"
SLOTS = ("raw", "rights", "adv", "cash")
MANIFEST_KEYS = {
    "schema",
    "book_id",
    "run_id",
    "member_id",
    "scope_sha256",
    "profile_sha256",
    "inputs",
}
SLOT_KEYS = {
    "file",
    "sha256",
    "source_receipt_sha256",
    "requested_dates",
    "requested_consumer",
    "symbols",
}
BINDING_KEYS = (
    "conventions_version",
    "conventions_sha256",
    "prereg_sha256",
    "common_profile_sha256",
)


def _dates(values):
    if type(values) is not list or not values:
        raise ValueError("input_manifest.date_vector_required")
    for value in values:
        try:
            valid = (
                type(value) is str and date.fromisoformat(value).isoformat() == value
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("input_manifest.date_vector_required")
    if values != sorted(set(values)):
        raise ValueError("input_manifest.date_vector_required")


def _prepare(profile, scope, manifest, expected):
    if type(manifest) is not dict or set(manifest) != MANIFEST_KEYS:
        raise ValueError("input_manifest.schema_or_injection_forbidden")
    if manifest["schema"] != SCHEMA:
        raise ValueError("input_manifest.schema_or_injection_forbidden")
    if (
        not is_sha(expected["book_id"])
        or type(expected["run_id"]) is not str
        or not expected["run_id"].strip()
        or not all(is_sha(expected[k]) for k in ("manifest", "scope", "profile"))
    ):
        raise ValueError("input_manifest.host_binding_required")
    if digest(manifest) != expected["manifest"]:
        raise ValueError("input_manifest.manifest_identity_mismatch")
    profile = validate_solo_profile(profile)
    if (
        type(scope) is not dict
        or scope["scope_sha256"] != expected["scope"]
        or profile["profile_sha256"] != expected["profile"]
    ):
        raise ValueError("input_manifest.scope_or_profile_binding_mismatch")
    validate_scope(
        scope,
        dict(train=scope["train"], warmup=scope["warmup"]),
        {key: scope["bindings"][key] for key in BINDING_KEYS},
    )
    if (
        manifest["book_id"] != expected["book_id"]
        or manifest["run_id"] != expected["run_id"]
        or manifest["member_id"] != profile["definition"]["member_id"]
        or manifest["scope_sha256"] != expected["scope"]
        or manifest["profile_sha256"] != expected["profile"]
    ):
        raise ValueError("input_manifest.book_run_or_member_binding_mismatch")
    slots = manifest["inputs"]
    if type(slots) is not dict or set(slots) != set(SLOTS):
        raise ValueError("input_manifest.four_slots_required")
    visible = set(scope["warmup"] + scope["train"])
    for role in SLOTS:
        slot = slots[role]
        if type(slot) is not dict or set(slot) != SLOT_KEYS:
            raise ValueError("input_manifest.slot_schema_or_injection_forbidden")
        if slot["file"] != role + ".json":
            raise ValueError("input_manifest.fixed_filename_required")
        if not all(is_sha(slot[k]) for k in ("sha256", "source_receipt_sha256")):
            raise ValueError("input_manifest.source_receipt_identity_required")
        _dates(slot["requested_dates"])
        if not set(slot["requested_dates"]).issubset(visible):
            raise ValueError("input_manifest.outside_train_warmup_view")
        if (
            type(slot["requested_consumer"]) is not str
            or slot["requested_consumer"] not in CONSUMERS
            or type(slot["symbols"]) is not list
            or not slot["symbols"]
            or any(type(symbol) is not str for symbol in slot["symbols"])
            or len(slot["symbols"]) != len(set(slot["symbols"]))
        ):
            raise ValueError("input_manifest.declared_consumer_or_symbols_invalid")
    # Check every declared batch using the existing B predicate. There is no
    # reader/callback/worker/ledger interface here, even for a valid manifest.
    for role in SLOTS:
        slot = slots[role]
        assert_consumer_symbols(
            scope["guard"], slot["requested_consumer"], slot["symbols"]
        )
    return deepcopy(manifest)


def prepare_input_envelope(
    profile,
    scope,
    manifest,
    *,
    book_id,
    run_id,
    expected_manifest_sha256,
    expected_scope_sha256,
    expected_profile_sha256,
):
    """Structural host preflight only; hashes are expectations, not authority.

    requested_dates/symbols describe metadata, not verified file contents.
    Actual raw prices, ADV, rights and cash still require the formal receiver,
    same-run observed DAG, source capabilities and authorized execution path.
    """
    expected = dict(
        book_id=book_id,
        run_id=run_id,
        manifest=expected_manifest_sha256,
        scope=expected_scope_sha256,
        profile=expected_profile_sha256,
    )
    prepared, reasons = None, []
    try:
        prepared = _prepare(profile, scope, manifest, expected)
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
        reasons = [
            str(exc)
            if isinstance(exc, ValueError)
            else "input_manifest.invalid_declaration"
        ]
    return dict(
        schema="EVO884.PreparedExecutionInputEnvelope/v1",
        phase="input_preparation",
        prepared=prepared is not None,
        manifest=prepared,
        manifest_sha256=digest(prepared) if prepared is not None else None,
        source_acceptance="not_checked",
        accounting_executed=False,
        evidence_accepted=False,
        complete=False,
        runtime_consumable=False,
        certifiable=False,
        reader_calls=0,
        executor_calls=0,
        accessed_roles=[],
        worker_roles=[],
        reasons=reasons,
        outstanding=[
            "C09_formal_source_and_P4_P7_reception",
            "C10_authorized_execution_integration",
        ],
    )
