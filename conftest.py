"""pytest bootstrap: make ``src/`` importable without an editable install.

pytest auto-loads this file before collecting tests. (For ``python -m unittest``,
run from the project root with ``-t .`` so ``tests/__init__.py`` runs first — see
the Makefile / README.)
"""

import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
