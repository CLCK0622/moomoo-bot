"""Executable private contract specimens; never a production trust adapter.

The original argv stays a test-only adapter. It invokes only the v3/v3.1 public
receivers and does not translate an old result into a new authority capability.
"""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import tempfile

from _pytest.monkeypatch import MonkeyPatch

from qlab.dynamic_factor import authority_host as host
from qlab.dynamic_factor.authority_ledger import (
    records,
    replay_approved_archive,
    validate_new_attempt,
)
from qlab.dynamic_factor.authority_record_types import validate_attempt_fields
from qlab.dynamic_factor.arm_n import MISSING
from qlab.dynamic_factor.contract import sha256, digest
from qlab.dynamic_factor.reception_v2 import bind_formal_n, ENTRYPOINTS
from qlab.dynamic_factor.reception_schema import validate
from authority_stage1_helpers import archive, rewrite, raw_json
from installation_host_helpers import installation_host
from test_reception_n03 import receive
from contract_adapters_v3 import adapt_v2_n01, adapt_v2_n02
from contract_adapters_v31 import adapt_v2_n03

BASELINE = "4cdfcbc0726abeadfff9e143b49281fab815bc43"
DESIGN_BASELINE = "6fa70f6c2f5d3599acb31e6063d78611c206fa7a"


def observed(result):
    return dict(
        schema=result["schema"],
        accepted=result["accepted"],
        state=result["state"],
        reasons=result["reasons"],
        binding_sha256=result["binding_sha256"],
        complete_N=result["details"].get("complete_N"),
        gate_N=result["details"].get("gate_N"),
        observations=result["observations"],
    )


def rejection(call):
    try:
        call()
    except ValueError as exc:
        return dict(accepted=False, reason=str(exc))
    raise AssertionError("negative specimen unexpectedly accepted")


def n_case(case, path, mp, variant="original"):
    adapter = (
        adapt_v2_n01
        if case.startswith("N-01")
        else adapt_v2_n02
        if case.startswith("N-02")
        else adapt_v2_n03
    )(case)
    receiver = adapter["receiver"]
    context, source, document = installation_host(
        path,
        mp,
        prefix_stub=False,
        complete=case in ("N-01-06", "N-02-04", "N-02-05", "N-02-06", "N-02-07"),
    )
    before = (
        Path(source["chain_path"]).read_bytes(),
        Path(source["witness_path"]).read_bytes(),
    )
    if case.startswith("N-03"):
        raw = source["installation_receipt_bytes"]
        module = None
        if case == "N-03-01":
            raw = None
        elif case == "N-03-02":
            context = {"accepted": True, "source_verified": True}
        elif case == "N-03-03":
            module = "/other/authority_ledger.py"
        elif case == "N-03-04":
            # Three independently required original approvals are absent.
            group = {
                "hanlin": "identity",
                "plan": "approved_release",
                "chief": "deploy_root",
            }[variant]
            host._HOSTS[context]["independent_group_results"][group]["status"] = "FAIL"
        elif case == "N-03-05":
            changed = deepcopy(document)
            changed["deploy_root"]["module_realpath"] = "/other/authority_ledger.py"
            raw = raw_json(changed)
        elif case == "N-03-06":
            Path(source["chain_path"]).write_bytes(
                source["chain_raw"].split(b"\n")[0] + b"\n"
            )
        result = receiver(
            host_context=context,
            runtime_module_path=source["module_path"] if module is None else module,
            installation_receipt_bytes=raw,
            published_anchor_bytes=source["published_anchor_bytes"],
            acceptance_bytes=source["installation_acceptance_bytes"],
        )
        assert result["accepted"] is (case == "N-03-07"), result["reasons"]
        validate(result, "N-03.v31.schema.json")
    else:
        checked = receive(context, source)
        assert checked["accepted"], checked["reasons"]
        snapshot = host.installed_snapshot(context)
        pin = host.pin_run(context, arm_tag="EVO883_FACTOR", run_id="SPEC-" + case)
        approval, projection = source["approval_bytes"], source["projection_bytes"]
        tag = "EVO883_FACTOR"
        if case.endswith("-01"):
            if case.startswith("N-01"):
                approval = None
            else:
                snapshot = None
        elif case in ("N-01-02", "N-02-02"):
            if case.startswith("N-01"):
                approval = raw_json(dict(approved=True, complete=True, dependencies=[]))
            else:
                context = {"source_verified": True, "accepted": True}
        elif case in ("N-01-03", "N-02-03"):
            pin = host.pin_run(context, arm_tag="EVO896_LLMCLI", run_id="OTHER-ACTOR")
        elif case == "N-01-04":
            changed = json.loads(projection)
            if variant == "wrong_arm":
                changed["arm_tag"] = "EVO896_LLMCLI"
            elif variant == "sensitivity_as_primary":
                changed["N_rows"].reverse()
            else:
                changed["N_rows"][0].update(value=1313, known=True)
                changed["complete"] = True
            projection = raw_json(changed)
        elif case == "N-01-05":
            changed = json.loads(approval)
            changed["coverage"] = "NEW-UNCOVERED-TIP"
            approval = raw_json(changed)
        if case.startswith("N-01"):
            result = receiver(
                approval,
                projection,
                host_context=context,
                installed_snapshot=snapshot,
                run_pin=pin,
                arm_tag=tag,
            )
            assert result["accepted"] is (case == "N-01-06"), result["reasons"]
            validate(result, "N-01.v3.schema.json")
        else:
            kwargs = dict(
                host_context=context,
                request_metrics={"self_report_n": 999999},
                installed_snapshot=snapshot,
                run_pin=pin,
                arm_tag=tag,
            )
            if case == "N-02-04":
                tag = {
                    "omitted": MISSING,
                    "null": None,
                    "invalid": "OTHER",
                    "conflict": tag,
                }[variant]
                kwargs["arm_tag"] = tag
                if variant == "conflict":
                    kwargs["request_metrics"]["arm_tag"] = "EVO896_LLMCLI"
            if case == "N-02-05":

                class Caller:
                    def arm_readout(self, *args):
                        raise AssertionError("caller consumed")

                kwargs["candidate_ledger"] = Caller()
            if case == "N-02-06":
                # A separately pinned operation cannot silently inherit a changed
                # accepted projection, even if its own-arm value stays 7.
                changed = deepcopy(host._HOSTS[context])
                doc = json.loads(changed["projection_bytes"])
                doc["acceptance_version"] = "PRIVATE-2"
                changed["projection_bytes"] = raw_json(doc)
                host._HOSTS[context] = changed
            reports = []
            for entry in sorted(ENTRYPOINTS):
                result = receiver(entrypoint=entry, **kwargs)
                validate(result, "N-02.v3.schema.json")
                assert result["accepted"] is (case == "N-02-07"), (
                    entry,
                    result["reasons"],
                )
                assert result["observations"]["economic_reader"] == 0
                reports.append(dict(entrypoint=entry, **observed(result)))
            return reports
    assert all(
        result["observations"].get(key, 0) == 0
        for key in (
            "economic_reader",
            "worker_read_inputs",
            "authority_writes",
            "budget_api",
        )
    )
    if case != "N-03-06":
        assert before == (
            Path(source["chain_path"]).read_bytes(),
            Path(source["witness_path"]).read_bytes(),
        )
    return observed(result)


def t_case(case, path, mp, variant="original"):
    raw, witness, coverage = archive()
    if case in ("T1-01", "T1-07"):
        report = replay_approved_archive(raw, trusted_release=coverage, witness=witness)
        assert report["book_N"] == report["high_water"] == 1313
        assert report["raw_unknown_rows"] == 101 and report["complete_N"] is None
        return dict(
            accepted=True,
            book_N=1313,
            unknown_rows=101,
            complete_N=None,
            raw_sha256=sha256(raw),
            unknown_rows_sha256=digest(report["unknown_rows"]),
        )
    if case in ("T1-02", "T1-03"):
        row = deepcopy(records(raw)[1149])
        if case == "T1-02":
            if variant == "missing_count_field":
                del row["n_evaluated"]
            elif variant == "missing_reason":
                del row["n_evaluated_null_reason"]
            else:
                row["n_evaluated_null_reason"] = (
                    "" if variant == "empty_reason" else "   "
                )
        else:
            if variant == "missing_n_trials_total":
                del row["n_trials_total"]
            else:
                row["n_evaluated"] = {
                    "negative": -1,
                    "float": 1.0,
                    "bool": True,
                    "string": "0",
                }[variant]
        from qlab.dynamic_factor.authority_record_types import (
            _issue_coverage,
            _HOST_TOKEN,
        )

        coverage = _issue_coverage(
            raw_json(row) + b"\n", "PRIVATE-BAD-FIELDS", _HOST_TOKEN
        )
        return rejection(
            lambda: validate_attempt_fields(
                row, mode="historical_replay", trusted_coverage=coverage
            )
        )
    if case == "T1-04":
        changed = rewrite(raw, lambda rows: rows[1149].update(n_evaluated=0))
        return rejection(
            lambda: replay_approved_archive(
                changed, trusted_release=coverage, witness=witness
            )
        )
    if case == "T1-05":
        changed = b"\n".join(raw.splitlines()[:1149]) + b"\n"
        return rejection(
            lambda: replay_approved_archive(
                changed, trusted_release=coverage, witness=witness
            )
        )
    if case == "T1-06":
        return rejection(
            lambda: validate_new_attempt(records(raw)[1149], records(raw)[:1149])
        )
    if case in ("T1-08", "T1-09", "A-09"):
        positive = case == "T1-08" and variant in (
            "approved_reconciliation",
            "approved_other_arm_no_feedback",
        )
        context, source, _ = installation_host(
            path, mp, prefix_stub=False, complete=positive
        )
        assert receive(context, source)["accepted"]
        snapshot = host.installed_snapshot(context)
        pin = host.pin_run(context, arm_tag="EVO883_FACTOR", run_id=case)
        result = bind_formal_n(
            host_context=context,
            installed_snapshot=snapshot,
            run_pin=pin,
            arm_tag="EVO883_FACTOR",
            request_metrics={"self_report_n": 1313},
            entrypoint="statistics.dsr_eval_arm",
        )
        assert result["accepted"] is positive, result["reasons"]
        assert result["details"]["gate_N"] == (7 if positive else None)
        return observed(result)
    context, source, document = installation_host(path, mp, prefix_stub=False)
    if case == "A-01":
        context = {"source_verified": True}
    elif case in ("A-02", "A-03", "A-04", "A-06", "A-08"):
        changed = deepcopy(document)
        if case == "A-02":
            changed["anchor"]["V2"]["L1_revision"] = 999
        elif case == "A-03":
            changed["anchor"]["V1"]["sequence"] = 182
        elif case == "A-04":
            changed["ledger"]["tip"] = "0" * 64
        elif case == "A-06":
            changed["ledger"]["ledger_id"] = "1" * 64
        elif variant == "path_integer":
            changed["ledger"]["ledger_path"] = 123
        elif variant == "revision_bool":
            changed["anchor"]["V2"]["L1_revision"] = True
        elif variant == "result_string_true":
            changed["identity"]["result"] = "true"
        else:
            changed["deploy_root"]["module_realpath"] = "/alias/authority_ledger.py"
        result = receive(context, source, raw_json(changed))
        assert not result["accepted"]
        return observed(result)
    elif case == "A-05":
        from qlab.dynamic_factor.authority_prefix import verify_anchor_prefix

        anchor = deepcopy(source["anchor"])
        anchor["ledger_file_sha256"] = "0" * 64
        observation = deepcopy(source["observation"])
        observation.update(
            anchor_raw=raw_json(anchor),
            anchor_ref="sha256:" + sha256(raw_json(anchor)),
            anchor_payload_sha256=sha256(raw_json(anchor)),
            approved_anchor_sha256=sha256(raw_json(anchor)),
        )
        result = verify_anchor_prefix(source["chain_raw"], anchor, observation)
        assert result["status"] != "PASS"
        return result
    elif case == "A-07":
        assert receive(context, source)["accepted"]
        from qlab.dynamic_factor.authority_binding import (
            make_worker_binding,
            verify_worker_binding,
        )

        snapshot = host.installed_snapshot(context)
        pin = host.pin_run(context, arm_tag="EVO883_FACTOR", run_id=case)
        expected = make_worker_binding(context, snapshot, pin, "EVO883_FACTOR")
        changed = deepcopy(expected)
        changed["chain_sha256"] = "0" * 64
        return rejection(lambda: verify_worker_binding(changed, expected))
    result = receive(context, source)
    assert not result["accepted"]
    return observed(result)


VARIANTS = {
    "N-01-04": ["wrong_arm", "book_as_primary", "sensitivity_as_primary"],
    "N-02-04": ["omitted", "null", "invalid", "conflict"],
    "N-03-04": ["hanlin", "plan", "chief"],
    "T1-02": [
        "missing_reason",
        "empty_reason",
        "whitespace_reason",
        "missing_count_field",
    ],
    "T1-03": ["negative", "float", "bool", "string", "missing_n_trials_total"],
    "T1-08": [
        "approved_reconciliation",
        "caller_claims_resolved",
        "approved_other_arm_no_feedback",
    ],
    "A-05": ["caller_V5_PASS", "shared_V5_binding_missing"],
    "A-08": [
        "path_integer",
        "revision_bool",
        "result_string_true",
        "L2_path_alias_mismatch",
    ],
}


def run_case(case, root):
    root = Path(root).resolve()
    reports = []
    for variant in VARIANTS.get(case, ["original"]):
        with (
            tempfile.TemporaryDirectory(dir=root, prefix=case + "-") as work,
            MonkeyPatch.context() as mp,
        ):
            f = n_case if case.startswith("N-") else t_case
            result = f(case, Path(work), mp, variant)
            reports.append(dict(variant=variant, result=result))
    return dict(
        case_id=case,
        status="PASS",
        private_trust_assumption=True,
        production_installation=False,
        baseline=BASELINE,
        design_baseline=DESIGN_BASELINE,
        variants=reports,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", required=True)
    parser.add_argument(
        "--baseline", required=True, choices=[BASELINE, DESIGN_BASELINE]
    )
    parser.add_argument("--private-fixtures", required=True, type=Path)
    parser.add_argument("--contract-version")
    parser.add_argument("--contract-id")
    parser.add_argument("--contracts-dir", type=Path)
    parser.add_argument("--report-json", default="-")
    args = parser.parse_args()
    args.private_fixtures.mkdir(parents=True, exist_ok=True)
    result = run_case(args.case_id, args.private_fixtures)
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False)
    if args.report_json == "-":
        print(encoded)
    else:
        Path(args.report_json).write_text(encoded + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
