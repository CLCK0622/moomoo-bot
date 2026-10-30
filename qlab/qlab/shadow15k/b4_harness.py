"""Fourth-batch namespace and chronology regressions; synthetic receipts only."""

from copy import deepcopy

from . import ledger as ledger_module
from .cash_harness import buy_request, fill, marks, packet
from .ledger import ShadowLedger


FORBIDDEN_PATHS = (
    "EVO-844/shadow15k",
    "EVO-851/shadow15k",
    "EVO-774/shadow15k",
    "evo_774/shadow15k",
    "safe/../EVO-844/shadow15k",
    "workspace-EvO-844-run/shadow15k",
    "evo-851-workspace/shadow15k",
    "workspace_eVo_774_run/shadow15k",
)
CHRONOLOGY = {
    "backfill": ("2022-12-19", "2022-12-16", "2022-12-19"),
    "future": ("2022-12-16", "2022-12-20", "2022-12-19"),
    "cross_ex_date": ("2022-12-16", "2022-12-16", "2022-12-19"),
}


def refused_namespace(path, genesis, fees):
    try:
        ShadowLedger(path, genesis, fees)
    except ValueError as exc:
        reason = str(exc)
    else:
        raise AssertionError("foreign physical namespace accepted")
    assert not (path.resolve() / "ledger.sqlite3").exists()
    return reason


def chronology_probe(root, genesis, fees, case):
    decision, trade, confirmed = CHRONOLOGY[case]
    book = ShadowLedger(root / "shadow15k", genesis, fees)
    request = buy_request(decision)
    request["orders"][0]["trade_date"] = trade
    intent = book.register_intent(request)
    before = book.readout(marks())["metrics"]
    receipt = book.record_receipt("buy", fill(confirmed))
    assert not intent["ok"] or not receipt["ok"]
    after = book.readout(marks())["metrics"]
    assert after == before and after["inventory"] == {}
    assert not book.record_dividend(packet())["ok"]
    final = book.readout(marks())["metrics"]
    assert final == before and final["receivable_amount"] in (None, "0")
    return dict(
        intent_ok=intent["ok"],
        receipt_ok=receipt["ok"],
        intent_reasons=intent["reasons"],
        receipt_reasons=receipt["reasons"],
        receivable_amount=final["receivable_amount"],
        event_count=final["event_count"],
        inventory=deepcopy(final["inventory"]),
    )


def cases(workdir, genesis, fees):
    out = []
    for i, suffix in enumerate(FORBIDDEN_PATHS):
        reason = refused_namespace(workdir / suffix, genesis, fees)
        out.append(
            dict(
                case_id="namespace.B4_R1_variant_%d" % i,
                status="PASS",
                requested_suffix=suffix,
                reason=reason,
                database_exists=False,
            )
        )
    anchor = ledger_module.PHYSICAL_ROOT
    reason = refused_namespace(
        anchor.parent / (anchor.name + "-outside") / "shadow15k", genesis, fees
    )
    assert reason == "namespace_outside_physical_root"
    out.append(
        dict(
            case_id="namespace.B4_R1_physical_root_escape",
            status="PASS",
            reason=reason,
            database_exists=False,
        )
    )
    for case in CHRONOLOGY:
        out.append(
            dict(
                case_id="cash.B4_R2_" + case,
                status="PASS",
                observed=chronology_probe(workdir / case, genesis, fees, case),
            )
        )
    return out
