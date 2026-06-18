"""Plugin接入点 for external candidate strategies (e.g. ``quant-strategies``).

EVO-13 §4: the skeleton must be able to take an external candidate as a plugin and
re-run it through qlab's own validation — **without trusting any performance claim
the source repo makes** (e.g. quant-strategies' "≈45% 年化"). A plugin only has to
conform to the existing :class:`qlab.strategy.base.Strategy` interface; it is then
fed to ``pipeline.evaluate_candidate`` and judged solely by cost×2 / walk-forward /
the EVO-10/12/14 门禁.

Two ways to plug in:
- :func:`load_strategy` — resolve ``"package.module:attr"`` to a Strategy (class,
  instance, or zero-arg factory) defined in an installed/importable package.
- :class:`FunctionStrategy` — wrap a plain ``bars -> list[float]`` weight function.

No external code is imported until you ask for it, and the loader validates the
object really is a Strategy before handing it to the engine.
"""

from __future__ import annotations

import importlib
from typing import Callable

from ..data.base import Bar
from .base import Strategy


class FunctionStrategy(Strategy):
    """Adapt a ``bars -> list[float]`` target-weight function to a Strategy.

    Useful when an external candidate exposes a signal function rather than a class.
    The function MUST be causal (element i uses only bars[0..i]); qlab does not and
    cannot verify causality, so document it on the plugin side.
    """

    def __init__(self, name: str, fn: Callable[[list[Bar]], list[float]]) -> None:
        self.name = name
        self._fn = fn

    def target_weights(self, bars: list[Bar]) -> list[float]:
        weights = self._fn(bars)
        if len(weights) != len(bars):
            raise ValueError("plugin strategy must return one weight per bar")
        return [self._clamp(float(w)) for w in weights]


def _validate(obj: object, label: str) -> Strategy:
    if isinstance(obj, Strategy):
        return obj
    # Duck-typed acceptance: anything with a callable target_weights is wrapped so
    # downstream code still sees a real Strategy instance.
    tw = getattr(obj, "target_weights", None)
    if callable(tw):
        name = getattr(obj, "name", label)
        return FunctionStrategy(name, lambda bars: tw(bars))
    raise TypeError(
        f"plugin '{label}' is not a Strategy and has no target_weights(bars) method"
    )


def load_strategy(target: str, /, **params) -> Strategy:
    """Resolve ``"package.module:attr"`` to a validated :class:`Strategy`.

    ``attr`` may be a Strategy subclass (instantiated with ``**params``), an already
    -built Strategy instance, or a zero/kwargs factory returning one. Raises a clear
    error if the spec is malformed or the result is not a Strategy.
    """
    if ":" not in target:
        raise ValueError("target must be 'package.module:attr'")
    module_path, _, attr = target.partition(":")
    module = importlib.import_module(module_path)
    try:
        obj = getattr(module, attr)
    except AttributeError as exc:
        raise ImportError(f"'{attr}' not found in '{module_path}'") from exc

    if isinstance(obj, type) and issubclass(obj, Strategy):
        return _validate(obj(**params), target)
    if callable(obj) and not isinstance(obj, Strategy):
        return _validate(obj(**params) if params else obj(), target)
    return _validate(obj, target)
