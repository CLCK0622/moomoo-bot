import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest

from qlab.dynamic_factor.contract import digest
from qlab.shadow15k import ShadowLedger
from qlab.shadow15k.harness import FIXTURE, POLICY_TOOLS, fixture_fees, run

DATA = json.loads(FIXTURE.read_bytes())


@pytest.fixture
def ledger(tmp_path):
    return ShadowLedger(tmp_path / "shadow15k", DATA["genesis"], fixture_fees("x1"))


def intent(
    iid="i",
    *,
    side="BUY",
    qty=100,
    symbol="X",
    date="2026-12-31",
    oid="o",
    protective=False,
):
    return dict(
        intent_id=iid,
        decision_ts=DATA["decision_ts"],
        input_hash=digest({"fixture": True}),
        orders=[
            dict(
                order_id=oid,
                symbol=symbol,
                side=side,
                planned_qty=qty,
                trade_date=date,
                protective=protective,
            )
        ],
    )


def receipt(
    rid="r",
    *,
    qty=100,
    gross="5000",
    fee_known=True,
    status="filled",
    oid="o",
    at="2026-12-31T15:00:00Z",
):
    return dict(
        receipt_id=rid,
        receipt_ts=at,
        orders=[
            dict(
                order_id=oid,
                confirmed_qty=qty,
                gross_usd=gross,
                fee_known=fee_known,
                status=status,
            )
        ],
    )


def marks(prices=None, *, basis="cash_bid_ask", at="2027-01-04T21:00:00Z"):
    return dict(
        as_of=at, price_basis=basis, prices={"X": "50"} if prices is None else prices
    )


def read(ledger, **kwargs):
    return ledger.readout(marks(**kwargs))["metrics"]


def test_fixed_harness_two_fresh_directories_is_byte_deterministic(tmp_path):
    first, second = run(tmp_path / "run1"), run(tmp_path / "run2")
    assert first == second
    assert first["cases_passed"] == 9
    assert {c["case_id"] for c in first["cases"]} >= {
        "paper.partial_is_incomplete",
        "paper.failed_hedge_retains_risk",
        "nav.missing_mark_is_unknown",
        "intent.retry_requires_reconcile",
        "cost.cash_vs_reference_no_double",
    }
    assert (
        first["network_attempts"]
        == first["strategy_backtests"]
        == first["forward_samples"]
        == 0
    )
    assert not first["certifiable"]
    assert len(first["input_sha256"]) == len(first["source_sha256"]) == 64
    with pytest.raises(ValueError, match="empty_harness"):
        run(tmp_path / "run1")


def test_intent_is_not_a_fill(ledger):
    assert ledger.register_intent(intent())["ok"]
    r = read(ledger)
    assert r["inventory"] == {}
    assert r["cash"] is None and r["nav"] is None
    assert r["last_known_cash"] == "15000"
    assert r["reconciliation_required"]
    assert not r["execution_verified"] and not r["execution_complete"]


def test_partial_fills_charge_once_then_increment_and_restart(ledger):
    assert ledger.register_intent(intent())["ok"]
    assert ledger.record_receipt(
        "i", receipt("part", qty=60, gross="3000", status="partial")
    )["ok"]
    a = read(ledger)
    assert a["inventory"] == {"X": 60}
    assert a["residual_qty"] == {"i": {"o": 40}}
    assert a["reconciliation_required"]
    reopened = ShadowLedger(ledger.root, DATA["genesis"], fixture_fees("x1"))
    assert reopened.record_receipt("i", receipt("finish"))["ok"]
    b = read(reopened)
    assert b["execution_complete"] and not b["execution_verified"]
    assert b["reconciliation_required"] is False
    assert Decimal(b["fees"]) == Decimal("1.406427")
    assert Decimal(b["postings"][1]["fee_delta"]) == Decimal("0.1309308")
    assert sum(Decimal(p["fee_delta"]) for p in b["postings"]) == Decimal(b["fees"])
    assert Decimal(b["gross_pnl"]) - Decimal(b["fees"]) == Decimal(b["net_pnl"])
    assert Decimal(b["nav"]) == Decimal("15000") - Decimal("1.406427")
    assert b == read(ShadowLedger(ledger.root, DATA["genesis"], fixture_fees("x1")))


@pytest.mark.parametrize("unknown_qty", [True, False])
def test_unknown_quantity_or_fees_freeze_then_explicit_cumulative_receipt_resolves(
    ledger, unknown_qty
):
    ledger.register_intent(intent())
    r = receipt(
        "unknown",
        qty=None if unknown_qty else 60,
        gross=None if unknown_qty else "3000",
        fee_known=False,
        status="unknown" if unknown_qty else "partial",
    )
    assert ledger.record_receipt("i", r)["ok"]
    before = read(ledger)
    assert before["cash"] is None and before["fees"] is None and before["nav"] is None
    assert before["reconciliation_required"]
    assert not ledger.register_intent(intent("new", oid="o2"))["ok"]
    assert ledger.record_receipt("i", receipt("resolved"))["ok"]
    after = read(ledger)
    assert after["inventory"] == {"X": 100}
    assert Decimal(after["fees"]) == Decimal("1.406427")
    assert not after["reconciliation_required"]
    assert ledger.register_intent(intent("new", oid="o2"))["ok"]


def test_uncertain_update_retains_prior_confirmed_risk_and_charges(ledger):
    ledger.register_intent(intent())
    ledger.record_receipt("i", receipt("part", qty=60, gross="3000", status="partial"))
    known = read(ledger)
    assert ledger.record_receipt(
        "i", receipt("lost", qty=None, gross=None, fee_known=False, status="unknown")
    )["ok"]
    r = read(ledger)
    assert r["inventory"] == {"X": 60} and r["fills"][0]["last_known_qty"] == 60
    assert (
        r["fills"][0]["confirmed_qty"] is None and r["residual_qty"]["i"]["o"] is None
    )
    assert r["known_fees"] == known["fees"] and r["cash"] is None
    assert ledger.record_receipt("i", receipt("recover"))["ok"]
    assert read(ledger)["inventory"] == {"X": 100}
    assert Decimal(read(ledger)["fees"]) == Decimal("1.406427")


def test_cancelled_partial_preserves_residual_and_does_not_claim_complete_execution(
    ledger,
):
    ledger.register_intent(intent())
    assert ledger.record_receipt(
        "i", receipt("cancel", qty=60, gross="3000", status="cancelled")
    )["ok"]
    r = read(ledger)
    assert not r["reconciliation_required"] and not r["execution_complete"]
    assert r["residual_qty"]["i"]["o"] == 40
    assert r["inventory"] == {"X": 60}


def test_duplicate_intent_and_receipt_across_threads_are_exactly_once(ledger):
    with ThreadPoolExecutor(max_workers=8) as pool:
        intents = list(pool.map(lambda _: ledger.register_intent(intent()), range(16)))
        receipts = list(
            pool.map(lambda _: ledger.record_receipt("i", receipt()), range(16))
        )
    assert all(r["ok"] for r in intents + receipts)
    assert sum(r["metrics"]["registered"] for r in intents) == 1
    assert sum(r["metrics"]["registered"] for r in receipts) == 1
    r = read(ledger)
    assert r["inventory"] == {"X": 100} and r["event_count"] == 2
    assert Decimal(r["cash"]) == Decimal("9998.593573")


def test_competing_new_intents_are_serialized_by_reconciliation(ledger):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda i: ledger.register_intent(intent(str(i), oid=str(i))), range(8)
            )
        )
    assert sum(r["ok"] for r in results) == 1
    assert read(ledger)["event_count"] == 1


def test_id_conflicts_and_order_reuse_cannot_change_accounting(ledger):
    ledger.register_intent(intent())
    a = read(ledger)
    assert not ledger.register_intent(intent(qty=99))["ok"]
    assert read(ledger) == a
    ledger.record_receipt("i", receipt())
    b = read(ledger)
    assert not ledger.record_receipt("i", receipt(gross="4999"))["ok"]
    assert not ledger.record_receipt("i", receipt("other", gross="4999"))["ok"]
    assert not ledger.register_intent(intent("reuse"))["ok"]
    assert read(ledger) == b


@pytest.mark.parametrize(
    "changes",
    [
        {"qty": 1.5},
        {"qty": True},
        {"qty": -1},
        {"qty": 101, "gross": "5050"},
        {"qty": 0},
        {"gross": "0"},
        {"gross": "-1"},
        {"gross": "NaN"},
        {"gross": "Infinity"},
        {"gross": float("nan")},
        {"fee_known": None},
        {"qty": None},
        {"status": "failed"},
        {"status": "partial"},
        {"at": "2026-12-01T00:00:00Z"},
        {"at": "2026-12-31T15:00:00"},
    ],
)
def test_invalid_receipt_rolls_back_all_changes(ledger, changes):
    ledger.register_intent(intent())
    before = read(ledger)
    assert not ledger.record_receipt("i", receipt(**changes))["ok"]
    assert read(ledger) == before


@pytest.mark.parametrize("price", [None, "0", "-1", "NaN", "Infinity", True])
def test_invalid_or_missing_mark_never_carries_prior_price(ledger, price):
    ledger.register_intent(intent())
    ledger.record_receipt("i", receipt())
    assert read(ledger)["valuation_complete"]
    r = read(ledger, prices={"X": price})
    assert r["missing_marks"] == ["X"]
    assert r["nav"] is r["gross_pnl"] is r["net_pnl"] is r["sharpe"] is None
    assert not r["valuation_complete"] and not r["sharpe_available"]


def test_wrong_price_basis_or_early_timestamp_refuses_valuation(ledger):
    ledger.register_intent(intent())
    ledger.record_receipt("i", receipt())
    for m in [marks(basis="reference"), marks(at="2026-12-30T23:00:00Z")]:
        r = ledger.readout(m)
        assert "nav.invalid_marks" in r["reasons"]
        assert r["metrics"]["nav"] is None


def test_sell_and_cash_constraints_are_atomic_including_fees(ledger):
    ledger.register_intent(intent(side="SELL"))
    before = read(ledger)
    assert (
        "short_inventory_forbidden" in ledger.record_receipt("i", receipt())["reasons"]
    )
    assert read(ledger) == before
    # A different isolated book checks fees cannot make an otherwise affordable buy overdraw.
    other = ShadowLedger(
        ledger.root.parent / "other" / "shadow15k", DATA["genesis"], fixture_fees("x1")
    )
    other.register_intent(intent())
    assert (
        "cash_insufficient_including_fees"
        in other.record_receipt("i", receipt(gross="15000"))["reasons"]
    )
    assert read(other)["inventory"] == {}


def test_second_leg_failure_rolls_back_first_leg(ledger):
    request = intent(qty=100)
    request["orders"].append(dict(request["orders"][0], order_id="second", symbol="Y"))
    ledger.register_intent(request)
    r = receipt()
    r["orders"].append(dict(r["orders"][0], order_id="second", confirmed_qty=1.5))
    before = read(ledger)
    assert not ledger.record_receipt("i", r)["ok"]
    assert read(ledger) == before


def test_page_seven_fields_and_hashes_are_complete(ledger):
    value = ledger.readout(marks())
    r = value["metrics"]
    assert (
        set(
            "candidate_id version decision_ts input_hash price_basis reading_kind gross_pnl fees net_pnl cash inventory_value missing_marks execution_verified sharpe_available metric_unavailable_reason cumulative_n n_ledger_hash intent_id fills residual_qty reconciliation_required".split()
        )
        <= r.keys()
    )
    assert r["cumulative_n"] is r["n_ledger_hash"] is r["sharpe"] is None
    assert len(value["input_sha256"]) == len(value["source_sha256"]) == 64
    assert value["assumptions"] and not value["certifiable"]


@pytest.mark.parametrize("tool", POLICY_TOOLS)
def test_every_meta_strategy_interface_refuses_even_if_request_claims_frozen(tool):
    for request in (
        {},
        {
            "frozen": True,
            "verified": True,
            "version": "v0.2",
            "parameters": {"weight": 1},
        },
    ):
        r = tool(request)
        assert not r["ok"] and not r["certifiable"]
        assert r["reasons"] == ["prereg_pending_v0.2"]
        assert r["metrics"] == {"allowed": False, "parameters": None}


@pytest.mark.parametrize(
    "component",
    [
        "llm_paper",
        "opend_snapshot",
        "content",
        "out",
        "launchd",
        "evo353",
        "evo774",
        "evo844",
        "evo851",
    ],
)
def test_forbidden_physical_namespaces_are_refused_before_creation(tmp_path, component):
    root = tmp_path / component / "shadow15k"
    with pytest.raises(ValueError, match="dedicated_shadow15k"):
        ShadowLedger(root, DATA["genesis"], fixture_fees("x1"))
    assert not root.exists()


def test_foreign_files_and_database_symlinks_are_not_touched(tmp_path):
    root = tmp_path / "shadow15k"
    root.mkdir()
    sentinel = root / "old.json"
    sentinel.write_text("unchanged")
    with pytest.raises(ValueError, match="foreign_files"):
        ShadowLedger(root, DATA["genesis"], fixture_fees("x1"))
    assert (
        sentinel.read_text() == "unchanged" and not (root / "ledger.sqlite3").exists()
    )
    sentinel.unlink()
    outside = tmp_path / "outside"
    outside.write_text("unchanged")
    (root / "ledger.sqlite3").symlink_to(outside)
    with pytest.raises(ValueError):
        ShadowLedger(root, DATA["genesis"], fixture_fees("x1"))
    assert outside.read_text() == "unchanged"


@pytest.mark.parametrize(
    "changes",
    [
        {"initial_cash": "100000"},
        {"mode": "REAL"},
        {"namespace": "llm_paper"},
        {"price_basis": "unknown"},
    ],
)
def test_invalid_genesis_never_creates_root(tmp_path, changes):
    root = tmp_path / "shadow15k"
    with pytest.raises(ValueError):
        ShadowLedger(root, dict(DATA["genesis"], **changes), fixture_fees("x1"))
    assert not root.exists()


def test_reopening_with_new_scenario_or_identity_refused_without_modifying_db(ledger):
    before = ledger.path.read_bytes()
    for g, f in [
        (DATA["genesis"], fixture_fees("x2")),
        (dict(DATA["genesis"], version="changed"), fixture_fees("x1")),
    ]:
        with pytest.raises(ValueError, match="genesis_or_fee"):
            ShadowLedger(ledger.root, g, f)
    assert ledger.path.read_bytes() == before


def test_fee_binding_checks_raw_bytes(tmp_path):
    from qlab.dynamic_factor.fees import FIXTURES
    from qlab.shadow15k import FeeBook
    from qlab.shadow15k.harness import FEE_SHAS

    changed = tmp_path / "params.json"
    changed.write_bytes((FIXTURES / "fee_params_x1.json").read_bytes() + b" ")
    with pytest.raises(ValueError, match="fee_file_sha_mismatch"):
        FeeBook(
            changed,
            FIXTURES / "fee_schedule.json",
            params_sha256=FEE_SHAS["x1"],
            schedule_sha256=FEE_SHAS["schedule"],
        )


def test_fee_dates_must_be_explicit_and_covered():
    fees = fixture_fees("x1")
    with pytest.raises(ValueError, match="uncovered"):
        fees.cumulative(
            qty=1,
            notional="50",
            side="SELL",
            trade_date="2026-09-30",
            price_basis="reference",
        )


def test_fee_line_min_caps_and_x2_stress():
    one, two = fixture_fees("x1"), fixture_fees("x2")
    for qty, notional in [(1, "0.1"), (100, "5000"), (100000, "100000")]:
        a = one.cumulative(
            qty=qty,
            notional=notional,
            side="SELL",
            trade_date="2027-01-01",
            price_basis="reference",
        )
        b = two.cumulative(
            qty=qty,
            notional=notional,
            side="SELL",
            trade_date="2027-01-01",
            price_basis="reference",
        )
        for key in set(a) - {"taf_rate_field"}:
            assert Decimal(b[key]) == 2 * Decimal(a[key])
        assert Decimal(a["settlement"]) <= Decimal(notional) * Decimal(".01")
        assert Decimal(".01") <= Decimal(a["taf"]) <= Decimal("9.79")
    zero = one.cumulative(
        qty=0,
        notional="0",
        side="SELL",
        trade_date="2027-01-01",
        price_basis="reference",
    )
    assert all(Decimal(v) == 0 for k, v in zero.items() if k != "taf_rate_field")


@pytest.mark.parametrize("scenario", ["x1", "x2"])
@pytest.mark.parametrize("basis", ["reference", "cash_bid_ask"])
def test_roundtrip_crosscheck_with_pr10_fee_frontier(scenario, basis):
    from qlab.dynamic_factor.fees import FIXTURES, fee_frontier

    fees = fixture_fees(scenario)
    sides = [
        fees.cumulative(
            qty=100,
            notional="5000",
            side=side,
            trade_date="2027-01-01",
            price_basis=basis,
        )
        for side in ("BUY", "SELL")
    ]
    frontier = fee_frontier(
        dict(
            price=50,
            ticket_usd=5000,
            gross_edge_bps=10,
            sell_date="2027-01-01",
            rate_basis="effective_date",
            pnl_basis=basis,
        ),
        FIXTURES / ("fee_params_" + scenario + ".json"),
    )["metrics"]
    charged = sum(Decimal(s["charged"]) for s in sides)
    assert float(charged) == pytest.approx(frontier["cost_bps"] * 5000 / 10000)
    # Gate floor is not charged to cash.
    assert sum(Decimal(s["gate_floor_diagnostic"]) for s in sides) > charged


def test_sell_partial_cumulative_fees_and_date_switch_in_real_ledger(ledger):
    ledger.register_intent(intent())
    ledger.record_receipt("i", receipt())
    ledger.register_intent(intent("sell", side="SELL", oid="s", date="2027-01-01"))
    for rid, qty, gross, status in [
        ("s1", 1, "50", "partial"),
        ("s100", 100, "5000", "filled"),
    ]:
        assert ledger.record_receipt(
            "sell",
            receipt(
                rid,
                qty=qty,
                gross=gross,
                status=status,
                oid="s",
                at="2027-01-01T15:00:00Z",
            ),
        )["ok"]
    r = read(ledger, prices={})
    assert r["inventory"] == {"X": 0}
    assert r["valuation_complete"] and not r["reconciliation_required"]
    assert Decimal(r["cash"]) == Decimal("15000") - Decimal("1.406427") - Decimal(
        "1.539952"
    )
    assert sum(Decimal(p["fee_delta"]) for p in r["postings"]) == Decimal(r["fees"])
    assert (
        r["fee_ledger"][-1]["lines"]["taf_rate_field"] == "taf_per_share_sell_restored"
    )


def test_failed_protection_blocks_next_intent_and_does_not_hide_exposure(tmp_path):
    case = DATA["cases"][1]
    ledger = ShadowLedger(tmp_path / "shadow15k", DATA["genesis"], fixture_fees("x1"))
    ledger.register_intent(
        dict(
            intent_id="i",
            decision_ts=DATA["decision_ts"],
            input_hash=digest(case),
            orders=case["orders"],
        )
    )
    assert ledger.record_receipt("i", case["receipts"][0])["ok"]
    assert not ledger.register_intent(intent("try-next"))["ok"]
    r = read(ledger)
    assert r["inventory"]["X"] == 100 and not r["hedge_verified"]
    assert r["reconciliation_required"]


def test_database_hardlink_is_refused_before_any_write(tmp_path):
    import os

    outside = tmp_path / "other.sqlite3"
    outside.write_bytes(b"not a database and must stay untouched")
    root = tmp_path / "shadow15k"
    root.mkdir()
    os.link(outside, root / "ledger.sqlite3")
    before = outside.read_bytes()
    with pytest.raises(ValueError, match="foreign_files"):
        ShadowLedger(root, DATA["genesis"], fixture_fees("x1"))
    assert outside.read_bytes() == before


def test_corrupted_event_chain_fails_closed_on_reopen(ledger):
    import sqlite3

    ledger.register_intent(intent())
    with sqlite3.connect(ledger.path) as db:
        db.execute("UPDATE events SET event_hash=?", ("0" * 64,))
    with pytest.raises(ValueError, match="hash_chain_invalid"):
        ShadowLedger(ledger.root, DATA["genesis"], fixture_fees("x1"))


def test_concurrent_first_open_is_safe(tmp_path):
    root = tmp_path / "shadow15k"
    with ThreadPoolExecutor(max_workers=8) as pool:
        ledgers = list(
            pool.map(
                lambda _: ShadowLedger(root, DATA["genesis"], fixture_fees("x1")),
                range(8),
            )
        )
    values = [read(ledger) for ledger in ledgers]
    assert all(v == values[0] for v in values) and values[0]["event_count"] == 0


def test_repeated_terminal_snapshot_validates_integer_type_and_money_equivalence(
    ledger,
):
    ledger.register_intent(intent())
    ledger.record_receipt("i", receipt())
    assert ledger.record_receipt("i", receipt("equivalent", gross=5000.0))["ok"]
    assert not ledger.record_receipt("i", receipt("float-qty", qty=100.0))["ok"]
    assert read(ledger)["inventory"] == {"X": 100}


def test_callers_decimal_context_cannot_change_replay_or_fees(ledger):
    from decimal import ROUND_DOWN, localcontext

    ledger.register_intent(intent())
    ledger.record_receipt("i", receipt())
    expected = read(ledger)
    fees = fixture_fees("x1")
    args = dict(
        qty=100,
        notional="5000",
        side="SELL",
        trade_date="2027-01-01",
        price_basis="reference",
    )
    cost = fees.cumulative(**args)
    with localcontext() as context:
        context.prec = 4
        context.rounding = ROUND_DOWN
        assert read(ledger) == expected
        assert fees.cumulative(**args) == cost
