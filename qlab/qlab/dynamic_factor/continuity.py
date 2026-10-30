"""Read-only full-grid continuity receipts; no returns execution or OOS refund."""

from copy import deepcopy

from .contract import digest, is_sha, result, unavailable
from .conventions import load_conventions
from .authority_ledger import latest_external_witness
from .fees import finite
from .input_scope import reject_b2_inputs
from .input_disposition import HASHES, sources


def fold_records(manifest, run_id, reason):
    return [
        dict(
            fold_id=f["fold_id"],
            test_start=f["test_start"],
            test_end=f["test_end"],
            status="not_run",
            predictions=None,
            returns=None,
            nav=None,
            reasons=[reason],
            attempt_id=f"{run_id}/{f['fold_id']}/invocation",
            attempted=False,
            budget_state=deepcopy(
                manifest.get("budget_state_by_fold", {}).get(
                    f["fold_id"],
                    {
                        "consumed": None,
                        "seen_result": None,
                        "authorization_sha256": None,
                    },
                )
            ),
        )
        for f in manifest.get("folds", [])
    ]


def continuous_path_check(request, *, conventions=None):
    """Validate supplied receipts against all frozen dates and causal state links.

    A valid structural receipt still leaves estimators/independent acceptance
    unavailable. Missing rows are retained as null records, never dropped.
    """
    policy = conventions or load_conventions()
    expected = policy.fold_manifest()
    outputs = fold_records(
        expected, request.get("run_id", "UNBOUND"), "wf.fold_receipt_missing"
    )
    reasons, stopped, previous, consumed = [], False, None, set()
    seen_results, attempts = set(), set()
    retained_inventory, retained_exit_intents = None, None
    declarations = []
    quarantine = None
    try:
        # Capture every declaration in input order, before shape, membership or
        # grid validation. This list is raw pending evidence, never acceptance.
        rows = request["folds"]
        for index, row in enumerate(rows):
            fields = row if isinstance(row, dict) else {}
            declarations.append(
                dict(
                    input_index=index,
                    raw_declaration=deepcopy(row),
                    metadata_validation_status="pending",
                    **{
                        k: deepcopy(fields.get(k))
                        for k in (
                            "fold_id",
                            "attempt_id",
                            "attempted",
                            "budget_state",
                            "N_receipt",
                        )
                    },
                )
            )
        by_id = {out["fold_id"]: out for out in outputs}
        for out in outputs:
            out["declaration_indices"] = []
        for declaration in declarations:
            row = declaration["raw_declaration"]
            if not isinstance(row, dict) or type(row.get("fold_id")) not in (int, str):
                continue
            out = by_id.get(row["fold_id"])
            if out is not None:
                out["declaration_indices"].append(declaration["input_index"])
        for out in outputs:
            indices = out["declaration_indices"]
            if indices:
                # Duplicate declarations have no singular metadata projection;
                # keep all of them in the ordered list via their input indices.
                row = (
                    declarations[indices[0]]["raw_declaration"]
                    if len(indices) == 1
                    else {}
                )
                out.update(
                    {
                        k: deepcopy(row.get(k))
                        for k in (
                            "attempt_id",
                            "attempted",
                            "budget_state",
                            "N_receipt",
                            "inventory",
                            "exit_intents",
                        )
                    }
                )
                out["metadata_validation_status"] = "pending"
        published = latest_external_witness()
        n_previous = request.get("initial_recorded_N", published["n_high_water"])
        sources()
        if type(n_previous) is not int or n_previous < published["n_high_water"]:
            raise ValueError("ledger.N_receipt_below_published_anchor")
        reject_b2_inputs(request, "qqq_labels")
        from .input_disposition import quarantine_check

        # Consume all row/state ancestry before accepting the frozen grid or
        # copying any numeric NAV. Unknown containers and identities refuse.
        quarantine = quarantine_check(request)
        if not quarantine["ok"]:
            raise ValueError(quarantine["reasons"][0])
        ids = [r["fold_id"] for r in rows]
        if ids != [r["fold_id"] for r in expected["folds"]]:
            raise ValueError("wf.all_original_folds_required")
        if request.get("skip_invalid_folds") or request.get("valid_only"):
            raise ValueError("wf.invalid_fold_may_not_be_skipped")
        if request.get("restart_capital"):
            raise ValueError("wf.capital_restart_forbidden")
        for i, (row, fold, out) in enumerate(zip(rows, expected["folds"], outputs)):
            out["reasons"] = list(row.get("reasons", []))
            budget = row.get("budget_state") or {}
            if (
                not is_sha(budget.get("authorization_sha256"))
                or type(budget.get("consumed")) is not bool
                or type(budget.get("seen_result")) is not bool
            ):
                raise ValueError("wf.budget_receipt_missing")
            authorization = budget["authorization_sha256"]
            if authorization in consumed and budget["consumed"] is False:
                raise ValueError("wf.OOS_budget_refund_forbidden")
            if budget["consumed"]:
                consumed.add(authorization)
            if authorization in seen_results and budget["seen_result"] is False:
                raise ValueError("wf.seen_result_may_not_be_erased")
            if budget["seen_result"]:
                seen_results.add(authorization)
            if i and row.get("initialized"):
                raise ValueError("wf.capital_restart_forbidden")
            if not isinstance(row.get("attempt_id"), str) or not row["attempt_id"]:
                raise ValueError("wf.attempt_receipt_missing")
            if row.get("retry_of") and row["retry_of"] == row["attempt_id"]:
                raise ValueError("ledger.retry_requires_new_counted_attempt")
            if row["attempt_id"] in attempts:
                raise ValueError("ledger.fold_attempt_identity_reused")
            attempts.add(row["attempt_id"])
            if row.get("attempted") is True:
                n = row.get("N_receipt", {})
                if (
                    n.get("attempt_id") != row["attempt_id"]
                    or type(n.get("contribution")) is not int
                    or n["contribution"] < 1
                    or n.get("N_before") != n_previous
                    or n.get("N_after") != n_previous + n["contribution"]
                ):
                    raise ValueError("ledger.failure_or_retry_not_counted")
                n_previous = n["N_after"]
            out["metadata_validation_status"] = "consistent"
            if stopped:
                out.update(
                    status="blocked",
                    predictions=None,
                    returns=None,
                    nav=None,
                    inventory=deepcopy(retained_inventory),
                    exit_intents=deepcopy(retained_exit_intents),
                    inventory_status="last_known_before_halt",
                    reasons=list(
                        dict.fromkeys(
                            out["reasons"] + ["wf.prior_strategy_state_unknown"]
                        )
                    ),
                )
                if row.get("status") == "success" or row.get("executed") is True:
                    reasons.append("wf.continuation_after_invalid_state_forbidden")
                continue
            dates = list(
                policy.calendar[
                    policy.calendar.index(fold["test_start"]) : policy.calendar.index(
                        fold["test_end"]
                    )
                    + 1
                ]
            )
            nav = row.get("nav")
            inp, final = row.get("input_state"), row.get("output_state")
            bad = (
                row.get("status") != "success"
                or row.get("dates") != dates
                or not isinstance(nav, list)
                or len(nav) != len(dates)
                or not all(finite(x) and x > 0 for x in nav)
                or not is_sha(row.get("output_state_sha256"))
                or not is_sha(row.get("input_state_sha256"))
                or not isinstance(inp, dict)
                or not isinstance(final, dict)
                or digest(inp) != row.get("input_state_sha256")
                or digest(final) != row.get("output_state_sha256")
            )
            if i and row.get("input_state_sha256") != previous:
                raise ValueError("wf.continuous_state_link_mismatch")
            if bad:
                stopped = True
                retained_inventory = deepcopy(row.get("inventory"))
                retained_exit_intents = deepcopy(row.get("exit_intents"))
                out.update(
                    status="invalid",
                    predictions=None,
                    returns=None,
                    nav=None,
                    reasons=list(
                        dict.fromkeys(
                            out["reasons"] + ["wf.strategy_state_or_nav_unknown"]
                        )
                    ),
                )
                reasons.append("wf.strategy_state_or_nav_unknown")
            else:
                if final.get("nav") != nav[-1] or (
                    i == 0
                    and inp.get("nav")
                    != policy.document["initialization"]["initial_cash_usd"]
                ):
                    raise ValueError("wf.NAV_state_mismatch")
                out.update(status="success", nav=list(nav), reasons=[])
                previous = row["output_state_sha256"]
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        reasons.append(
            str(exc) if isinstance(exc, ValueError) else "wf.continuity_receipt_invalid"
        )
        # Only mark blocked/reason here; retain every pre-copied declaration,
        # including pending metadata on rows validation has not reached.
        for out in outputs:
            if out["status"] == "not_run":
                out.update(status="blocked", reasons=[reasons[-1]])
    complete = (
        not reasons
        and len(outputs) == len(expected["folds"])
        and all(x["status"] == "success" for x in outputs)
    )
    return policy.bind(
        result(
            "continuous_path_check",
            {
                "request": request,
                "scope_ruling_sha256": HASHES[
                    "EVO883-EVO886-minimum-scope-ruling-v1.json"
                ],
                **policy.binding,
            },
            reasons=reasons,
            metrics={
                "folds": outputs,
                "submitted_declarations": declarations,
                "state_receipt_grid_complete": complete,
                "strategy_path_complete": None,
                "S2_admission_accepted": None,
                "receipt_consistency_only": True,
                "A": None,
                "IR": None,
                "interval": None,
                "B2": None,
                "complete_N": None,
                "dsr": None,
                "event_quarantine": quarantine,
            },
            assumptions=[
                "Full original fold/date vectors and state links are mandatory; no fragment statistics, capital restart, budget refund or automatic recovery is authorized.",
                "Attempt/budget receipts are consistency checks, not independent authority acceptance or permission to recompute.",
            ],
            availability={
                **{
                    k: unavailable(
                        reasons[0]
                        if reasons
                        else "wf.continuity_estimator_not_connected"
                    )
                    for k in ("A", "IR", "interval")
                },
                "B2": unavailable("scope.separate_B2_readout_required"),
                "complete_N": unavailable("ledger_history_incomplete"),
                "dsr": unavailable("dsr.runtime_bindings_pending"),
                "strategy_path_complete": unavailable("pool.S2_unavailable_not_empty"),
            },
        )
    )
