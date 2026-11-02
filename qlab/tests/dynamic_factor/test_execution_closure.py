"""Adopted parameter binding and EA.N1 hard gate; no reference/strategy run."""

from copy import deepcopy
from decimal import Decimal, localcontext
import json
from pathlib import Path

import pytest

from qlab.dynamic_factor import execution_closure as closure
from qlab.dynamic_factor.contract import canonical, sha256
from qlab.dynamic_factor.conventions import FIXTURES, load_conventions
from qlab.dynamic_factor.execution_startup import StartupBook
from qlab.dynamic_factor.fee_model import order_cost
from qlab.dynamic_factor.v1_harness import unit_context
from test_execution_startup import book, initial_state, day


def binding():
    return closure.adopted_execution_binding(
        expected_adoption_sha256=closure.ADOPTED_SHA256
    )


@pytest.mark.parametrize(
    "wrong", [None, "", "0" * 64, *closure.DRAFT_SHA256, closure.WITHDRAWN_SHA256]
)
def test_EA_binding_missing_default_wrong_or_draft_refuses_before_reader(
    wrong, record_property
):
    policy = load_conventions()
    reads = []
    with pytest.raises(ValueError, match="formal_closure_adoption_required") as error:
        params = binding()
        params["adoption_sha256"] = wrong
        ledger = StartupBook(
            "CREF-F1-L020",
            "0",
            "SYNTHETIC",
            initial_state(policy),
            unit_context(policy),
            execution_binding=params,
        )
        ledger.execute_open(
            ledger.sessions[1] + "T13:30:00Z", lambda *a: reads.append(a)
        )
    assert reads == []
    record_property(
        "actual",
        json.dumps(
            dict(reason=str(error.value), reader_calls=len(reads), worker_roles=[])
        ),
    )


@pytest.mark.parametrize("kind", ["missing", "changed", "text_changed"])
def test_EA_adopted_bytes_required_not_self_resigned(tmp_path, monkeypatch, kind):
    for name in (closure.NAME, closure.NAME.replace(".json", ".md")):
        (tmp_path / name).write_bytes((closure.ROOT / name).read_bytes())
    if kind == "missing":
        (tmp_path / closure.NAME).unlink()
    else:
        target = (
            closure.NAME if kind == "changed" else closure.NAME.replace(".json", ".md")
        )
        with (tmp_path / target).open("ab") as stream:
            stream.write(b" ")
    monkeypatch.setattr(closure, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="formal_closure_adoption_"):
        binding()


@pytest.mark.parametrize(
    "group,field,value",
    [
        ("N1", "monetary_domain", "float_epsilon"),
        ("N2", "execution_verified", True),
        ("N3", "actual_forward", "sell_before_buy_immediate_cash"),
        ("N4", "first_usable_check", 19),
        ("N4", "first_possible_half", 20),
        ("N4", "solo_inherits_meta_lifecycle", True),
        ("N5", "next_open_reselects_signal", True),
        ("N5", "new_fold_artifact", "reuse_old_pool"),
    ],
)
def test_EA_parameter_drift_cannot_self_resign(group, field, value):
    params = binding()
    params[group][field] = value
    with pytest.raises(ValueError, match="closure_parameters_mismatch"):
        closure.validate_execution_binding(params)


def test_EA_N2_named_diagnostic_book_never_actual_forward_or_merge(record_property):
    ledger = book()
    _, opened, _, _ = day(ledger, 0)
    model = opened["model_receipt"]
    assert model["model"] == "reference_full_fill_at_verified_open"
    assert model["scope"] == "independent_training"
    assert opened["plan_accepted"] is True
    assert opened["modeled_filled_quantity"] == opened["planned_quantity"] == 60
    assert opened["execution_verified"] is model["execution_verified"] is False
    for scope in ("forward", "actual_forward", "merged_books", None):
        with pytest.raises(ValueError, match="diagnostic_book_only"):
            closure.reference_model(binding(), book_id=ledger.book_id, scope=scope)
    other = book("MREF-F2-L020")
    assert other.book_id != ledger.book_id
    assert other.snapshot()["account_state"]["inventory"]["QQQ"] == 0
    assert ledger.snapshot()["complete_account_state"] is None
    record_property("actual", json.dumps(opened, sort_keys=True))


def test_EA_N1_original_seven_fee_lexemes_and_oracle_bytes_unchanged(record_property):
    root = Path(__file__).parent / "fixtures" / "execution-closure-oracle"
    expected = (root / "CF01.expected.canonical.json").read_bytes()
    # Published expected bytes stay literal; this test never writes any oracle.
    assert (
        sha256(expected)
        == "b935b633e29830e30469d9f08bb2666bcb272c2bda2143b7011e7faecaa102b7"
    )
    manifest_raw = (root / "suite-manifest.json").read_bytes()
    assert (
        sha256(manifest_raw)
        == "30acf166a6012c59636f5559d6b6412f4571e0a145c70ec2b78b246d4c1e08d4"
    )
    manifest = json.loads(manifest_raw)
    assert sha256(expected) == manifest["expected_raw_sha256"]
    assert (
        sha256((root / "fixed-order-fee-worksheet.json").read_bytes())
        == manifest["fixed_order_fee_worksheet_sha256"]
    )
    policy = load_conventions()
    assert (
        sha256((FIXTURES / "fee_params_x2.json").read_bytes())
        == policy.document["cost_mapping"]["x2_sha256"]
    )
    params = json.loads((FIXTURES / "fee_params_x2.json").read_bytes())
    worksheet = json.loads((root / "fixed-order-fee-worksheet.json").read_bytes())
    rows = []
    for index, row in enumerate(worksheet["rows"]):
        with localcontext() as ambient:
            ambient.prec = 6
            with closure.fee_context(binding()):
                result = order_cost(
                    params,
                    "sell" if index < 2 else "buy",
                    row["quantity"],
                    float(row["notional"]),
                    0.001,
                    "reference",
                )
            assert ambient.prec == 6
        token = canonical(result["research_cost_usd"]).decode()
        assert token == row["expected_x2_fee"]
        rows.append(
            dict(symbol=row["symbol"], expected=row["expected_x2_fee"], actual=token)
        )
    with closure.fee_context(binding()):
        total = sum((Decimal(row["actual"]) for row in rows), Decimal(0))
        assert total == Decimal(worksheet["total_fee"])
        assert Decimal(3900) + Decimal(worksheet["sell_notional"]) - Decimal(
            worksheet["buy_notional"]
        ) - total == Decimal(worksheet["post_cash"])
        assert Decimal(15000) - total == Decimal(worksheet["post_fee_open_NAV"])
    record_property("EA_N1_actual", json.dumps(rows, sort_keys=True))


def test_EA_N1_startup_fee_does_not_inherit_callers_decimal_context():
    with localcontext() as ambient:
        ambient.prec = 3
        ledger = book()
        _, opened, _, _ = day(ledger, 0)
        assert opened["fee_x2"] == 12.0
        assert ambient.prec == 3
    before = deepcopy(binding())
    assert closure.validate_execution_binding(before) == before


def test_EA_N1_expected_bytes_stay_on_host_not_in_product_package():
    root = Path(__file__).parent / "fixtures" / "execution-closure-oracle"
    assert root.is_dir()
    assert not (FIXTURES / "execution-closure-oracle").exists()
    assert not list(FIXTURES.rglob("CF01.expected.canonical.json"))
