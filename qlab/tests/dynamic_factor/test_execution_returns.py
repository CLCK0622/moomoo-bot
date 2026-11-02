"""C07 synthetic 1260-day journal, never a market/reference performance run."""

from copy import deepcopy
from fractions import Fraction
import math
import json

import pytest

from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.execution_accounting import ExecutionAccount, MODEL
from qlab.dynamic_factor.input_disposition import qqq_cash_input
from qlab.dynamic_factor.execution_numbers import amount, decimal_text
from qlab.dynamic_factor.execution_returns import TrainingReturns
from qlab.dynamic_factor.execution_risk_history import RiskHistory
from test_execution_accounting import model_origins
from test_execution_risk_history import history
from test_execution_startup import book as startup


def born(member="CREF-F1-L020"):
    source = startup(member)
    _, args = history(member)
    args["book_id"] = source.book_id
    risk = RiskHistory(**args)
    account = ExecutionAccount(
        risk_book=risk._book,
        expected_snapshot_sha256=risk.snapshot()["snapshot_sha256"],
        execution_binding=args["scope"]["execution_binding"],
        execution_mode="named_training_diagnostic",
    )
    series = TrainingReturns(
        account,
        expected_account_sha256=account.snapshot()["account_sha256"],
        execution_binding=args["scope"]["execution_binding"],
    )
    return account, risk, source, series


@pytest.fixture(scope="module")
def full():
    account, risk, source, series = born()
    for i, date in enumerate(series._dates):
        if i < 3:
            source.prepare_next_open()
            source.execute_open(date + "T14:30:00Z", lambda date, symbol: 100)
            account.lock_startup(
                source, expected_source_sha256=digest(source.snapshot())
            )
            e = dict(
                session=date,
                asof=date + "T14:30:00Z",
                prices={"QQQ": "100"},
                source_sha256=digest(["SYNTHETIC OPEN", i]),
                price_kind="verified_tradable_raw_open",
                origins=model_origins(account),
            )
            account.model_open(e, expected_evidence_sha256=digest(e), model_name=MODEL)
        if date == "2019-09-23":
            event = qqq_cash_input(date, account._state["inventory"]["QQQ"])
            event.update(
                event_id="UNPAID-KNOWN-CASH",
                book_id=account._book_id,
                kind="cash_dividend",
                cash_basis="integer_pre_tax_cash",
            )
            account.record_cash_events(
                [event], session=date, expected_event_sha256=[digest(event)]
            )
        price = "100" if i < 3 else decimal_text(Fraction(10000 + i % 7, 100))
        evidence = dict(
            session=date,
            asof=date + "T20:00:00Z",
            prices={"QQQ": price},
            source_sha256=digest(["SYNTHETIC CLOSE", i]),
            price_kind="verified_raw_close",
            rights_complete=True,
            cash_events_complete=True,
            execution_outcomes={
                key: dict(
                    filled_quantity=row["filled"],
                    status="verified_DAY_closed",
                    source_sha256=digest(["SYNTHETIC DAY", i]),
                )
                for key, row in account.intent()["orders"].items()
                if row["session"] == date
            },
        )
        closed = account.close_session(
            evidence, expected_evidence_sha256=digest(evidence)
        )
        row = closed["receipt"]
        rs = risk.observe_close(
            date,
            row["accounting"],
            row["fills"],
            expected_accounting_sha256=digest(row["accounting"]),
            expected_fills_sha256=digest(row["fills"]),
            cash_proof=closed["cash_proof"],
        )
        assert rs["complete"], rs["reasons"]
        account.bind_next_risk(
            risk._book, expected_snapshot_sha256=rs["snapshot_sha256"]
        )
        if i < 3:
            source.close_session(
                date + "T20:00:00Z",
                100,
                dict(rights_value=0, receivables_value=0, components_known=True),
            )
    benchmark = dict(
        schema="EVO884.BenchmarkDaily/v1",
        dates=list(series._dates),
        values=[0.0] * 1260,
        basis="analytical_TR",
        symbol="QQQ",
        role="B1",
        source_sha256=digest("SYNTHETIC TR NOT ACCOUNT DRIP"),
    )
    return account, series, benchmark, risk


def evaluate(full):
    _, series, benchmark, _ = full
    return series.evaluate(benchmark, expected_benchmark_sha256=digest(benchmark))


def test_A07_A17_A18_complete_1260_E0_first_day_and_terminal_fee(full):
    account, series, _, _ = full
    before = account.export_bytes()
    out = evaluate(full)
    assert out["complete"], out["reasons"]
    assert len(out["dates"]) == len(out["daily_x2"]) == 1260
    closes = account.close_receipts()
    assert out["daily_x2"][0] == float(
        amount(closes[0]["accounting"]["nav"]) / 15000 - 1
    )
    assert out["daily_x2"][0] < 0  # real startup fee, no clock delay
    terminal = out["terminal"]
    assert amount(terminal["fee_x2"]) > 0
    assert amount(terminal["accounting"]["fees_x2"]) == amount(
        closes[-1]["accounting"]["fees_x2"]
    ) + amount(terminal["fee_x2"])
    assert all(q == 0 for q in terminal["accounting"]["inventory"].values())
    assert out["daily_x2"][-1] == float(
        amount(terminal["accounting"]["nav"]) / amount(closes[-2]["accounting"]["nav"])
        - 1
    )
    compound = math.prod(1 + r for r in out["daily_x2"])
    assert math.isclose(
        compound, float(amount(terminal["accounting"]["nav"]) / 15000), rel_tol=1e-12
    )
    assert evaluate(full) == out  # terminal fees exactly once/idempotent
    assert account.export_bytes() == before  # raw source ledger is retained
    assert series.terminal_settlement() == terminal
    assert series.export_bytes() == series.export_bytes()
    assert terminal["settlement_phase"] == "scheduled_historical_terminal_close"
    assert terminal["x1_same_orders_and_quantities"] is True
    assert amount(terminal["accounting"]["cash"]) == amount(
        closes[-1]["accounting"]["cash"]
    ) + amount(terminal["gross_sale_proceeds"]) - amount(terminal["fee_x2"])
    assert set(r["order_id"] for r in terminal["orders"]).isdisjoint(
        account.intent()["orders"]
    )
    assert out["execution_verified"] is False and out["certifiable"] is False
    assert terminal["spendable_account_cash_attested"] is False
    receivable = terminal["accounting"]["receivables"]["UNPAID-KNOWN-CASH"]
    assert amount(receivable["amount"]) > 0 and receivable["payment_state"] == "UNPAID"
    assert amount(terminal["accounting"]["nav"]) == amount(
        terminal["accounting"]["cash"]
    ) + amount(receivable["amount"])
    assert (
        terminal["accounting"]["receivables"] == closes[-1]["accounting"]["receivables"]
    )


def test_A18_active_SR_uses_existing_daily_interface_x1_same_orders(full):
    account, _, _, _ = full
    out = evaluate(full)
    assert out["moments_daily"]["n"] == 1260
    assert out["moments_daily_x1"]["n"] == 1260
    assert out["active_daily_x1"] == out["daily_x1"]
    assert out["annualized_IR_x1"] == math.sqrt(252) * out["moments_daily_x1"]["sharpe"]
    assert out["primary_A_x1"] == 252 * out["moments_daily_x1"]["mean"]
    assert out["active_daily"] == out["daily_x2"]
    assert out["primary_A"] == 252 * out["moments_daily"]["mean"]
    assert out["annualized_IR"] == math.sqrt(252) * out["moments_daily"]["sharpe"]
    assert out["terminal"]["x1_NAV"] != out["terminal"]["accounting"]["nav"]
    assert len(out["terminal"]["orders"]) == sum(
        bool(q)
        for q in account.close_receipts()[-1]["accounting"]["inventory"].values()
    )
    for r in out["terminal"]["orders"]:
        assert amount(r["fee_x2"]) == 2 * amount(r["fee_x1"])


@pytest.mark.parametrize(
    "mutation",
    [
        "omit_first",
        "omit_last",
        "duplicate",
        "NAV",
        "ratio",
        "fee",
        "book",
        "closure",
        "rights",
        "unknown",
        "receivable",
        "x1_orders",
    ],
)
def test_A17_A18_bad_owned_journal_refuses_without_return_patch(
    full, monkeypatch, mutation, record_property
):
    account, series, benchmark, _ = full
    rows = deepcopy(account._closes)
    if mutation == "omit_first":
        rows.pop(0)
    elif mutation == "omit_last":
        rows.pop()
    elif mutation == "duplicate":
        rows[2] = deepcopy(rows[1])
    elif mutation == "NAV":
        rows[1]["previous_close_NAV"] = "1"
    elif mutation == "ratio":
        rows[1]["return_ratio"] = "0"
    elif mutation == "fee":
        rows[1]["accounting"]["fees_x2"] = "0"
    elif mutation == "book":
        rows[1]["book_id"] = digest("other ledger")
    elif mutation == "closure":
        rows[1]["execution_closure_sha256"] = digest("other adoption")
    elif mutation == "rights":
        rows[1]["accounting"]["rights"] = {"UNKNOWN": None}
    elif mutation == "unknown":
        rows[1]["accounting"]["unknown_components"] = ["unknown amount"]
    elif mutation == "receivable":
        rows[1]["accounting"]["receivables"] = {"dividend": {"amount": None}}
    else:
        rows[1]["x1_replay"]["additional_orders"] = ["optimizer"]
    monkeypatch.setattr(account, "_closes", rows)
    out = series.evaluate(benchmark, expected_benchmark_sha256=digest(benchmark))
    assert out["complete"] is False and out["reasons"]
    assert out["daily_x2"] is None and out["moments_daily"] is None
    assert out["retained_close_count"] == len(rows)
    assert account._closes == rows
    record_property(
        "C07_observation",
        json.dumps(
            dict(
                case=mutation,
                complete=out["complete"],
                reasons=out["reasons"],
                formal_returns=out["daily_x2"],
                retained_close_count=out["retained_close_count"],
                boundary="owned_C04_journal_only_no_C09_reader_or_worker",
            )
        ),
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "date",
        "short",
        "NaN",
        "basis",
        "source",
        "extra_strategy_vector",
        "binding",
        "SPY",
        "VTI",
        "role",
    ],
)
def test_A18_benchmark_cannot_repair_missing_strategy_or_source(
    full, mutation, record_property
):
    _, series, baseline, _ = full
    b = deepcopy(baseline)
    if mutation == "date":
        b["dates"] = b["dates"][1:] + ["2999-01-01"]
    elif mutation == "short":
        b["values"].pop()
    elif mutation == "NaN":
        b["values"][5] = None
    elif mutation == "basis":
        b["basis"] = "integer_DRIP"
    elif mutation in {"SPY", "VTI"}:
        b["symbol"] = mutation
    elif mutation == "role":
        b["role"] = "B2"
    elif mutation == "source":
        b["source_sha256"] = None
    elif mutation == "extra_strategy_vector":
        b["strategy_returns"] = [0] * 1260
    out = series.evaluate(
        b,
        expected_benchmark_sha256=digest("wrong")
        if mutation == "binding"
        else digest(b),
    )
    assert not out["complete"] and out["daily_x2"] is None
    assert out["reasons"] == ["returns.exact_source_bound_benchmark_required"]
    record_property(
        "C07_observation",
        json.dumps(
            dict(
                case="benchmark_" + mutation,
                complete=out["complete"],
                reasons=out["reasons"],
                formal_returns=out["daily_x2"],
                retained_close_count=out["retained_close_count"],
                boundary="owned_C04_journal_only_no_C09_reader_or_worker",
            )
        ),
    )


def test_A18_degenerate_SR_null_no_good_subset(full):
    _, series, b, _ = full
    b = dict(b, values=evaluate(full)["daily_x2"])
    out = series.evaluate(b, expected_benchmark_sha256=digest(b))
    assert not out["complete"] and out["moments_daily"] is None
    assert out["reasons"] == ["dsr.zero_return_variance"]


def test_A17_no_caller_terminal_or_return_vector():
    account, _, _, series = born()
    with pytest.raises(TypeError):
        TrainingReturns(
            account,
            expected_account_sha256=account.snapshot()["account_sha256"],
            execution_binding=account._binding,
            terminal_session="2099-01-01",
        )
    with pytest.raises(ValueError, match="owned_C04"):
        TrainingReturns(
            {"returns": [0] * 1260},
            expected_account_sha256=digest({}),
            execution_binding=account._binding,
        )
    out = series.evaluate({}, expected_benchmark_sha256=digest({}))
    assert not out["complete"] and out["retained_close_count"] == 0
    assert out["reasons"] == ["returns.exact_1260_dates_required_no_omission"]


def test_A17_terminal_known_receivable_preserved_not_credited(full, monkeypatch):
    account, series, _, _ = full
    rows = deepcopy(account._closes)
    # Injected corruption must fail the owned journal's accounting, not silently
    # erase the receivable. Production cash events require a host CashProof.
    rows[-1]["accounting"]["receivables"] = {"unpaid": {"amount": "10"}}
    monkeypatch.setattr(account, "_closes", rows)
    out = evaluate(full)
    assert not out["complete"] and out["daily_x2"] is None
    assert out["reasons"] == ["returns.account_changed_after_final_close"]
    assert account._closes[-1]["accounting"]["receivables"]["unpaid"]["amount"] == "10"


def test_A14_terminal_missing_fee_rejects_and_keeps_original_book(full, monkeypatch):
    account, series, _, _ = full
    original = account.export_bytes()
    monkeypatch.setattr(series, "_terminal", None)

    def missing(*args, **kwargs):
        raise ValueError("fee.parameters_missing")

    monkeypatch.setattr(account, "_fee", missing)
    out = evaluate(full)
    assert not out["complete"] and out["daily_x2"] is None
    assert out["reasons"] == ["fee.parameters_missing"]
    assert account.export_bytes() == original


def test_A17_fixed_training_boundary_all1260_not_maturity_end(full):
    account, series, _, risk = full
    assert account.close_receipts()[-1]["session"] == series.plan()["terminal_session"]
    fold = account._policy.fold_manifest()["folds"][0]
    assert series.plan()["terminal_session"] == fold["history_end"]
    assert series.plan()["terminal_session"] > fold["train_end"]
    date = account._policy.calendar[
        account._policy.calendar.index(fold["history_end"]) + 1
    ]
    row = deepcopy(account.close_receipts()[-1]["accounting"])
    row["asof"] = date + "T20:00:00Z"
    with pytest.raises(ValueError, match="training_book_cannot_enter_other_fold"):
        risk.observe_close(
            date,
            row,
            [],
            expected_accounting_sha256=digest(row),
            expected_fills_sha256=digest([]),
        )


def test_source_binding_before_startup_no_late_series(full):
    account, _, _, _ = full
    with pytest.raises(ValueError, match="preexecution_training_binding"):
        TrainingReturns(
            account,
            expected_account_sha256=account.snapshot()["account_sha256"],
            execution_binding=account._binding,
        )


def test_A17_real_unknown_right_keeps_journal_R2(record_property):
    account, _, _, series = born()
    event = dict(kind="split", ratio=None, source_sha256=digest("SYNTHETIC UNKNOWN"))
    account.record_unknown_right(event, expected_event_sha256=digest(event))
    before = account.export_bytes()
    out = series.evaluate({}, expected_benchmark_sha256=digest({}))
    assert not out["complete"] and out["daily_x2"] is None and out["terminal"] is None
    assert out["reasons"] == ["returns.R2_incomplete_account"]
    assert account.export_bytes() == before
    assert account.snapshot()["retained_state"]["rights"][digest(event)] == event
    record_property(
        "C07_observation",
        json.dumps(
            dict(
                case="real_unknown_right",
                complete=out["complete"],
                reasons=out["reasons"],
                formal_returns=out["daily_x2"],
                boundary="owned_C04_journal_only_no_C09_reader_or_worker",
            )
        ),
    )


@pytest.mark.parametrize("binding_kind", ["missing", "draft", "withdrawn", "changed"])
def test_C07_requires_same_formal_adoption_no_default(binding_kind):
    from qlab.dynamic_factor.execution_closure import DRAFT_SHA256, WITHDRAWN_SHA256

    account, _, _, _ = born()
    binding = deepcopy(account._binding)
    if binding_kind == "missing":
        binding = None
    elif binding_kind == "draft":
        binding["adoption_sha256"] = DRAFT_SHA256[0]
    elif binding_kind == "withdrawn":
        binding["adoption_sha256"] = WITHDRAWN_SHA256
    else:
        binding["N5"]["close_order"].reverse()
    with pytest.raises(ValueError, match=r"execution\."):
        TrainingReturns(
            account,
            expected_account_sha256=account.snapshot()["account_sha256"],
            execution_binding=binding,
        )


def test_A18_all_frozen_folds_have_exact1260_shared_dates():
    from qlab.dynamic_factor.fold_split import train_dates
    from qlab.dynamic_factor.conventions import load_conventions

    policy = load_conventions()
    folds = policy.fold_manifest()["folds"]
    assert len(folds) == 77
    for fold, original in zip(folds, policy.date_manifest["folds"]):
        dates = train_dates(policy.calendar, fold)
        assert len(dates) == 1260
        assert (dates[0], dates[-1]) == tuple(original["train_dates_inclusive"])
        assert dates[-1] == fold["history_end"]


def test_four_references_bind_same_rules_but_keep_separate_books():
    from qlab.dynamic_factor.reference_definition_v301 import reference_definitions

    books = [born(d["member_id"])[3] for d in reference_definitions()]
    plans = [b.plan() for b in books]
    assert len({p["book_id"] for p in plans}) == 4
    assert len({p["execution_closure_sha256"] for p in plans}) == 1
    assert len({p["clock_ruling_sha256"] for p in plans}) == 1
    assert len({p["train_calendar_sha256"] for p in plans}) == 1
