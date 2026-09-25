#!/usr/bin/env bash
# bootstrap_env.sh — recreate the PERSISTENT Qlib generator environment.
#
# Layer discipline (工部 env convention): the Python interpreter + venv live in
# the persistent user layer (~/.local, ~/.venvs), NOT in a task workdir, so they
# survive across tasks. Re-running this is idempotent and safe.
#
#   uv        -> ~/.local/bin/uv            (same layer as node/pnpm)
#   CPython   -> ~/.local/share/uv/python   (uv-managed, persistent cache)
#   venv      -> ~/.venvs/qlab-py312        (pyqlib==0.9.7, CPU-only)
#
# Usage:  bash tools/qlib_gen/bootstrap_env.sh
set -euo pipefail

PY_VERSION="3.12"
VENV="$HOME/.venvs/qlab-py312"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCK="$HERE/requirements-qlib-lock.txt"
export PATH="$HOME/.local/bin:$PATH"

echo "==> [1/4] uv"
if ! command -v uv >/dev/null 2>&1; then
  echo "    installing uv into ~/.local/bin (persistent)"
  export UV_INSTALL_DIR="$HOME/.local/bin"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
uv --version

echo "==> [2/4] CPython $PY_VERSION (persistent, uv-managed)"
uv python install "$PY_VERSION"

echo "==> [3/4] venv $VENV"
mkdir -p "$HOME/.venvs"
uv venv --python "$PY_VERSION" "$VENV"
VP="$VENV/bin/python"

echo "==> [4/4] deps"
if [[ -f "$LOCK" ]]; then
  echo "    from lock: $LOCK"
  uv pip install --python "$VP" -r "$LOCK"
else
  echo "    lock absent, using requirements-qlib.txt"
  uv pip install --python "$VP" -r "$HERE/requirements-qlib.txt"
fi

echo "==> verify"
"$VP" - <<'PY'
import qlib, numpy, pandas
print(f"    qlib {qlib.__version__} | numpy {numpy.__version__} | pandas {pandas.__version__}")
try:
    import torch; print("    WARNING: torch present (expected CPU-only)")
except ImportError:
    print("    torch absent (CPU-only OK)")
from qlib.contrib.data.handler import Alpha158, Alpha360  # noqa: F401
print("    Alpha158/Alpha360 handlers OK")
PY
echo "==> done. Interpreter: $VP"
echo "    Run:  PYTHONPATH=\$PWD $VP -m tools.qlib_gen.factor_export --help"
