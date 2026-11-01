"""Descriptor/assertion migration, never old-nine-group receipt conversion."""

from qlab.dynamic_factor.authority_install_receipt import verify_installation_readonly
from contract_adapters_v3 import _adapt


def adapt_v2_n03(case_id):
    result = _adapt(
        case_id,
        "N-03",
        7,
        verify_installation_readonly,
        "EVO884.InstalledAuthorityReceipt/v3.1",
    )
    result["assertion_pointers"] = dict(
        original_twelve_groups="/details/installation_fields",
        original_trusted_validation="/details/trusted_validation",
        original_summary="/details/verified_summary",
    )
    return result
