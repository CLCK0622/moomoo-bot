"""One formal adapter for the original nine dispatch sites; no legacy overload."""

from .arm_n import MISSING, readout
from .contract import digest
from .authority_host import view_binding
from .reception_v2 import bind_formal_n


def bound_readout(
    ledger, arm_tag=MISSING, entrypoint="authority.arm_readout", request_metrics=None
):
    context = snapshot = pin = None
    try:
        context, snapshot, pin, _ = view_binding(ledger)
    except ValueError:
        pass
    bound = bind_formal_n(
        host_context=context,
        request_metrics={} if request_metrics is None else request_metrics,
        installed_snapshot=snapshot,
        entrypoint=entrypoint,
        run_pin=pin,
        arm_tag=arm_tag,
        candidate_ledger=ledger,
    )
    # The legacy projection is only a null-shaped refusal template here; it
    # never receives the caller ledger and cannot call its arm_readout method.
    report = readout(None, MISSING)
    report["metrics"]["arm_n"]["arm_tag"] = (
        arm_tag if isinstance(arm_tag, str) else None
    )
    report["metrics"]["arm_n"]["reasons"] = list(bound["reasons"])
    report["metrics"]["arm_n"]["projection_sha256"] = digest(
        {"refused_arm_tag": report["metrics"]["arm_n"]["arm_tag"]}
    )
    report["artifacts"]["formal_N_binding"] = bound
    report["reasons"] = list(bound["reasons"])
    if bound["accepted"]:
        accepted = bound["details"]["n_acceptance"]
        details = accepted["details"]
        arm = report["metrics"]["arm_n"]
        arm.update(
            cumulative_n=details["complete_N"],
            n_complete=True,
            cumulative_n_lower_bound=details["complete_N"],
            rows=[
                dict(row, observed_N=row["value"], complete_N=row["value"])
                for row in details["N_rows"]
            ],
            observed_N_config=details["complete_N"],
            observed_N_generation_requests=details["N_rows"][1]["value"],
            request_count_known=details["N_rows"][1]["known"],
            projection_sha256=details["projection_sha256"],
            n_ledger_hash=accepted["input_identities"]["chain_sha256"],
        )
        report["metrics"].update(
            cumulative_n=details["complete_N"],
            complete_N=details["complete_N"],
            n_complete=True,
            N_rows=details["N_rows"],
            n_ledger_hash=arm["n_ledger_hash"],
        )
        report["artifacts"]["ledger"] = ledger.snapshot()
        snapshot = report["artifacts"]["ledger"]
        arm["global_history"] = {
            key: snapshot.get(key)
            for key in (
                "legacy_count_readout",
                "recorded_N",
                "n_high_water",
                "authority_tip",
                "authority_sequence",
            )
        }
        report["metrics"]["N_rows"] = arm["rows"]
    return report
