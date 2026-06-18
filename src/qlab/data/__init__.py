"""Data ingest layer: abstract :class:`DataSource` + the fixture adapter.

The moomoo OpenD-backed quote source lives in :mod:`qlab.brokers.moomoo` (with the
trade gateway and safety guardrails), since it is part of the live broker layer.
"""

from .base import Bar, DataSource
from .fixture import FixtureDataSource

__all__ = ["Bar", "DataSource", "FixtureDataSource"]
