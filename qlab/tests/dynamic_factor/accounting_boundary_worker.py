"""Real C04 rejection paths on private synthetic facts, with call observation.

No compile/worker dispatch is requested by C04. Counts measure calls to those
existing boundaries; they are not evidence of C09 worker integration.
"""

import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from qlab.dynamic_factor.contract import digest  # noqa: E402
from qlab.dynamic_factor.execution_accounting import MODEL  # noqa: E402
from test_execution_accounting import account, facts, record  # noqa: E402


def main(case):
    book, inputs, *_ = account()
    reader_calls = []
    workers = []
    roles = set()

    def observe(frame, event, arg):
        path = frame.f_code.co_filename.replace("\\", "/")
        if (
            event == "return"
            and path.endswith("/reference_inputs.py")
            and frame.f_code.co_name == "read_inputs"
            and isinstance(arg, dict)
        ):
            roles.update(arg)
        if event == "call":
            path = frame.f_code.co_filename.replace("\\", "/")
            name = frame.f_code.co_name
            if path.endswith("/reference_inputs.py") and name == "read_inputs":
                reader_calls.append(name)
            if path.endswith("/reference_boundary.py") and name == "run_isolated":
                workers.append(name)

    sys.setprofile(observe)
    temporary = None
    try:
        if case in {"price", "fee", "B"}:
            rows = facts(book, inputs)
            record(book, [rows[0]])
            bad = rows[1]
            if case == "price":
                bad["price"] = None
            elif case == "B":
                bad["symbol"] = "B"
            else:
                from qlab.dynamic_factor import execution

                temporary = tempfile.TemporaryDirectory()
                path = Path(temporary.name)
                (path / "fee_params_x2.json").write_text("{}")
                execution.FIXTURES = path
            record(book, [bad])
        elif case == "model-forward":
            book.model_open({}, expected_evidence_sha256=digest({}), model_name=MODEL)
        elif case in {"paydate", "TR"}:
            date = book.intent()["ticket"]["execution_session"]
            e = dict(
                event_id="DIV",
                book_id=book.snapshot()["book_id"],
                kind="cash_dividend",
                symbol="COP",
                ex_date=date,
                ex_date_status="verified",
                exact_amount_status="verified_exact",
                cash_basis="analytical_fractional_TR"
                if case == "TR"
                else "integer_pre_tax_cash",
                declared_cash_amount="0.5",
                pay_date=None,
                entitled_integer_shares=4,
                source_sha256=digest("SYNTHETIC ONLY"),
            )
            book.record_cash_events(
                [e], session=date, expected_event_sha256=[digest(e)]
            )
        elif case == "rights":
            e = dict(kind="split", ratio=None)
            book.record_unknown_right(e, expected_event_sha256=digest(e))
        else:
            raise AssertionError(case)
    except ValueError:
        pass
    finally:
        sys.setprofile(None)
        if temporary:
            temporary.cleanup()
    snapshot = book.snapshot()
    value = dict(
        case=case,
        complete=snapshot["complete"],
        NAV=snapshot["NAV"],
        cash=snapshot["cash"],
        reasons=snapshot["reasons"],
        reader_calls=len(reader_calls),
        worker_calls=len(workers),
        accessed_roles=sorted(roles),
        accepted_facts=sum(r["status"] == "ACCEPTED_ACTUAL" for r in snapshot["facts"]),
        retained_receivables=snapshot["retained_state"]["receivables"],
        retained_rights=snapshot["retained_state"]["rights"],
    )
    assert value["complete"] is False and value["NAV"] is None and value["reasons"]
    assert reader_calls == [] and workers == []
    print(json.dumps(value, sort_keys=True))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument(
        "--case",
        required=True,
        choices=["price", "fee", "B", "model-forward", "paydate", "TR", "rights"],
    )
    main(p.parse_args().case)
