"""Closed schemas for the v10 consumer boundary (including raw evidence).

Names are exact and case sensitive. A field's value type never decides whether
its name is admissible. Dictionary-valued evidence has its own closed schema;
the only keyed maps are declared security maps, with a frozen key domain.
"""

from .conventions import load_conventions


SCALAR = "scalar"
STRINGS = ("list", "string")
NUMBERS = ("list", SCALAR)
EVIDENCE = "evidence"
NODE = dict.fromkeys(
    (
        "id",
        "field",
        "symbol",
        "date",
        "dependency_start",
        "dependency_end",
        "price_basis",
        "source_csv_sha256",
        "receipt_id",
        "order_id",
        "client_identity",
        "consumer_role",
    ),
    "string",
)
NODE.update(
    parents=STRINGS,
    event_keys=STRINGS,
    value=EVIDENCE,
    entry_on_ex_open=SCALAR,
    amount_verified=SCALAR,
    exdate_verified=SCALAR,
    reconciliation_checkpoint={"verified": SCALAR, "sha256": "string"},
)
LINEAGE = {"dependency_nodes": ("list", NODE), "panel_inputs": ("list", NODE)}
EVENT = dict.fromkeys(
    (
        "symbol",
        "ex_date",
        "pay_date",
        "entry_date",
        "source_sha256",
        "source_mapping_sha256",
        "event_table_sha256",
        "input_version",
        "original_event_source_sha256",
        "simulated_payment_source_sha256",
        "exact_amount_status",
        "ex_date_status",
        "pay_date_status",
        "simulated_cash_credited_at",
    ),
    "string",
)
EVENT.update(
    dict.fromkeys(
        (
            "analytical_D_used",
            "archived_vendor_amount",
            "declared_cash_amount",
            "entitled_integer_shares",
            "simulated_cash_credited_amount",
            "simulated_payment_available",
        ),
        SCALAR,
    )
)
EVENT.update(LINEAGE)
STATE = dict(
    date="string",
    nav=EVIDENCE,
    inventory="security_map",
    cash=EVIDENCE,
    age="security_map",
    retired_ids=STRINGS,
    exit_intents=STRINGS,
    initialization_count=SCALAR,
    **LINEAGE,
)
FOLD = dict(
    fold_id="string",
    dates=STRINGS,
    status="string",
    reasons=STRINGS,
    nav=NUMBERS,
    initialized=SCALAR,
    attempt_id="string",
    attempted=SCALAR,
    retry_of="string",
    inventory="security_map",
    exit_intents=STRINGS,
    budget_state=dict(
        authorization_sha256="string", consumed=SCALAR, seen_result=SCALAR
    ),
    N_receipt=dict(
        attempt_id="string", contribution=SCALAR, N_before=SCALAR, N_after=SCALAR
    ),
    input_state=STATE,
    output_state=STATE,
    input_state_sha256="string",
    output_state_sha256="string",
    **LINEAGE,
)
CONSUMER = dict(
    run_id="string",
    folds=("list", FOLD),
    initial_recorded_N=SCALAR,
    inputs=("list", NODE),
    events=("list", EVENT),
    event=EVENT,
    input_state=STATE,
    output_state=STATE,
    inventory="security_map",
    marks="security_map",
    known_cash=SCALAR,
    as_of="string",
    panel_symbols=STRINGS,
    replacement_symbols=STRINGS,
    restart_capital=SCALAR,
    skip_invalid_folds=SCALAR,
    truncate_sample=SCALAR,
    valid_only=SCALAR,
    **LINEAGE,
)
# B7 and B8 submitted numeric evidence aliases. These do not create graph edges
# or certify a formal value; the exact submitted object remains in the report.
EVIDENCE_KEYS = {
    "value",
    "nav",
    "NAV",
    "cash",
    "alias",
    "nested_numeric",
    "formal_alias",
}


def consumer_schema_v3():
    """Block 4: preserve the original account state and R2 declarations."""
    symbols = set(load_conventions().profile["universe"]) | {"VSNT"}
    rights = dict.fromkeys(symbols | {"child", "LEGACY"}, SCALAR)
    receivables = dict.fromkeys(symbols | {"cash_event", "LEGACY"}, SCALAR)
    state = dict(
        STATE,
        origin="security_map",
        rights=rights,
        receivables=receivables,
        unknown_components=STRINGS,
    )
    fold = dict(FOLD, input_state=state, output_state=state)
    return dict(
        CONSUMER,
        folds=("list", fold),
        input_state=state,
        output_state=state,
        rights=rights,
        receivables=receivables,
    )


def validate_consumer(request, *, schema=CONSUMER):
    """Iteratively validate every depth, without a recursion-limit loophole."""
    securities = set(load_conventions().profile["universe"]) | {
        "B",
        "COR",
        "QQQ",
        "VTI",
        "X",
        "H",
    }
    pending = [(request, schema)]
    while pending:
        value, schema = pending.pop()
        # Null is retained raw missing evidence; the owning business validator
        # determines availability. It cannot hide a nested object or key.
        if value is None:
            continue
        if schema == EVIDENCE:
            if isinstance(value, dict):
                schema = dict.fromkeys(EVIDENCE_KEYS, EVIDENCE)
            elif isinstance(value, list):
                schema = ("list", EVIDENCE)
            else:
                schema = SCALAR
        if isinstance(schema, dict):
            if not isinstance(value, dict) or set(value) - set(schema):
                raise ValueError("data.v10_unknown_lineage_structure")
            if schema is NODE:
                if "parents" in value and (
                    not isinstance(value["parents"], list)
                    or any(not isinstance(p, str) for p in value["parents"])
                ):
                    raise ValueError("data.v10_ancestry_missing")
                if "event_keys" in value and (
                    not isinstance(value["event_keys"], list)
                    or any(not isinstance(p, str) for p in value["event_keys"])
                ):
                    raise ValueError("data.v10_unknown_event_lineage")
            pending.extend((child, schema[key]) for key, child in value.items())
        elif isinstance(schema, tuple):
            if not isinstance(value, list):
                raise ValueError("data.v10_lineage_list_required")
            pending.extend((child, schema[1]) for child in value)
        elif schema == "security_map":
            if not isinstance(value, dict) or set(value) - securities:
                raise ValueError("data.v10_unknown_lineage_structure")
            pending.extend((child, SCALAR) for child in value.values())
        elif schema == "string":
            if not isinstance(value, str):
                raise ValueError("data.v10_lineage_scalar_invalid")
        elif type(value) not in (str, int, float, bool):
            raise ValueError("data.v10_unknown_lineage_structure")
