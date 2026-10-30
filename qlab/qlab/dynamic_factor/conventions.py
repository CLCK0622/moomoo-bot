"""Read/hash EVO-883's draft; never execute Python supplied by a JSON file."""

from __future__ import annotations

import ast
import json
import math
import operator
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist

from .contract import sha256

FIXTURES = Path(__file__).parent / "fixtures"


class ConventionConflict(ValueError):
    pass


def arithmetic(expression, variables):
    """Small numeric AST interpreter for the two published DSR expressions."""
    binary = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
    }
    functions = {
        "max": max,
        "sqrt": math.sqrt,
        "exp": math.exp,
        "norm_ppf": NormalDist().inv_cdf,
        "norm_cdf": NormalDist().cdf,
    }

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.Name) and node.id in variables:
            return variables[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in binary:
            return binary[type(node.op)](visit(node.left), visit(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        comparisons = {
            ast.Lt: operator.lt,
            ast.LtE: operator.le,
            ast.Gt: operator.gt,
            ast.GtE: operator.ge,
        }
        if (
            isinstance(node, ast.Compare)
            and len(node.ops) == 1
            and type(node.ops[0]) in comparisons
        ):
            return comparisons[type(node.ops[0])](
                visit(node.left), visit(node.comparators[0])
            )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in functions
            and len(node.args) == (2 if node.func.id == "max" else 1)
            and not node.keywords
        ):
            return functions[node.func.id](*(visit(arg) for arg in node.args))
        raise ConventionConflict("conventions.unsupported_numeric_expression")

    if len(expression) > 1000:
        raise ConventionConflict("conventions.expression_too_long")
    return visit(ast.parse(expression, mode="eval"))


@dataclass(frozen=True)
class Conventions:
    raw_document: bytes
    raw_sha256: str
    calendar: tuple
    raw_date_manifest: bytes
    seed_raw: bytes
    raw_profile: bytes = b""

    @property
    def document(self):
        return json.loads(self.raw_document)

    @property
    def date_manifest(self):
        return json.loads(self.raw_date_manifest)

    @property
    def seed_rows(self):
        return tuple(
            json.loads(line) for line in self.seed_raw.decode().splitlines() if line
        )

    @property
    def binding(self):
        binding = {
            "conventions_version": self.document["version"],
            "conventions_sha256": self.raw_sha256,
            "conventions_status": self.document["status"],
        }
        if self.raw_profile:
            binding["profile_sha256"] = sha256(self.raw_profile)
            binding["prereg_sha256"] = sha256(self.raw_profile)
            binding["prereg_version"] = self.profile["version"]
            binding["common_profile_sha256"] = self.document["variance_layers"][
                "probe_profile"
            ]["common_profile_sha256"]
        return binding

    @property
    def annual_periods(self):
        return int(
            re.fullmatch(
                r"divide_sqrt(\d+)", self.document["units"]["annual_to_daily_SR"]
            )[1]
        )

    @property
    def template_horizon(self):
        return int(
            re.search(r"(\d+)_day_template_path", self.document["label_boundary"])[1]
        )

    @property
    def profile(self):
        return json.loads(self.raw_profile)

    @property
    def family_size(self):
        if "variance_layers" in self.document:
            return len(
                self.document["variance_layers"]["family_definitions"]["meta_members"]
            )
        match = re.fullmatch(
            r"all_(\d+)_primary_recipes_plus_single_meta_combination_per_fold_fixed_before_performance",
            self.document["V"]["family"],
        )
        return int(match[1]) + 1

    def fold_manifest(self):
        p = self.document
        # The offset includes the next-open entry; the 20-session path matures at t+21.
        maturity = max(
            p["labels"]["primary_exit_open_offset_from_signal"],
            p["labels"]["diagnostic_exit_open_offset_from_signal"],
            p["labels"]["entry_open_offset_from_signal"] + self.template_horizon,
        )
        index = {d: i for i, d in enumerate(self.calendar)}
        folds = []
        for declared in self.date_manifest["folds"]:
            start, end = declared["train_dates_inclusive"]
            eligible_end = self.calendar[index[end] - maturity]
            folds.append(
                {
                    "fold_id": str(declared["fold_id"]),
                    "train_start": start,
                    "train_end": eligible_end,
                    "history_end": end,
                    "test_start": declared["test_dates_inclusive"][0],
                    "test_end": declared["test_dates_inclusive"][1],
                }
            )
        return {
            "calendar": list(self.calendar),
            "label_horizon": p["labels"]["primary_exit_open_offset_from_signal"],
            "label_entry_offset": p["labels"]["entry_open_offset_from_signal"],
            "template_path_offset": p["labels"]["entry_open_offset_from_signal"]
            + self.template_horizon,
            "embargo": p["folds"]["gap_days"],
            "folds": folds,
            **self.binding,
        }

    def bind(self, report):
        report.update(self.binding)
        report["assumptions"] += self.document["assumptions"]
        # v0.1 is explicitly not a strategy freeze, regardless of diagnostic numbers.
        report["certifiable"] = False
        return report


def load_conventions(
    path=FIXTURES / "conventions-v1.0.1.json", *, expected_sha256=None
):
    raw = Path(path).read_bytes()
    provenance = json.loads((FIXTURES / "provenance.json").read_bytes())
    if expected_sha256 is None:
        expected_sha256 = provenance.get(
            Path(path).name, provenance["conventions-v1.0.1.json"]
        )["sha256"]
    if sha256(raw) != expected_sha256:
        raise ConventionConflict("conventions.hash_mismatch")
    p = json.loads(raw)
    authority = provenance.get("conventions-" + p["version"] + ".json")
    if authority is None or sha256(raw) != authority["sha256"]:
        raise ConventionConflict("conventions.authority_hash_mismatch")
    if p["schema"] in (
        "EVO883.executable-conventions.v0.2",
        "EVO883.executable-conventions.v1.0.1",
    ):
        profile_raw = validate_v02(p, provenance)
        # Reuse frozen date/seed/scale checks; v1 changes profile/fees/actions.
        legacy = load_conventions(FIXTURES / "conventions-v0.1.json")
        for key in (
            "genesis",
            "N_counting",
            "folds",
            "label_boundary",
            "units",
            "DSR",
        ):
            if p[key] != legacy.document[key]:
                raise ConventionConflict(
                    "conventions.v02_unchanged_field_conflict:" + key
                )
        if p["benchmark_missing_days"] != dict(
            legacy.document["benchmark_missing_days"],
            local_calendar_condition_accepted_in_review=True,
        ):
            raise ConventionConflict("conventions.benchmark_rule_conflict")
        return Conventions(
            raw,
            sha256(raw),
            legacy.calendar,
            legacy.raw_date_manifest,
            legacy.seed_raw,
            profile_raw,
        )
    if p["schema"] != "EVO883.executable-conventions.v0.1":
        raise ConventionConflict("conventions.schema_unsupported")
    n, v, g, f = p["N"], p["V"], p["genesis"], p["folds"]
    if (
        p["DSR"]["threshold"] != n["DSR_min"]
        or n["global_EVO8_50_20_modified"]
        or n["V_scalar_weighted_fallback"] != v["scalar_weighted_variance_fallback"]
        or not n["independent_V_required"]
        or n["supersedes_deletes_prior_attempt"]
        or n["N_seed_sha256"] != g["sha256"]
        or n["N_seed_min"] != g["seed_min_N"]
        or n["N_seed_source_commit"] != g["commit"]
        or n["N_seed_completeness_certified"] != g["complete_current_N_verified"]
        or n["N_seed_historical_sharpes_usable_as_active_V"]
        or v["historical_seed_raw_strategy_SRs_are_comparable_active_SRs"]
    ):
        raise ConventionConflict("conventions.internal_conflict")
    if not (n["append_only_attempts"] and n["failed_nan_duplicate_attempts_preserved"]):
        raise ConventionConflict("conventions.attempt_counting_conflict")
    policy_strings = {
        p["N_counting"][
            "structural_prelabel_rejection"
        ]: "record_proposed_and_conservatively_attempted",
        p["N_counting"]["supersedes"]: "link_only_never_delete_or_remove_prior_count",
        p["N_counting"][
            "mandatory_x1_x2_and_three_benchmarks"
        ]: "one_frozen_attempt_multi_readouts_not_six_optimizer_trials",
        p["N_counting"][
            "byte_identical_delivery_retry_same_attempt_id"
        ]: "idempotent_no_new_performance_count",
        v[
            "family_variance"
        ]: "sample_variance_ddof1_of_complete_finite_daily_active_SR_family",
        v[
            "independent_floor"
        ]: "sample_variance_ddof1_full_comparable_daily_active_SR_union_excluding_own_run",
        v[
            "missing_failed_SR"
        ]: "retain_entry_do_not_impute0_do_not_select_winners_return_unavailable",
        p["benchmark_missing_days"][
            "align_rule"
        ]: "longest_common_complete_suffix_after_last_missing_reference_session_all_QQQ_SPY_and_validated_VTI_dates_identical",
    }
    if any(actual != supported for actual, supported in policy_strings.items()):
        raise ConventionConflict("conventions.rule_unsupported")
    n_effective = (
        n["V_effective"]
        .replace("full_family_daily_SR_sample_variance", "family_variance")
        .replace(
            "independent_authoritative_daily_SR_sample_variance", "independent_floor"
        )
    )
    if ast.dump(ast.parse(n_effective, mode="eval")) != ast.dump(
        ast.parse(v["effective"], mode="eval")
    ):
        raise ConventionConflict("conventions.V_aggregation_conflict")
    sample_ddof = re.fullmatch(r"ddof(\d+)", p["DSR"]["sample_sd"])
    if (
        not sample_ddof
        or sample_ddof[1]
        != re.search(r"sample_variance_ddof(\d+)", v["family_variance"])[1]
    ):
        raise ConventionConflict("conventions.variance_ddof_conflict")
    date_raw = (FIXTURES / "calendar-folds-v0.1.json").read_bytes()
    calendar_raw = (FIXTURES / "common-calendar-v0.1.txt").read_bytes()
    seed_raw = (FIXTURES / "historical-seed-e51f8023.jsonl").read_bytes()
    if sha256(date_raw) != f["date_manifest_sha256"] or sha256(seed_raw) != g["sha256"]:
        raise ConventionConflict("conventions.bound_artifact_hash_mismatch")
    dates = json.loads(date_raw)
    if sha256(calendar_raw) != dates["common_calendar_sha256"]:
        raise ConventionConflict("conventions.calendar_hash_mismatch")
    calendar = tuple(calendar_raw.decode().splitlines())
    seed = tuple(json.loads(line) for line in seed_raw.decode().splitlines() if line)
    if [
        {"run_id": r["run_id"], "n_trials_total": r["n_trials_total"]} for r in seed
    ] != g["seed_runs"] or sum(r["n_trials_total"] for r in seed) != g["seed_min_N"]:
        raise ConventionConflict("conventions.seed_identity_mismatch")
    if len(calendar) != dates["n_sessions"] or len(dates["folds"]) != f["fold_count"]:
        raise ConventionConflict("conventions.fold_count_mismatch")
    for row in dates["folds"]:
        k = row["fold_id"]
        b = arithmetic(f["b_k"], {"k": k})
        lo, hi = [
            arithmetic(e, {"b_k": b}) for e in f["train_inclusive"][1:-1].split(",")
        ]
        a, z = [arithmetic(e, {"b_k": b}) for e in f["test_inclusive"][1:-1].split(",")]
        if (
            row["train_index_inclusive"] != [lo, hi]
            or row["test_index_inclusive"] != [a, z]
            or hi - lo + 1 != f["train_days"]
            or a - hi - 1 != f["gap_days"]
            or z - a + 1 != f["test_days"]
            or row["train_dates_inclusive"] != [calendar[lo], calendar[hi]]
            or row["test_dates_inclusive"] != [calendar[a], calendar[z]]
            or not arithmetic(f["valid_fold"], {"b_k": b, "M": len(calendar)})
            or lo < f["warmup_days"]
        ):
            raise ConventionConflict("conventions.fold_boundary_conflict")
    if (
        len(dates["folds"]) < f["minimum_complete_folds"]
        or p["labels"]["primary_exit_open_offset_from_signal"]
        != p["labels"]["entry_open_offset_from_signal"]
        + p["labels"]["primary_horizon_days"]
        or p["labels"]["diagnostic_exit_open_offset_from_signal"]
        != p["labels"]["entry_open_offset_from_signal"]
        + p["labels"]["diagnostic_horizon_days"]
    ):
        raise ConventionConflict("conventions.label_or_minimum_fold_conflict")
    sr_scale = re.fullmatch(r"divide_sqrt(\d+)", p["units"]["annual_to_daily_SR"])
    v_scale = re.fullmatch(r"divide(\d+)_exactly_once", p["units"]["annual_to_daily_V"])
    if not sr_scale or not v_scale or sr_scale[1] != v_scale[1]:
        raise ConventionConflict("conventions.scale_conflict")
    return Conventions(raw, sha256(raw), calendar, date_raw, seed_raw)


def validate_v02(p, provenance):
    """Verify the companion profile, common hash, and the reviewed acyclic contract."""
    from .contract import digest

    profile_file = (
        "prereg-v1.json" if p["version"] == "v1.0.1" else "prereg-v1-draft2.json"
    )
    raw = (FIXTURES / profile_file).read_bytes()
    if sha256(raw) != provenance[profile_file]["sha256"]:
        raise ConventionConflict("conventions.profile_hash_mismatch")
    profile = json.loads(raw)
    for key in ("initialization", "gain_model", "variance_layers", "price_basis_gate"):
        if p[key] != profile[key]:
            raise ConventionConflict("conventions.profile_conflict:" + key)
    if (
        p["N"] != profile["gate_thresholds"]
        or p["DSR"]["threshold"] != p["N"]["DSR_min"]
    ):
        raise ConventionConflict("conventions.internal_conflict")
    v = p["variance_layers"]
    recipe = v["common_profile_hash_recipe"]
    common = {k: profile[k] for k in recipe["direct_root_keys"]}
    for dest, path in recipe["scalar_key_paths"].items():
        obj = profile
        for part in path.split("."):
            obj = obj[part]
        common[dest] = obj
    common.update(recipe["constant_fields"])
    if (
        digest(common) != v["probe_profile"]["common_profile_sha256"]
        or digest(common)
        != v["independent_reference"]["required_common_profile_sha256"]
    ):
        raise ConventionConflict("conventions.common_profile_hash_mismatch")
    if [x["id"] for x in v["steps"]] != ["S0", "S1", "S2", "S3", "S4"] or [
        x["depends_on"] for x in v["steps"]
    ] != [[], ["S0"], ["S1"], ["S2"], ["S1", "S3"]]:
        raise ConventionConflict("conventions.v02_stage_conflict")
    families = v["family_definitions"]
    if (
        families != profile["family"]
        or families["meta_members"][:-1] != families["candidate_members"]
        or v["meta_results_feedback_to_candidate_admission"]
    ):
        raise ConventionConflict("conventions.v02_family_conflict")
    if (
        p["V"]["candidate_formula"] != v["candidate_V"]
        or p["V"]["meta_formula"] != v["meta_V"]
        or p["N"]["V_effective"]
        != {
            "candidate": "variance_layers.candidate_V",
            "meta": "variance_layers.meta_V",
        }
    ):
        raise ConventionConflict("conventions.V_aggregation_conflict")
    return raw
