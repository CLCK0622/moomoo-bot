"""Test package init.

Make ``src/`` importable for plain ``python -m unittest`` runs (no install needed).
This runs before any ``tests.test_*`` submodule is imported, so ``import qlab``
works regardless of import ordering. pytest also honours ``pythonpath = ["src"]``
from pyproject.toml, so both runners work out of the box.
"""

import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
