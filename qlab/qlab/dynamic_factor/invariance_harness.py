"""Implementation-level VTI byte-replacement probe, synthetic mechanisms only.

No reference return generation, strategy backtest, actual eligibility acceptance
or account state is fabricated. Output SHA cover the seven owned interfaces;
S2's still-pending refusal is an output, not a valid empty pool.
"""

from dataclasses import asdict

from .contract import canonical, digest, sha256
from .conventions import load_conventions
from .execution import calibrate_gain, initial_build_turnover_check, lock_startup_intent
from .folds import FitReceipt, _features, _run_walk_forward_unbound
from .harness_helpers import fixture_ledger
from .input_disposition import qqq_cash_input
from .ledger import AttemptLedger
from .pending import pool_admission_check
from .reference_boundary import run_isolated
from .scope_reader import read_strategy_inputs
from .v1_harness import producer_fixture, unit_context
from .valuation import benchmark_valuation, integer_cash_valuation
from .b2_inputs import b2_input_readout


class UnitMiner:
    def mine(self, train):
        return [{"SYNTHETIC_UNIT_SPEC": True}]


class UnitModel:
    def predict(self, test):
        return [0.0 for _ in test]


class UnitFitter:
    def fit(self, train, proposals):
        return FitReceipt(
            UnitModel(),
            tuple(r.date for r in train),
            digest([asdict(r) for r in train]),
            digest(proposals),
        )


def probe(workdir, policy=None):
    policy = policy or load_conventions()
    root = workdir / "vti-disjoint-inputs"
    reference = producer_fixture(root, policy)
    dates = list(policy.calendar[:8])
    raw = canonical(
        {"symbol": "QQQ", "rows": [{"date": d, "close": 100} for d in dates]}
    )
    (root / "QQQ.json").write_bytes(raw)
    binding = {"QQQ": dict(symbol="QQQ", file="QQQ.json", sha256=sha256(raw))}
    VTI = root / "VTI.json"
    outputs = []
    B2 = []
    input_sha = []
    diagnostics = []
    for index, (value, snapshot) in enumerate(
        [(99, True), (777, True), (777, False), (None, False)]
    ):
        if value is None:
            VTI.unlink()
        else:
            VTI.write_bytes(
                canonical(
                    {
                        "symbol": "VTI",
                        "rows": [{"date": d, "close": value} for d in dates],
                    }
                )
            )
        input_sha.append(sha256(VTI.read_bytes()) if value is not None else None)
        data = {
            role: read_strategy_inputs(root, binding, dates, role=role, policy=policy)
            for role in (
                "features",
                "qqq_labels",
                "calibration",
                "admission",
                "reference",
                "holdings_cash",
                "orders",
            )
        }
        features = [
            _features({"features": {"QQQ_close": r["close"]}})
            for r in data["features"]["QQQ"]
        ]
        manifest = dict(
            calendar=dates,
            label_horizon=1,
            embargo=0,
            folds=[
                dict(
                    fold_id="UNIT",
                    train_start=dates[0],
                    train_end=dates[1],
                    test_start=dates[3],
                    test_end=dates[4],
                )
            ],
        )
        rows = [
            dict(
                date=d,
                features={"QQQ_close": 100},
                target=0.0,
                label_end=dates[min(i + 1, len(dates) - 1)],
            )
            for i, d in enumerate(dates)
        ]
        labels = _run_walk_forward_unbound(
            manifest,
            rows,
            miner_factory=lambda ctx: UnitMiner(),
            fitter_factory=lambda ctx: UnitFitter(),
            ledger=AttemptLedger(workdir / f"label-unit-{index}.sqlite"),
            run_id="SYNTHETIC_UNIT",
        )
        context = unit_context(policy)
        d = context["train_calendar"][0]
        family = policy.document["variance_layers"]["family_definitions"][
            "candidate_members"
        ]
        calibration_rows = [
            dict(
                date=d,
                symbol=f"UNIT{i:03}",
                label_entry=context["train_calendar"][1],
                label_end=context["train_calendar"][11],
                stock_h10=0.02 + i * 0.001,
                qqq_h10=0.01,
                ranks={m: (i + 0.5) / 50 for m in family},
            )
            for i in range(50)
        ]
        calibration = calibrate_gain(
            calibration_rows, {d}, conventions=policy, context=context
        )
        admission = pool_admission_check(
            {"candidate_id": "UNIT"},
            conventions=policy,
            ledger=fixture_ledger(workdir / f"admission-unit-{index}.sqlite", policy),
        )
        ref = run_isolated(root, reference)
        assert ref["returns"] is None
        cash = integer_cash_valuation(
            dict(
                known_cash=100,
                as_of="2022-12-20",
                inventory={"QQQ": 2},
                marks={"QQQ": 100},
                events=[qqq_cash_input("2022-12-19", 2)],
            ),
            conventions=policy,
        )
        ledger = AttemptLedger(workdir / f"orders-unit-{index}.sqlite")
        sessions = list(policy.calendar[100:110])
        close = sessions[0] + "T16:00:00"
        intent = lock_startup_intent(
            0,
            15000,
            {},
            close,
            policy=policy,
            ledger=ledger,
            start_id="UNIT",
            scope_id="SYNTHETIC_UNIT",
        )
        order = initial_build_turnover_check(
            dict(
                intent=intent,
                context=context,
                cash=15000,
                previous_close=close,
                reference_sessions=sessions,
                raw_open_prices={"QQQ": 100},
                open_timestamp=sessions[1] + "T09:30:00",
                sell_date=sessions[1],
                rate_basis="research_restored",
                start_id="UNIT",
            ),
            conventions=policy,
            ledger=ledger,
        )
        assert cash["ok"] and order["ok"] and not admission["ok"]
        artifacts = dict(
            features=features,
            qqq_labels=labels["metrics"]["folds"],
            calibration=calibration,
            admission=admission["metrics"],
            reference=ref,
            holdings_cash=cash["metrics"],
            orders=order["metrics"],
        )
        outputs.append({role: digest(artifact) for role, artifact in artifacts.items()})
        b2 = benchmark_valuation(
            dict(
                symbol="VTI",
                price_basis="raw_close",
                raw_source_sha256=input_sha[-1],
                prices=[dict(date=d, close=value) for d in dates],
            ),
            conventions=policy,
        )
        assert b2["metrics"]["formal_return"] is None
        B2.append(b2["input_sha256"])
        diagnostics.append(
            b2_input_readout(
                dict(
                    include_issuer_snapshot_fields=snapshot,
                    price_basis="raw_close",
                    raw_source_sha256=digest("SYNTHETIC_UNIT_FLAT_VTI_PRICES"),
                    prices=[dict(date=d, close=100) for d in policy.calendar],
                ),
                conventions=policy,
            )
        )
    assert input_sha[0] != input_sha[1] and B2[0] != B2[1] and outputs[0] == outputs[1]
    on, off = diagnostics[1:3]
    assert on["ok"] and off["ok"] and outputs[1] == outputs[2]
    changed = []
    for left, right in zip(on["metrics"]["daily"], off["metrics"]["daily"]):
        assert left["date"] == right["date"] and left["raw_close"] == right["raw_close"]
        assert left["raw_price_return"] == right["raw_price_return"]
        if left["daily_total_return"] != right["daily_total_return"]:
            assert right["daily_total_return"] is None
            changed.append(left["date"])
    assert changed == ["2013-12-20", "2014-03-25"]
    assert outputs[1] == outputs[3] and input_sha[3] is None
    return dict(
        case_id="scope.VTI_file_replacement_output_SHA_invariant",
        status="PASS",
        scope="SYNTHETIC_UNIT_INTERFACES_NOT_ACTUAL_PERFORMANCE",
        VTI_source_sha256=input_sha,
        B2_receipt_input_sha256=B2,
        output_sha256_before=outputs[0],
        output_sha256_after=outputs[1],
        actual_reference_run_id=None,
        actual_reference_returns=None,
        main_market_file_bindings=binding,
        reference_file_bindings=reference["inputs"],
        snapshot_switch_receipt=dict(
            case_id="scope.B2_snapshot_fields_disabled_strategy_SHA_invariant",
            status="PASS",
            scope="SYNTHETIC_UNIT_INTERFACES_NOT_ACTUAL_PERFORMANCE",
            strategy_output_sha256_enabled=outputs[1],
            strategy_output_sha256_disabled=outputs[2],
            B2_enabled_receipt_sha256=digest(on),
            B2_disabled_receipt_sha256=digest(off),
            B2_changed_daily_TR_dates=changed,
            raw_close_date_and_price_returns_unchanged=True,
            B2_event_source_provenance=on["input_sha256"],
            no_actual_strategy_or_reference_rerun=True,
        ),
        B2_missing_file_receipt=dict(
            case_id="scope.B2_file_missing_strategy_SHA_invariant",
            status="PASS",
            scope="SYNTHETIC_UNIT_INTERFACES_NOT_ACTUAL_PERFORMANCE",
            strategy_output_sha256_present=outputs[1],
            strategy_output_sha256_absent=outputs[3],
            B2_formal_return=None,
            VTI_source_sha256=None,
        ),
        evidence_scope="Owned fixed interfaces and synthetic caller inputs; actual runtime DAG and market-source acceptance remain separate.",
    )
