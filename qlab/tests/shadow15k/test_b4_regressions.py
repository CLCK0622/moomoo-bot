import json
from pathlib import Path

import pytest

from qlab.shadow15k.b4_harness import (
    CHRONOLOGY,
    FORBIDDEN_PATHS,
    chronology_probe,
    refused_namespace,
)
from qlab.shadow15k.cash_harness import buy_request, fill, marks, packet
from qlab.shadow15k.harness import FIXTURE, fixture_fees
from qlab.shadow15k.ledger import ShadowLedger

GENESIS = json.loads(FIXTURE.read_bytes())["genesis"]


@pytest.mark.parametrize("suffix", FORBIDDEN_PATHS)
def test_forbidden_line_variants_refused_inside_allowlisted_physical_root(
    tmp_path, suffix
):
    assert refused_namespace(tmp_path / suffix, GENESIS, fixture_fees("x1")) == (
        "dedicated_shadow15k_directory_required"
    )


@pytest.mark.parametrize("escape", ["sibling_prefix", "traversal", "symlink"])
def test_root_escape_refused_before_database_creation(tmp_path, escape):
    outside = tmp_path.parent / (tmp_path.name + "-outside") / "shadow15k"
    if escape == "sibling_prefix":
        path = outside
    elif escape == "traversal":
        path = tmp_path / "safe" / ".." / ".." / outside.parent.name / "shadow15k"
    else:
        outside.parent.mkdir()
        (tmp_path / "link").symlink_to(outside.parent, target_is_directory=True)
        path = tmp_path / "link" / "shadow15k"
    assert refused_namespace(path, GENESIS, fixture_fees("x1")) == (
        "namespace_outside_physical_root"
    )
    assert not outside.exists()


def test_default_host_anchor_is_independent_of_constructor_path_and_genesis(
    monkeypatch,
):
    from qlab.shadow15k import ledger

    # Restore the module's source-defined default without creating anything there.
    anchor = (
        Path(ledger.__file__).resolve().parents[3] / ".shadow15k-offline"
    ).resolve()
    monkeypatch.setattr(ledger, "PHYSICAL_ROOT", anchor)
    path = anchor.parent / "other-sandbox" / "shadow15k"
    assert refused_namespace(path, GENESIS, fixture_fees("x1")) == (
        "namespace_outside_physical_root"
    )


def test_symlink_is_still_forbidden_when_target_remains_inside_the_anchor(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    assert refused_namespace(alias / "shadow15k", GENESIS, fixture_fees("x1")) == (
        "namespace_symlink_forbidden"
    )


@pytest.mark.parametrize("case", CHRONOLOGY)
def test_bad_trade_chronology_never_creates_inventory_or_dividend_receivable(
    tmp_path, case
):
    observed = chronology_probe(tmp_path / case, GENESIS, fixture_fees("x1"), case)
    assert observed["inventory"] == {} and observed["receivable_amount"] == "0"
    assert observed["event_count"] == (0 if case == "backfill" else 1)


def test_planned_future_DAY_order_uses_execution_day_for_entitlement(tmp_path):
    book = ShadowLedger(tmp_path / "shadow15k", GENESIS, fixture_fees("x1"))
    request = buy_request("2022-12-16")
    request["orders"][0]["trade_date"] = "2022-12-19"
    assert book.register_intent(request)["ok"]
    assert book.record_receipt("buy", fill("2022-12-19"))["ok"]
    assert not book.record_dividend(packet())["ok"]
    assert book.readout(marks())["metrics"]["receivable_amount"] == "0"


def test_exchange_day_boundary_and_late_terminal_copy_do_not_invent_new_shares(
    tmp_path,
):
    book = ShadowLedger(tmp_path / "shadow15k", GENESIS, fixture_fees("x1"))
    request = buy_request("2022-12-16")
    request["decision_ts"] = "2022-12-16T23:00:00Z"
    assert book.register_intent(request)["ok"]
    receipt = fill("2022-12-16")
    # UTC midnight remains the prior New York date; no date-from-UTC shortcut.
    receipt["receipt_ts"] = "2022-12-17T00:01:00Z"
    assert book.record_receipt("buy", receipt)["ok"]
    receipt.update(receipt_id="late-copy", receipt_ts="2022-12-19T15:00:00Z")
    assert book.record_receipt("buy", receipt)["ok"]
    assert book.record_dividend(packet())["ok"]
    m = book.readout(marks())["metrics"]
    assert m["inventory"] == {"QQQ": 2} and len(m["postings"]) == 1
    assert m["receivable_amount"] == "1.31082"
