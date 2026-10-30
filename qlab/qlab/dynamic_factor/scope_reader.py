"""Market-file capability for the seven strategy roles, with no B2 capability."""

import json
from pathlib import Path

from .contract import sha256
from .input_scope import reject_b2_inputs


def read_strategy_inputs(root, bindings, dates, *, role, policy):
    reject_b2_inputs(bindings, role)
    root = Path(root).resolve()
    allowed = set(policy.profile["universe"]) | {
        policy.profile["portfolio"]["base_ticker"]
    }
    if not bindings or not set(bindings).issubset(allowed):
        raise ValueError("scope.market_symbol_not_whitelisted")
    result = {}
    for symbol, binding in sorted(bindings.items()):
        if binding.get("symbol") != symbol or binding.get("file") != symbol + ".json":
            raise ValueError("scope.market_file_not_whitelisted")
        path = root / binding["file"]
        if (
            path.is_symlink()
            or path.resolve().parent != root
            or path.stat().st_nlink != 1
        ):
            raise ValueError("scope.market_file_not_whitelisted")
        raw = path.read_bytes()
        if sha256(raw) != binding.get("sha256"):
            raise ValueError("scope.market_sha_mismatch")
        document = json.loads(raw)
        reject_b2_inputs(document, role)
        if set(document) != {"symbol", "rows"} or document["symbol"] != symbol:
            raise ValueError("scope.market_header_mismatch")
        if [r["date"] for r in document["rows"]] != list(dates):
            raise ValueError("scope.market_calendar_incomplete")
        result[symbol] = document["rows"]
    return result
