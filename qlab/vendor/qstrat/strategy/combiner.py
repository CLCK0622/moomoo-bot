from __future__ import annotations
from typing import Callable
import pandas as pd
from strategy.conditions import ALL_CONDITIONS


def build_entry_evaluator(params: dict) -> Callable[[pd.Series, dict], bool]:
    active_conditions = []
    for name, spec in ALL_CONDITIONS.items():
        if spec.get("always_on"):
            active_conditions.append(spec["fn"])
        elif params.get(spec.get("toggle_param"), False):
            active_conditions.append(spec["fn"])

    def evaluate(row: pd.Series, params: dict) -> bool:
        return all(cond(row, params) for cond in active_conditions)

    return evaluate
