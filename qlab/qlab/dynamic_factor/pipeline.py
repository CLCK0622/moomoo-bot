"""v0.2 train-only S0 -> S4 orchestration for trusted, injected adapters.
No price acquisition, strategy implementation, or automatic reference runs.
Reference registries are separately pinned inputs, never scalar V supplied by a
current candidate. Stage records are immutable, including failures and empty pools.
"""

from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path

from .contract import digest, is_sha, sha256
from .conventions import arithmetic
from .dsr_v0 import formula, variance
from .statistics import MISSING, label, valid_arm
from .fees import finite
from .input_scope import reject_b2_inputs


def read_pinned(path, expected_sha256, *, conventions=None):
    from .reference_registry import HASHES
    from .conventions import load_conventions

    if (conventions or load_conventions()).document["version"] == "v3.0.0":
        from .reference_registry_v3 import HASHES

    if (
        Path(path).name
        not in (
            "predeclared_reference_registry.json",
            "candidate_reference_manifest.json",
            "meta_reference_manifest.json",
        )
        or expected_sha256 != HASHES[Path(path).name]
    ):
        raise ValueError("pipeline.only_registered_definition_files_allowed")
    raw = Path(path).read_bytes()
    if not is_sha(expected_sha256) or sha256(raw) != expected_sha256:
        raise ValueError("pipeline.input_hash_mismatch")
    return {
        "sha256": sha256(raw),
        "document": json.loads(raw),
        "semantic_sha256": digest(json.loads(raw)),
    }


def moments(returns, policy):
    p = policy.document["DSR"]
    var = variance(returns, int(p["sample_sd"].removeprefix("ddof")))
    if var <= 0:
        raise ValueError("dsr.zero_return_variance")
    mean = math.fsum(returns) / len(returns)
    central = {
        f"population_m{k}": math.fsum((r - mean) ** k for r in returns) / len(returns)
        for k in (2, 3, 4)
    }
    return {
        "mean": mean,
        "sharpe": mean / math.sqrt(var),
        "skew": arithmetic(p["skew"].replace("^", "**"), central),
        "kurt": arithmetic(
            p["kurt"].removesuffix("_non_excess_normal3").replace("^", "**"), central
        ),
        "n": len(returns),
    }


def price_basis_check(context):
    receipt = context.get("price_basis_receipt") or {}
    if (
        not is_sha(receipt.get("source_sha256"))
        or receipt.get("universe_and_data_sha256")
        != context.get("universe_and_data_sha256")
        or not all(
            receipt.get(k) is True
            for k in (
                "execution_price_basis_verified",
                "total_return_basis_verified",
                "cross_anchor_comparability_verified",
            )
        )
    ):
        raise ValueError("data.price_basis_unverified")


def validate_context(context, policy):
    price_basis_check(context)
    if policy.document["version"] in ("v2.0.0", "v3.0.0") and any(
        not is_sha(context.get(key))
        for key in ("quarantine_manifest_sha256", "eligible_set_derivation_sha256")
    ):
        raise ValueError("pipeline.v2_isolation_identity_missing")
    if policy.document["version"] in ("v2.0.0", "v3.0.0"):
        from .isolation import checked_manifest, eligible_day

        isolation = context.get("isolation")
        if not isolation:
            raise ValueError("pipeline.v2_isolation_receipts_missing")
        checked_manifest(isolation["manifest"], policy)
        days = {
            d: eligible_day(isolation["manifest"], d, policy)[
                "eligible_set_derivation_sha256"
            ]
            for d in context["train_calendar"]
        }
        if context["quarantine_manifest_sha256"] != isolation["manifest"][
            "quarantine_manifest_sha256"
        ] or context["eligible_set_derivation_sha256"] != digest(days):
            raise ValueError("pipeline.v2_isolation_identity_mismatch")
    calendar = context["train_calendar"]
    if len(calendar) != policy.document["folds"]["train_days"] or calendar != sorted(
        set(calendar)
    ):
        raise ValueError("pipeline.train_window_mismatch")
    fold = next(
        (
            x
            for x in policy.date_manifest["folds"]
            if str(x["fold_id"]) == str(context["fold_id"])
        ),
        None,
    )
    if fold is None or calendar != list(
        policy.calendar[
            fold["train_index_inclusive"][0] : fold["train_index_inclusive"][1] + 1
        ]
    ):
        raise ValueError("pipeline.train_window_mismatch")
    if (
        not is_sha(context.get("universe_and_data_sha256"))
        or context.get("cost_model_sha256")
        != policy.document["cost_mapping"]["x2_sha256"]
    ):
        raise ValueError("pipeline.data_or_cost_identity_missing")
    if (
        context.get("common_profile_sha256")
        != policy.document["variance_layers"]["probe_profile"]["common_profile_sha256"]
    ):
        raise ValueError("pipeline.profile_mismatch")


def _reference_variance(registry, layer, context, policy):
    if registry is None:
        raise ValueError(f"dsr.{layer}_reference_missing")
    document = registry["document"]
    if digest(document) != registry.get(
        "semantic_sha256", digest(document)
    ) or not is_sha(registry.get("sha256")):
        raise ValueError("dsr.reference_identity_invalid")
    ref = document[layer]
    spec = policy.document["variance_layers"]["independent_reference"]
    members = ref["members"]
    trials = ref["trials"]
    if (
        len(members) != len(set(members))
        or set(members) != set(trials)
        or len(members) < spec["minimum_finite_SR_per_complete_reference_family"]
    ):
        raise ValueError("dsr.reference_family_incomplete")
    profile = spec[f"{layer}_reference_profile"]
    values = []
    for tid in members:
        trial = trials[tid]
        if any(k not in trial for k in spec["required_per_trial"]):
            raise ValueError("dsr.reference_provenance_missing")
        if (
            not isinstance(trial["source_run_id"], str)
            or not trial["source_run_id"]
            or trial["trial_id"] != tid
            or trial["source_run_id"] == context["run_id"]
            or context["run_id"] in trial.get("derived_from_runs", [])
            or trial["return_role"] != policy.document["N"]["DSR_SR_basis"]
            or trial["profile_id_and_sha256"]
            != {"id": profile, "sha256": context["common_profile_sha256"]}
            or trial["universe_and_data_sha256"] != context["universe_and_data_sha256"]
            or trial["cost_model_sha256"] != context["cost_model_sha256"]
            or trial["train_calendar_sha256"] != digest(context["train_calendar"])
            or trial["scale"] != "daily"
        ):
            raise ValueError("dsr.reference_profile_window_or_source_mismatch")
        returns = trial["returns"]
        if policy.document["version"] in ("v2.0.0", "v3.0.0") and any(
            not is_sha(context.get(key)) or trial.get(key) != context[key]
            for key in ("quarantine_manifest_sha256", "eligible_set_derivation_sha256")
        ):
            raise ValueError("dsr.reference_isolation_mismatch")
        if policy.document["version"] == "v3.0.0" and (
            not is_sha(context.get("noncash_guard_manifest_sha256"))
            or trial.get("noncash_guard_manifest_sha256")
            != context["noncash_guard_manifest_sha256"]
            or not is_sha(
                trial.get("zero_exposure_and_consumer_dependency_receipt_sha256")
            )
        ):
            raise ValueError("dsr.reference_B_release_or_proof_mismatch")
        if trial["source_returns_sha256"] != digest(returns) or len(returns) != len(
            context["train_calendar"]
        ):
            raise ValueError("dsr.reference_returns_identity_mismatch")
        values.append(moments(returns, policy)["sharpe"])
    return variance(
        values, int(policy.document["DSR"]["sample_sd"].removeprefix("ddof"))
    )


def _layer(srs, layer, registry, context, policy):
    ref = _reference_variance(registry, layer, context, policy)
    own = variance(srs, int(policy.document["DSR"]["sample_sd"].removeprefix("ddof")))
    v = policy.document["variance_layers"]
    expression = v[f"{layer}_V"]
    variables = {
        "sample_var_ddof1_complete_SR16"
        if layer == "candidate"
        else "sample_var_ddof1_complete_SR16_plus_SR_meta": own,
        f"{layer}_reference_V": ref,
    }
    return {
        "family_variance": own,
        "independent_variance": ref,
        "trials_variance": arithmetic(expression, variables),
    }


def _dsr(m, v, n_snapshot, policy):
    sr0, value = formula(
        policy,
        SR=m["sharpe"],
        n=m["n"],
        N=n_snapshot["gate_n"],
        V=v,
        skew=m["skew"],
        kurt=m["kurt"],
        n_complete=n_snapshot["n_complete"],
    )
    return dict(m, sr0=sr0, dsr=value)


def _n_snapshot(ledger, self_report_n, policy=None, *, arm_tag=None):
    """Read the formal arm projection without observing or writing a self-report.

    The third positional argument remains the factor policy object.
    A label must be supplied by keyword; neither a function name nor a policy
    version supplies identity. Omission and explicit null both refuse here.
    A book high-water value remains diagnostic metadata, never complete arm N.
    The shared readout verifies one chain and retains both N rows together.
    Current factor v3 and LLM history still lack complete-arm acceptance.
    This wrapper has no attempt registration, callbacks or ledger writes.
    """
    from .statistics import arm_snapshot

    return arm_snapshot(
        ledger,
        self_report_n,
        policy,
        arm_tag=arm_tag,
    )


def select_pool(evaluations, scores, policy, retired_ids, *, isolation=None):
    """Unique greedy pool. Unusable correlations isolate a recipe, retaining N/V."""
    reject_b2_inputs({"evaluations": evaluations, "scores": scores}, "admission")
    if policy.document["version"] in (
        "v1.0.1",
        "v2.0.0",
        "v3.0.0",
    ) and not policy.document.get("runtime_consumable"):
        raise ValueError("pool.S2_unavailable_not_empty")
    expected = policy.document["variance_layers"]["family_definitions"][
        "candidate_members"
    ]
    if policy.document["version"] in ("v2.0.0", "v3.0.0"):
        from .isolation import verify_rank_receipt

        if not isolation or set(scores) != set(expected):
            raise ValueError("pool.v2_isolation_receipts_missing")
        dates = set(isolation["rank_receipts"])
        if not dates or any(set(scores[k]) != dates for k in expected):
            raise ValueError("pool.v2_score_dates_mismatch")
        for d, receipt in isolation["rank_receipts"].items():
            verify_rank_receipt(receipt, isolation["manifest"], policy)
            if d != receipt["day"]["date"] or any(
                scores[k][d] != receipt["scores"][k] for k in expected
            ):
                raise ValueError("pool.v2_score_membership_or_values_mismatch")
    if set(evaluations) != set(expected) or any(
        any(not finite(m.get(k)) for k in ("mean", "sharpe", "dsr"))
        for m in evaluations.values()
    ):
        raise ValueError("pool.S2_unavailable_not_empty")
    import re

    p = policy.profile["signal_params"]
    cap = float(re.search(r">([0-9.]+)$", p["redundancy"])[1])
    eligible = sorted(
        (
            k
            for k, m in evaluations.items()
            if k not in retired_ids
            and m["mean"] > p["train_mean_active_x2_min_exclusive"]
            and m["dsr"] >= p["train_dsr_min"]
        ),
        key=lambda k: (-evaluations[k]["mean"], k),
    )
    pool, isolated = [], {}
    for k in eligible:
        if len(pool) >= p["pool_size_max"]:
            break
        try:
            a = scores[k]
            if not a:
                raise ValueError("pool.scores_missing")
            for row in a.values():
                if (
                    len(row) < p["min_eligible_stocks"]
                    or not all(finite(x) for x in row.values())
                    or max(row.values()) == min(row.values())
                ):
                    raise ValueError("pool.scores_incomplete_or_constant")
            redundant = False
            for other in pool:
                b = scores[other]
                if set(a) != set(b):
                    raise ValueError("pool.score_calendar_mismatch")
                correlations = []
                for d in sorted(a):
                    if set(a[d]) != set(b[d]):
                        raise ValueError("pool.score_panel_incomplete")
                    symbols = sorted(a[d])
                    x, y = [a[d][t] for t in symbols], [b[d][t] for t in symbols]
                    mx, my = math.fsum(x) / len(x), math.fsum(y) / len(y)
                    xx, yy = (
                        math.fsum((v - mx) ** 2 for v in x),
                        math.fsum((v - my) ** 2 for v in y),
                    )
                    correlations.append(
                        math.fsum((u - mx) * (v - my) for u, v in zip(x, y))
                        / math.sqrt(xx * yy)
                    )
                if abs(math.fsum(correlations) / len(correlations)) > cap:
                    redundant = True
                    break
            if not redundant:
                pool.append(k)
        except (
            ValueError,
            KeyError,
            TypeError,
            ZeroDivisionError,
            OverflowError,
        ) as exc:
            isolated[k] = (
                str(exc)
                if isinstance(exc, ValueError)
                else "pool.correlation_unavailable"
            )
    return {"pool": pool, "isolated": isolated}


def run_train_pipeline(
    *,
    policy,
    ledger,
    run_id,
    context,
    registry,
    proposals,
    probe,
    build_meta,
    self_report_n,
    calibrate=None,
):
    """Callbacks receive train data through their closure; no OOS argument exists.

    probe(proposal, profile) -> {returns, scores}; calibrate() -> mature labels;
    build_meta(pool, frozen_calibration) -> {returns}.
    Errors retain every proposal and stop downstream work; no rescue/reselection.
    """
    if not isinstance(context, dict):
        return dict(
            candidate=None, meta=None, reason="arm_n.arm_tag_missing_or_invalid"
        )
    tag = label(context)
    # Omission alone retains the frozen pending reason; explicit bad values refuse.
    if tag is not MISSING and not valid_arm(tag):
        return dict(
            candidate=None, meta=None, reason="arm_n.arm_tag_missing_or_invalid"
        )
    if policy.document.get("runtime_consumable", False) is False:
        return {
            "candidate": None,
            "meta": None,
            "reason": "dsr.runtime_bindings_pending",
        }
    if not valid_arm(tag):  # D_TRAIN_LABEL_GUARD: independent of frozen runtime.
        return dict(
            candidate=None, meta=None, reason="arm_n.arm_tag_missing_or_invalid"
        )
    preflight_n = _n_snapshot(ledger, self_report_n, policy, arm_tag=tag)
    if not preflight_n["n_complete"]:
        return dict(
            candidate=None,
            meta=None,
            reason="ledger.factor_arm_projection_missing"
            if tag == "EVO883_FACTOR"
            else "ledger_history_incomplete",
        )
    context, proposals, registry = deepcopy((context, proposals, registry))
    proposal_hash = digest(proposals)
    key = f"v02/{run_id}/{context.get('fold_id')}"
    if ledger.recorded(key + "/S0") is not None:
        raise ValueError("pipeline.run_already_consumed")
    p = policy.document
    families = p["variance_layers"]["family_definitions"]
    ids = families["candidate_members"]
    ledger.record(
        key + "/S0",
        {
            "context": context,
            "proposals": proposals,
            "registry_sha256": None if registry is None else registry["sha256"],
            "families": families,
            **policy.binding,
        },
    )
    try:
        validate_context(dict(context, run_id=run_id), policy)
        genesis = ledger.snapshot()["genesis"]
        if (
            genesis.get("conventions_sha256") != policy.raw_sha256
            or type(genesis.get("prior_n")) is not int
            or genesis["prior_n"] < (p["genesis"]["seed_min_N"] or 0)
        ):
            raise ValueError("dsr.ledger_seed_or_conventions_not_bound")
        if [x["id"] for x in proposals] != ids:
            raise ValueError("pipeline.fixed_candidate_membership_mismatch")
        # Membership is sealed before any performance; the future meta ROLE is
        # pinned above but is not an attempted meta until S3 actually registers it.
        attempts = [f"{run_id}/candidate/{x}" for x in ids]
        ledger.declare_family(run_id, attempts, basis=p["N"]["DSR_SR_basis"])
        for aid, proposal in zip(attempts, proposals):
            ledger.begin(aid, proposal, context={"run_id": run_id}, replay=False)
        evaluations, scores, errors = {}, {}, []
        for aid, proposal in zip(attempts, proposals):
            try:
                observation = probe(proposal, p["variance_layers"]["probe_profile"])
                if len(observation["returns"]) != len(context["train_calendar"]):
                    raise ValueError("pipeline.probe_return_window_mismatch")
                m = moments(observation["returns"], policy)
                if not observation["scores"] or any(
                    d not in context["train_calendar"] for d in observation["scores"]
                ):
                    raise ValueError("pipeline.probe_scores_missing_or_outside_train")
                scores[proposal["id"]] = observation["scores"]
                evaluations[proposal["id"]] = m
                ledger.finish(
                    aid,
                    "success",
                    sharpe=m["sharpe"],
                    details={
                        "observation": observation,
                        "sharpe_scale": "daily",
                        "profile": p["variance_layers"]["probe_profile"]["id"],
                    },
                )
            except Exception as exc:
                reason = (
                    str(exc) if isinstance(exc, ValueError) else "pipeline.probe_failed"
                )
                errors.append(reason)
                ledger.finish(aid, "failed", reason=reason)
        if digest(proposals) != proposal_hash:
            raise ValueError("pipeline.proposals_mutated")
        if errors:
            ledger.record(
                key + "/S1",
                {"evaluations": evaluations, "errors": errors, "calibration": None},
            )
            if "wf.full_history_or_mutated_fit_rejected" in errors:
                raise ValueError("wf.full_history_or_mutated_fit_rejected")
            raise ValueError("pipeline.candidate_family_incomplete")
        if calibrate is None:
            raise ValueError("gain.calibration_missing")
        from .execution import calibrate_gain

        labels = calibrate()
        calibration = calibrate_gain(
            labels["rows"], labels["matured_dates"], conventions=policy, context=context
        )
        ledger.record(
            key + "/S1",
            {"evaluations": evaluations, "errors": [], "calibration": calibration},
        )
        if any(
            e["event"] == "begin"
            and e.get("kind") == "candidate"
            and e.get("context", {}).get("run_id") == run_id
            and e["attempt_id"] not in attempts
            for e in ledger.snapshot()["events"]
        ):
            raise ValueError("pipeline.undeclared_candidate_attempt")
        n_candidate = _n_snapshot(ledger, self_report_n, policy, arm_tag=tag)
        if (
            policy.document["version"] in ("v2.0.0", "v3.0.0")
            and not n_candidate["n_complete"]
        ):
            raise ValueError("ledger.factor_arm_projection_missing")
        candidate_v = _layer(
            [evaluations[x]["sharpe"] for x in ids],
            "candidate",
            registry,
            dict(context, run_id=run_id),
            policy,
        )
        candidate_dsr = {
            k: _dsr(m, candidate_v["trials_variance"], n_candidate, policy)
            for k, m in evaluations.items()
        }
        if not n_candidate["n_complete"] or not ledger.snapshot()["certifiable"]:
            raise ValueError("ledger_history_incomplete")
        retired = context["retired_ids"]
        if (
            not isinstance(retired, list)
            or len(retired) != len(set(retired))
            or not set(retired).issubset(ids)
        ):
            raise ValueError("pool.retirement_state_invalid")
        selection = select_pool(
            candidate_dsr, scores, policy, retired, isolation=context.get("isolation")
        )
        pool = selection["pool"]
        candidate = {
            **selection,
            "evaluations": candidate_dsr,
            "family_sha256": digest(ids),
            "family_attempt_ids": attempts,
            "reference_registry_sha256": registry["sha256"],
            "variance_scale": policy.document["units"]["V"],
            **candidate_v,
            **n_candidate,
        }
        ledger.record(key + "/S2", candidate)
        meta_id = f"{run_id}/meta/{families['meta_members'][-1]}"
        ledger.begin(
            meta_id,
            {"policy_role": families["meta_members"][-1], "pool": pool},
            kind="meta",
            context={"run_id": run_id},
            replay=False,
        )
        n_meta = _n_snapshot(ledger, self_report_n, policy, arm_tag=tag)
        ledger.record(key + "/S3", {"meta_attempt_id": meta_id, "pool": pool, **n_meta})
        try:
            observation = build_meta(tuple(pool), deepcopy(calibration))
            if len(observation["returns"]) != len(context["train_calendar"]):
                raise ValueError("pipeline.meta_return_window_mismatch")
            m = moments(observation["returns"], policy)
            ledger.finish(
                meta_id,
                "success",
                sharpe=m["sharpe"],
                details={
                    "observation": observation,
                    "sharpe_scale": "daily",
                    "profile": p["variance_layers"]["independent_reference"][
                        "meta_reference_profile"
                    ],
                },
            )
        except Exception as exc:
            reason = str(exc) if isinstance(exc, ValueError) else "pipeline.meta_failed"
            ledger.finish(meta_id, "failed", reason=reason)
            raise ValueError(reason) from exc
        meta_v = _layer(
            [evaluations[x]["sharpe"] for x in ids] + [m["sharpe"]],
            "meta",
            registry,
            dict(context, run_id=run_id),
            policy,
        )
        meta = {
            **_dsr(m, meta_v["trials_variance"], n_meta, policy),
            **meta_v,
            **n_meta,
            **policy.binding,
            "stage_ledger_hash": ledger.snapshot()["n_ledger_hash"],
            "family_sha256": digest(families["meta_members"]),
            "probe_attempt_ids": attempts,
            "meta_attempt_id": meta_id,
            "reference_registry_sha256": registry["sha256"],
            "variance_scale": policy.document["units"]["V"],
        }
        ledger.record(key + "/S4", meta)
        return {"candidate": candidate, "meta": meta, "reason": None}
    except (ValueError, KeyError, TypeError, OverflowError, ZeroDivisionError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) else "pipeline.input_invalid"
        ledger.record(key + "/failure", {"reason": reason})
        return {
            "candidate": ledger.recorded(key + "/S2"),
            "meta": None,
            "reason": reason,
        }


def evaluate(request, ledger, policy, *, arm_tag=MISSING):
    from .statistics import dsr_eval

    return dsr_eval(request, ledger, conventions=policy, arm_tag=arm_tag)


def evaluate_arm(request, ledger, policy, *, arm_tag=MISSING):
    from .statistics import dsr_eval_arm

    return dsr_eval_arm(request, ledger, conventions=policy, arm_tag=arm_tag)


def oos_dsr(returns, fold_receipts, expected_fold_ids, n_snapshot, policy):
    """No OOS-generated controls: V is max of ALL frozen train meta V values."""
    if expected_fold_ids != [f["fold_id"] for f in policy.fold_manifest()["folds"]]:
        raise ValueError("wf.all_original_folds_required")
    if policy.document["version"] in (
        "v1.0.1",
        "v2.0.0",
        "v3.0.0",
    ) and not policy.document.get("runtime_consumable"):
        raise ValueError("dsr.runtime_bindings_pending")
    if (
        set(fold_receipts) != set(expected_fold_ids)
        or not fold_receipts
        or not n_snapshot["n_complete"]
    ):
        raise ValueError("dsr.oos_fold_v_or_complete_n_missing")
    values = []
    for fid in expected_fold_ids:
        r = fold_receipts[fid]
        if (
            r["conventions_sha256"] != policy.raw_sha256
            or not is_sha(r.get("stage_ledger_hash"))
            or not finite(r.get("trials_variance"))
            or r["trials_variance"] < 0
        ):
            raise ValueError("dsr.oos_fold_v_invalid")
        values.append(r["trials_variance"])
    v = max(values)
    return dict(
        _dsr(moments(returns, policy), v, n_snapshot, policy),
        trials_variance=v,
        certifiable=False,
    )
