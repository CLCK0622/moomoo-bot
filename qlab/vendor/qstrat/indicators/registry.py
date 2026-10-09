from __future__ import annotations
import importlib
import pkgutil
import inspect
from pathlib import Path
from typing import Any, Callable


class IndicatorRegistry:
    def __init__(self):
        self.indicators: dict[str, dict[str, Callable]] = {}
        self._discover()

    def _discover(self):
        indicators_dir = Path(__file__).parent
        for _, name, _ in pkgutil.iter_modules([str(indicators_dir)]):
            if name == "registry":
                continue
            module = importlib.import_module(f"indicators.{name}")
            if hasattr(module, "compute") and hasattr(module, "register_params"):
                self.indicators[name] = {
                    "compute": module.compute,
                    "register_params": module.register_params,
                }

    def collect_all_params(self, trial) -> dict[str, Any]:
        params = {}
        for name, funcs in self.indicators.items():
            indicator_params = funcs["register_params"](trial)
            params.update(indicator_params)
        return params

    def compute_all(self, df, params: dict[str, Any]):
        result = df.copy()
        for name, funcs in self.indicators.items():
            relevant_params = {}
            sig = inspect.signature(funcs["compute"])
            for p_name in sig.parameters:
                if p_name in ("df", "kwargs"):
                    continue
                if p_name in params:
                    relevant_params[p_name] = params[p_name]
            result = funcs["compute"](result, **relevant_params)
        return result
