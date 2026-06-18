"""Model training / persistence abstraction.

A :class:`Model` is anything that can be ``fit`` on a bar history and then produce
per-bar signals via ``predict``. Persistence is JSON-based (human-auditable, no
pickle security footgun): subclasses expose their learned state through
``params()`` and rebuild from it via :meth:`from_params`. ``save`` / ``load_model``
round-trip a small envelope so a trained model can be reloaded in a later run.
"""

from __future__ import annotations

import abc
import json
import os

from ..data.base import Bar

_REGISTRY: dict[str, type[Model]] = {}


def register_model(cls: type[Model]) -> type[Model]:
    """Class decorator to make a model reloadable by ``kind`` from disk."""
    _REGISTRY[cls.kind] = cls
    return cls


class Model(abc.ABC):
    kind: str = "model"

    @abc.abstractmethod
    def fit(self, bars: list[Bar]) -> Model:
        """Learn parameters from ``bars`` and return self."""
        raise NotImplementedError

    @abc.abstractmethod
    def predict(self, bars: list[Bar]) -> list[float]:
        """Return one target weight per bar (no-lookahead, like a Strategy)."""
        raise NotImplementedError

    @abc.abstractmethod
    def params(self) -> dict:
        """Return JSON-serialisable learned state."""
        raise NotImplementedError

    @classmethod
    @abc.abstractmethod
    def from_params(cls, params: dict) -> Model:
        """Reconstruct an instance from :meth:`params` output."""
        raise NotImplementedError

    def save(self, path: str) -> str:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        envelope = {"kind": self.kind, "params": self.params()}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(envelope, fh, indent=2, sort_keys=True)
        return path


def load_model(path: str) -> Model:
    with open(path, encoding="utf-8") as fh:
        envelope = json.load(fh)
    kind = envelope["kind"]
    if kind not in _REGISTRY:
        raise KeyError(f"unknown model kind '{kind}'; import its module to register it")
    return _REGISTRY[kind].from_params(envelope["params"])
