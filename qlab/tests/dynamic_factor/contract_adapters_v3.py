"""Old specification descriptors only; no legacy receipt can mint authority."""

from qlab.dynamic_factor.reception_v2 import receive_arm_n, bind_formal_n


def _adapt(case_id, prefix, count, receiver, schema):
    if type(case_id) is not str or case_id not in {
        prefix + f"-{i:02}" for i in range(1, count + 1)
    }:
        raise ValueError("receipt.retired_specification_descriptor")
    return dict(
        case_id=case_id,
        receiver=receiver,
        root_schema=schema,
        legacy_result_input=False,
        formal_entrypoint_count=1,
    )


def adapt_v2_n01(case_id):
    return _adapt(case_id, "N-01", 6, receive_arm_n, "EVO884.NAcceptanceReceipt/v3")


def adapt_v2_n02(case_id):
    return _adapt(case_id, "N-02", 7, bind_formal_n, "EVO884.FormalNBinding/v3")
