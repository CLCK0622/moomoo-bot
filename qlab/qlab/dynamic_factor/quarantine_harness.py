"""Offline business negatives bound one-for-one to the seven v10 examples."""

import argparse
import json
import platform
from copy import deepcopy
from pathlib import Path

from .contract import canonical, digest, sha256
from .conventions import load_conventions
from .continuity import continuous_path_check
from .event_quarantine import (
    BINDINGS,
    event_receipts,
    field_rules,
    quarantine_check,
    s1_scope,
    s1_input_receipt,
    read_s1_raw_open,
    sources,
)
from .input_disposition import panel_input_check
from .scope_harness import continuity_fixture
from .valuation import integer_cash_valuation


def node(key, field, *, parents=(), **values):
    return dict(id=key, field=field, parents=list(parents), **values)


def cash_request(**values):
    return dict(
        known_cash=100,
        as_of="2026-07-09",
        inventory={"B": 2},
        marks={"B": 10},
        events=[],
        **values,
    )


def assert_nulls(report):
    assert not report["ok"]
    fields = field_rules(sources()[0])
    assert set(report["metrics"]["readouts"]) == set(fields)
    for field in fields:
        assert report["metrics"]["readouts"][field] is None, field
        assert report["metric_availability"][field]["reason"], field
        assert report["metric_availability"][field]["available"] is False, field
    for row in report["metrics"]["projected_nodes"]:
        assert row["value"] is None and row["reasons"], row


def business_case(index):
    doc, _ = sources()
    events = {r["event_key"]: r for r in event_receipts(doc)}
    if index == 1:
        # A caller's repaired/rounded value is not a supported price/cash input.
        row = events["B|2023-08-30"]
        assert row["evidence"]["vendor_amount"] == "0.19984"
        assert row["evidence"]["declared_Barrick_amount"] == "0.1"
        for value in (0.09992, 0.1, 0.19984):
            r = quarantine_check(
                {
                    "dependency_nodes": [
                        node("cash", "receivable", symbol="B", value=value)
                    ]
                }
            )
            assert_nulls(r)
        assert row["analytical_D"] is row["receivable"] is row["available_cash"] is None
    elif index == 2:
        nov27, nov28 = events["B|2019-11-27"], events["B|2019-11-28"]
        assert nov27["event_key"] != nov28["event_key"]
        assert nov28["evidence"]["vendor_date"] == "2019-11-28"
        assert "DO_NOT_DEDUPE_OR_SHIFT" in nov28["action"]
        request = cash_request()
        request["events"] = [
            dict(
                symbol="B",
                ex_date=date,
                entitled_integer_shares=2,
                declared_cash_amount=0.05,
            )
            for date in ("2019-11-27", "2019-11-28")
        ]
        r = integer_cash_valuation(request)
        assert not r["ok"] and r["metrics"]["receivable_amount"] is None
        assert r["metrics"]["available_cash"] is None
    elif index == 3:
        for date in ("2021-08-30", "2021-11-29"):
            row = events[f"B|{date}"]
            assert row["evidence"]["vendor_amount"] == "0.1405"
            assert "RETURN_OF_CAPITAL" in row["action"]
            relations = [
                r
                for r in doc["unmatched_declaration_relations"]
                if r["derived_ex_candidate"] == date
            ]
            assert len(relations) == 1 and relations[0]["declared_amount"] == "0.09"
            r = quarantine_check(
                {
                    "dependency_nodes": [
                        node("guess", "cash", symbol="B", date=date, value=0.2305)
                    ]
                }
            )
            assert_nulls(r)
            assert row["available_cash"] is None
    elif index == 4:
        # Dependency order and observation dates differ. The prior anchor is
        # affected by a later event; an unrelated current symbol cannot clear
        # the carried balance that consumed it.
        rows = [
            node(
                "later",
                "inventory",
                parents=["cash"],
                symbol="QQQ",
                date="2026-07-09",
                value=3,
            ),
            node(
                "anchor",
                "raw_close",
                event_keys=["B|2023-08-30"],
                date="2013-10-29",
                value=100,
            ),
            node("cash", "cash", parents=["anchor"], date="2024-01-01", value=100),
        ]
        r = quarantine_check({"dependency_nodes": rows})
        assert_nulls(r)
        assert all(
            "B|2023-08-30" in x["event_keys"] for x in r["metrics"]["projected_nodes"]
        )
    elif index == 5:
        rows = [
            node(
                "entry",
                "entitled_shares",
                symbol="B",
                date="2023-08-30",
                value=0,
                entry_on_ex_open=True,
            ),
            node("history", "eligible_state", parents=["entry"], value="VERIFIED_GE50"),
            node(
                "label",
                "H10_label",
                parents=["entry"],
                dependency_start="2023-08-29",
                dependency_end="2023-09-15",
                value=0.1,
            ),
        ]
        assert_nulls(quarantine_check({"dependency_nodes": rows}))
    elif index == 6:
        s1 = s1_input_receipt()
        item = dict(
            symbol="BRK.B",
            field="raw_open",
            date="2013-10-29",
            price_basis="NONE",
            source_csv_sha256=s1["csv_sha256"],
        )
        assert s1_scope(item)
        assert panel_input_check({"inputs": [item]})["ok"]
        assert s1["rows"] == 3191 and s1["field_receipt_adopted"]
        assert s1["price_values"] is None and not s1["source_independence"]
        for change in (
            {"field": "volume_as_traded_units"},
            {"symbol": "B"},
            {"date": "2013-10-28"},
            {"date": "2026-07-10"},
            {"price_basis": "QFQ"},
            {"source_csv_sha256": "0" * 64},
        ):
            assert not s1_scope(dict(item, **change))
        assert not s1["complete_execution_path_certified"]
        raw = (
            Path(__file__).parent
            / "fixtures"
            / "evo898"
            / "EVO893-S1-BRKB-v10-open-none.csv"
        ).read_bytes()
        adopted = read_s1_raw_open(raw)
        assert len(adopted["rows"]) == 3191
        assert all(
            set(row) == {"symbol", "date", "raw_open"} for row in adopted["rows"]
        )
        assert not adopted["receipt"]["source_independence"]
    elif index == 7:
        r = quarantine_check(
            {
                "dependency_nodes": [
                    node("missing", "NAV", event_keys=["B|2022-05-26"], value=0),
                    node("DSR", "DSR", parents=["missing"], value=0),
                ]
            }
        )
        assert_nulls(r)
        assert len(r["metrics"]["unmatched_relations"]) == 15
        assert all(
            x["repair_amount"] is None
            and x["actual_missing_payment_certified"] is False
            for x in r["metrics"]["unmatched_relations"]
        )
    else:
        raise ValueError("unknown business case")
    return dict(
        id=f"NEG{index}",
        text=doc["engineering_negative_examples"][index - 1],
        status="PASS",
    )


def prohibitions():
    policy = load_conventions()
    cases = []
    r = integer_cash_valuation(cash_request())
    assert not r["ok"]
    assert r["metrics"]["nav"] is r["metrics"]["available_cash"] is None
    assert r["metrics"]["declared_inventory"] == {"B": 2}
    assert r["metrics"]["known_available_cash"] == 100
    assert_nulls(r["metrics"]["event_quarantine"])
    cases.append(dict(id="NO_CASH_ROW_RECOVERY", status="PASS"))
    panel = list(policy.profile["universe"])
    assert len(panel) == 64
    r = panel_input_check(
        {"inputs": [], "panel_symbols": [s for s in panel if s not in ("B", "COR")]}
    )
    assert not r["ok"] and "data.v10_frozen_panel_required" in r["reasons"]
    cases.append(dict(id="NO_SILENT_PANEL_DELETE", status="PASS"))
    for flag, reason in (
        ("skip_invalid_folds", "wf.invalid_fold_may_not_be_skipped"),
        ("restart_capital", "wf.capital_restart_forbidden"),
    ):
        req = continuity_fixture(policy)
        req[flag] = True
        r = continuous_path_check(req, conventions=policy)
        assert not r["ok"] and reason in r["reasons"]
        assert len(r["metrics"]["folds"]) == len(req["folds"]) == 77
        assert len(r["metrics"]["submitted_declarations"]) == 77
        cases.append(dict(id="NO_" + flag.upper(), status="PASS"))
    req = continuity_fixture(policy)
    before = deepcopy(req)
    req["dependency_nodes"] = [
        node("old-anchor", "raw_open", symbol="COR", date="2010-01-04", value=10)
    ]
    r = continuous_path_check(req, conventions=policy)
    assert not r["ok"] and not r["metrics"]["state_receipt_grid_complete"]
    assert (
        len(r["metrics"]["folds"]) == len(r["metrics"]["submitted_declarations"]) == 77
    )
    for row, source in zip(r["metrics"]["submitted_declarations"], before["folds"]):
        assert row["raw_declaration"] == source
    assert all(x["nav"] is None and x["reasons"] for x in r["metrics"]["folds"])
    assert_nulls(r["metrics"]["event_quarantine"])
    cases.append(dict(id="NO_CROSS_FOLD_AUTO_RESUME", status="PASS"))
    return cases


def run():
    fields = field_rules(sources()[0])
    projection = quarantine_check(
        {
            "dependency_nodes": [node("event", "event", event_keys=["B|2023-08-30"])]
            + [node(field, field, parents=["event"], value=1) for field in fields]
        }
    )
    assert_nulls(projection)
    return dict(
        schema="EVO898.quarantine-harness/v1",
        bindings=BINDINGS,
        cases=[business_case(i) for i in range(1, 8)] + prohibitions(),
        projection=projection,
        dependencies={"python": platform.python_version()},
        runtime_consumable=False,
        certifiable=False,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run()
    raw = (
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2).encode()
        + b"\n"
    )
    args.output.write_bytes(raw)
    semantic = {k: v for k, v in report.items() if k != "dependencies"}
    print(
        json.dumps(
            dict(
                cases=len(report["cases"]),
                sha256=sha256(raw),
                canonical_sha256=sha256(canonical(semantic)),
                semantic_digest=digest(semantic),
            )
        )
    )


if __name__ == "__main__":
    main()
