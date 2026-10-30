"""Deterministic reports, including the actual imported tool source bytes."""

from pathlib import Path

from qlab.dynamic_factor.contract import digest, result, sha256
from qlab.dynamic_factor.conventions import load_conventions

ASSUMPTIONS = [
    "Offline synthetic receipts only; no broker, OpenD, REAL or forward sampling.",
    "Execution is never verified by this module, including cash_bid_ask fixtures.",
    "Definitions bind frozen v2.0.0; runtime N/V/reference evidence and forward authorization remain missing, strategy interfaces refuse.",
    "Fees policy pending EVO-883 next version; accounting arithmetic is provisional.",
    "Research charges reuse the frozen per-net-order floor before stress; actual invoice amounts remain unverified.",
    "Each order is confined to one explicit trading date; cross-day orders require separate IDs.",
    "Unknown fees/quantities block new intents; no marks are carried forward.",
    "No authoritative N ledger or return series is supplied; N and Sharpe remain null.",
    "QQQ integer dividend inputs use the adopted source mapping; analysis TR is separate; actual account cash receipt stays null.",
    "Failed protective orders freeze this offline version; no automatic override or strategy repair is installed.",
]


def report(tool, inputs, *, metrics=None, reasons=(), assumptions=(), artifacts=None):
    sources = {
        "shadow15k/" + p.name: sha256(p.read_bytes())
        for p in sorted(Path(__file__).parent.glob("*.py"))
    }
    value = result(
        tool,
        inputs,
        metrics=metrics,
        reasons=reasons,
        assumptions=ASSUMPTIONS + list(assumptions),
        artifacts=artifacts,
        extra_sources=sources,
    )
    value["schema"] = "shadow15k.tool/v1"
    return load_conventions().bind(value)


def source_binding():
    value = report("source_binding", {})
    return {k: value[k] for k in ("source_files", "source_sha256")}


def text_id(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("nonempty_identifier_required")
    return value


def whole(value):
    if type(value) is not int or value < 0:
        raise ValueError("nonnegative_integer_shares_required")
    return value


def input_hash(value):
    return digest(value)
