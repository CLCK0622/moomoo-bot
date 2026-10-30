import json
import subprocess
import sys

import pytest

from qlab.dynamic_factor.b2_inputs import b2_input_readout, event_inputs
from qlab.dynamic_factor.contract import digest
from qlab.dynamic_factor.conventions import load_conventions


def request():
    p = load_conventions()
    return dict(
        price_basis="raw_close",
        raw_source_sha256=digest("SYNTHETIC_UNIT_PRICES"),
        prices=[dict(date=d, close=100) for d in p.calendar],
    )


def test_snapshot_off_preserves_rehab_and_aggregate_fields_and_masks_every_snapshot_field():
    on, provenance = event_inputs(True)
    off, same_provenance = event_inputs(False)
    assert provenance == same_provenance
    assert len(on) == len(off) == 51
    assert sum(r["fields"]["rehab_amount"] is not None for r in off) == 49
    for before, after in zip(on, off):
        assert before["event_key"] == after["event_key"]
        for k, v in before["field_sources"].items():
            if v["tier"] == "issuer_snapshot_only":
                assert after["fields"][k] is None
            else:
                assert before["fields"][k] == after["fields"][k]
    assert [r["event_key"] for r in off if r["fields"]["D_used_for_TR"] is None] == [
        "2013-12-20",
        "2014-03-25",
    ]


def test_only_affected_B2_readings_null_no_date_removal_or_cumulative_restart():
    req = request()
    on = b2_input_readout(req)
    off = b2_input_readout(dict(req, include_issuer_snapshot_fields=False))
    assert on["ok"] and off["ok"] and off["metrics"]["formal_return"] is None
    assert len(on["metrics"]["daily"]) == len(off["metrics"]["daily"]) == 3191
    changed = []
    index_unknown = False
    for before, after in zip(on["metrics"]["daily"], off["metrics"]["daily"]):
        assert (
            before["date"] == after["date"]
            and before["raw_close"] == after["raw_close"]
        )
        assert before["raw_price_return"] == after["raw_price_return"]
        if before["daily_total_return"] != after["daily_total_return"]:
            assert after["daily_total_return"] is None
            changed.append(after["date"])
            index_unknown = True
        if index_unknown:
            assert after["cumulative_index"] is None
    assert changed == ["2013-12-20", "2014-03-25"]


@pytest.mark.parametrize(
    "mutation",
    [
        dict(include_issuer_snapshot_fields="false"),
        dict(price_basis="qfq"),
        dict(prices=[]),
    ],
)
def test_invalid_switch_or_suffix_does_not_emit_B2_daily_numbers(mutation):
    r = b2_input_readout(dict(request(), **mutation))
    assert not r["ok"] and r["metrics"]["daily"] is None
    assert not r["certifiable"]


def test_independent_cli_supports_snapshot_off_without_ledger_or_strategy(tmp_path):
    p = tmp_path / "input.json"
    p.write_text(json.dumps(dict(include_issuer_snapshot_fields=False)))
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "qlab.dynamic_factor",
            "b2_input_readout",
            "--input",
            str(p),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    d = json.loads(r.stdout)
    assert d["metrics"]["snapshot_disabled_event_keys"] == ["2013-12-20", "2014-03-25"]
    assert d["metrics"]["account_cash"] is d["metrics"]["formal_return"] is None
