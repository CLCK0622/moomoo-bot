"""Strategy-core sanity: synthetic determinism + signal-adapter consistency."""
from __future__ import annotations

from qlab.synthetic import generate_symbol
from qlab.signals import SignalAdapter
from qlab.params import default_params

START, END = "2025-01-02", "2025-02-28"


def test_synthetic_is_deterministic():
    a1, a15 = generate_symbol("AAA", START, END, seed=7)
    b1, b15 = generate_symbol("AAA", START, END, seed=7)
    assert a1.equals(b1) and a15.equals(b15)
    c1, _ = generate_symbol("BBB", START, END, seed=7)
    assert not a1.equals(c1)


def test_adapter_uses_vendored_entry_logic_verbatim():
    """Consistency check: the adapter's entry decision == the vendored
    entry evaluator on the same prepared bars (no reimplementation drift)."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "vendor" / "qstrat"))
    from strategy.combiner import build_entry_evaluator

    params = default_params()
    adapter = SignalAdapter(params)
    raw_eval = build_entry_evaluator(params)

    df1, df15 = generate_symbol("AAA", START, END, seed=7)
    prepared = adapter.prepare(df1, df15)

    fired_adapter, fired_raw = 0, 0
    for _, row in prepared.iterrows():
        sig = adapter.entry_signal(row)
        adapter_fired = sig is not None
        # raw decision replicating the engine gate, minus adapter-only session window
        import pandas as pd
        raw_ok = (not pd.isna(row.get("orb_high")) and not pd.isna(row.get("orb_low"))
                  and raw_eval(row, params))
        if adapter_fired:
            fired_adapter += 1
            # whenever the adapter fires, the raw evaluator must also be True
            assert raw_ok, "adapter fired where vendored evaluator did not"
        if raw_ok:
            fired_raw += 1
    assert fired_raw > 0  # the fixture actually exercises ORB breakouts
    assert fired_adapter > 0
