"""Compile only pre-performance evidence and the shared factor input scope."""

from .contract import digest
from .conventions import load_conventions
from .isolation import checked_manifest, _eligible_day
from .noncash_v3 import checked_guard, assert_consumer_symbols
from .fees import finite


def seal_scope(sealed, train, warmup, policy=None):
    p = policy or load_conventions()
    checked_manifest(sealed, p)
    if (
        p.document["version"] != "v3.0.0"
        or sealed["request"]["role"] != "external_reference_roles"
    ):
        raise ValueError("reference.shared_v3_role_required")
    guard = checked_guard(sealed["request"]["noncash_guard_manifest"], p)
    train, warmup = list(train), list(warmup)
    if (
        not train
        or len(set(warmup + train)) != len(warmup + train)
        or warmup + train != sorted(warmup + train)
    ):
        raise ValueError("reference.only_complete_train_warmup_visible")
    days = {date: _eligible_day(sealed, date, p) for date in train}
    union = sorted({symbol for day in days.values() for symbol in day["eligible"]})
    numeric = {
        date: (days[date]["eligible"] if date in days else union)
        for date in warmup + train
    }
    payload = dict(
        schema="EVO900.reference-shared-scope/v3",
        guard=guard,
        days=days,
        train=train,
        warmup=warmup,
        numeric_symbols=numeric,
        universe=p.profile["universe"],
        all16_recipe_ids=p.document["variance_layers"]["family_definitions"][
            "candidate_members"
        ],
        quarantine_manifest_sha256=sealed["quarantine_manifest_sha256"],
        eligible_set_derivation_sha256=digest(days),
        eligible_set_manifest_sha256=digest(
            {date: day["eligible"] for date, day in days.items()}
        ),
        source_evidence_version_sha256=digest(sealed["request"]["records"]),
        B_catalog_release_sha256=guard["accepted_catalog_sha256"],
        B_derivation_sha256=guard.get("B_derivation_sha256", guard["catalog_sha256"]),
        sealed_at=sealed["request"]["sealed_at"],
        first_performance_at=sealed["request"]["first_performance_at"],
        bindings=p.binding,
        complete=all(day["quantity_state"] == "VERIFIED_GE50" for day in days.values()),
        runtime_consumable=False,
        certifiable=False,
    )
    return dict(payload, scope_sha256=digest(payload))


def compile_panel(scope, reader, policy=None):
    """The numeric callback sees E(t) only; UNKNOWN never becomes a QQQ plan."""
    from .reference_v3_scope import validate_scope

    p = policy or load_conventions()
    validate_scope(
        scope,
        dict(train=scope["train"], warmup=scope["warmup"]),
        {
            k: p.binding[k]
            for k in (
                "conventions_version",
                "conventions_sha256",
                "prereg_sha256",
                "common_profile_sha256",
            )
        },
    )
    guard = checked_guard(scope["guard"], p)
    rows = []
    for date in scope["warmup"] + scope["train"]:
        symbols = scope["numeric_symbols"][date]
        assert_consumer_symbols(guard, "score", symbols, p)
        prices = {s: reader(date, s) for s in symbols}
        if any(not finite(v) or v <= 0 for v in prices.values()):
            raise ValueError("reference.numeric_input_invalid")
        rows.append(dict(date=date, prices=prices))
    return dict(schema="reference.train_panel/v1", rows=rows)


def compile_inputs(scope, price_reader, benchmark_reader, policy=None):
    from .reference_registry_v3 import artifact

    p = policy or load_conventions()
    panel = compile_panel(scope, price_reader, p)
    guard = checked_guard(scope["guard"], p)
    assert_consumer_symbols(guard, "label", ["QQQ"], p)
    rows = []
    for date in scope["warmup"] + scope["train"]:
        value = benchmark_reader(date, "QQQ")
        if not finite(value) or value <= 0:
            raise ValueError("reference.numeric_input_invalid")
        rows.append(dict(date=date, close=value))
    profile = dict(
        schema="reference.profile/v1",
        fold_bindings_raw=artifact("fold-bindings.json")["raw"],
        **{
            k: p.binding[k]
            for k in (
                "conventions_version",
                "conventions_sha256",
                "prereg_sha256",
                "common_profile_sha256",
            )
        },
    )
    return dict(
        panel=panel,
        benchmark=dict(schema="reference.train_benchmark/v1", symbol="QQQ", rows=rows),
        profile=profile,
    )
