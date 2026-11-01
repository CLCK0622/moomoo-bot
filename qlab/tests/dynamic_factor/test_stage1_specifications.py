"""Original 20 first-stage and 18 T1 specifications, through real receivers."""

import pytest
from reception_v2_driver import run_case

CASES = (
    [f"N-01-{i:02}" for i in range(1, 7)]
    + [f"N-02-{i:02}" for i in range(1, 8)]
    + [f"N-03-{i:02}" for i in range(1, 8)]
    + [f"T1-{i:02}" for i in range(1, 10)]
    + [f"A-{i:02}" for i in range(1, 10)]
)


@pytest.mark.parametrize("case", CASES)
def test_stage1_specification(case, tmp_path):
    result = run_case(case, tmp_path)
    assert result["status"] == "PASS"
    assert result["production_installation"] is False
