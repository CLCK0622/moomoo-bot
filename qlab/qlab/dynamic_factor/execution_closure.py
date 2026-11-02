"""One explicit EXEC-CLOSURE binding; it grants no source or runtime credit.

This is the shared parameter boundary, not a second D1/D2 implementation.
C03/C04 own monetary projection/accounting; C06 owns only observed risk.
"""

from copy import deepcopy
from decimal import Context, ROUND_HALF_EVEN, localcontext
import json

from .contract import digest, sha256
from .reference_definition_v301 import ROOT


NAME = "EVO883-EXEC-CLOSURE-adopted-protocol-v0.1.0.json"
ADOPTED_SHA256 = "7677b123fa2fe573343fad3fe3f43887c5f5d2c0fd7c12d9a1de8bc625162e1b"
TEXT_SHA256 = "34f25ce19dcf8687f7068b62f751c83573a858997ab11fa0096794157f3a373f"
WITHDRAWN_SHA256 = "e3646dc3a1381e508e59b2adceb04d29b3ea357949065ce83728950a038653ec"
DRAFT_SHA256 = (
    "b1ff273b275366cdf2a88df71e719d756f205d57dc331dd64e7bd08b97bf1db5",
    "f03914b2def4bd841dd71ead1bbd793b99ef886891e1344e4169befa2f57c19c",
    "0b4fe7f20552cea5d22c5ed9a4f374c2cebecb961fabff2f4893c55c31c67863",
)


def adopted_execution_binding(*, expected_adoption_sha256):
    if expected_adoption_sha256 != ADOPTED_SHA256:
        raise ValueError("execution.formal_closure_adoption_required")
    try:
        raw = (ROOT / NAME).read_bytes()
        text = (ROOT / NAME.replace(".json", ".md")).read_bytes()
    except OSError as exc:
        raise ValueError("execution.formal_closure_adoption_missing") from exc
    if sha256(raw) != ADOPTED_SHA256 or sha256(text) != TEXT_SHA256:
        raise ValueError("execution.formal_closure_adoption_identity_mismatch")
    document = json.loads(raw)
    boundaries = document["adoption_boundaries"]
    return dict(
        schema="EVO884.ExecutionClosureBinding/v1",
        adoption_sha256=ADOPTED_SHA256,
        normative_text_sha256=TEXT_SHA256,
        rule_body_sha256=document["adopted_rules_full_body_sha256"],
        clause_sha256={
            k: sha256(v.encode("utf-8"))
            for k, v in document["adopted_rule_sections_verbatim"].items()
        },
        common_bindings=deepcopy(document["common_bindings"]),
        N1=dict(
            monetary_domain="canonical_decimal_exact_no_cent_quantization_no_epsilon",
            fee_context=dict(
                precision=28, rounding="ROUND_HALF_EVEN", Emin=-999999, Emax=999999
            ),
            fee_bridge="preserve_original_canonical_float_lexeme_shortest_roundtrip",
            compatibility_gate=boundaries[
                "N1_changed_accepted_expected_bytes_or_existing_formula"
            ],
        ),
        N2=dict(
            reference_model=boundaries["N2_reference_model"],
            execution_verified=boundaries["N2_execution_verified"],
            actual_forward="accepted_actual_receipts_only",
        ),
        N3=dict(
            research_only="sell_before_buy_immediate_cash",
            actual_forward="accepted_cash_availability_evidence_only",
            economic_effect_verified=boundaries["N3_V_effect_verified"],
        ),
        N4=dict(
            first_usable_check=boundaries["N4_index_explanation"]["first_usable_check"],
            first_possible_half=boundaries["N4_index_explanation"][
                "first_possible_active_to_half"
            ],
            solo_inherits_meta_lifecycle=boundaries[
                "N4_solo_inherits_meta_pool_lifecycle"
            ],
        ),
        N5=dict(
            close_order=[
                "account_and_reconcile",
                "NAV_age_peak_latch_once",
                "decay_and_fold",
                "M_origin_lock",
                "locked_next_open_only",
            ],
            new_fold_artifact=boundaries["N5_new_fold_artifact"],
            next_open_reselects_signal=boundaries["N5_next_open_reselects_signal"],
        ),
    )


def validate_execution_binding(binding):
    if type(binding) is not dict:
        raise ValueError("execution.closure_binding_required")
    expected = adopted_execution_binding(
        expected_adoption_sha256=binding.get("adoption_sha256")
    )
    if digest(binding) != digest(expected):
        raise ValueError("execution.closure_parameters_mismatch")
    return deepcopy(expected)


def fee_context(binding):
    """Isolate the original fee module; never change its formulas or outputs."""
    params = validate_execution_binding(binding)["N1"]["fee_context"]
    return localcontext(
        Context(
            prec=params["precision"],
            rounding=ROUND_HALF_EVEN,
            Emin=params["Emin"],
            Emax=params["Emax"],
        )
    )


def reference_model(binding, *, book_id, scope):
    bound = validate_execution_binding(binding)
    if scope != "independent_training":
        raise ValueError("execution.ideal_model_diagnostic_book_only")
    return dict(
        book_id=book_id,
        scope=scope,
        model=bound["N2"]["reference_model"],
        execution_verified=False,
        cash_availability_assumption=bound["N3"]["research_only"],
        adoption_sha256=bound["adoption_sha256"],
    )
