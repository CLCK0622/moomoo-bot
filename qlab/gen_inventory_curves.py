"""重算库存三候选（GEM / 残差动量 / 多因子）的日频收益，落 reports/inventory_curves/<name>_equity.csv
（date,ret），供候选 A 的 sleeve 相关性用。每条独立 try，失败跳过不阻塞。"""
import sys, traceback
from pathlib import Path
import numpy as np, pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parent))          # qlab pkg
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))      # repo root (research)
from qlab.swing.momentum_signals import load_daily

OUT = Path("qlab/reports/inventory_curves"); OUT.mkdir(parents=True, exist_ok=True)

def _save(name, edf):
    edf[["date", "ret"]].to_csv(OUT / f"{name}_equity.csv", index=False)
    print(f"  {name}: {len(edf)} rows {pd.to_datetime(edf['date']).min().date()}→{pd.to_datetime(edf['date']).max().date()}")

def _find(sym, dirs=("data/daily_full", "data/gem")):
    for d in dirs:
        p = Path(d) / f"{sym}_1d.parquet"
        if p.exists(): return load_daily(p)
    return None

# GEM
try:
    from qlab.swing.gem_signals import GemParams, gem_curve
    p = GemParams(); fr = {s: _find(s) for s in p.all_symbols}
    fr = {s: f for s, f in fr.items() if f is not None}
    start = str(max(pd.to_datetime(fr[s]["date"]).min() for s in fr).date())
    _save("gem", gem_curve(fr, p, cost_mult=2.0, start=start)["equity_df"])
except Exception as e:
    print("  gem SKIP:", e)

# 残差动量
try:
    from qlab.swing.residmom_signals import ResidMomParams, residmom_curve
    from qlab.swing.residual_signals import FACTOR_ETFS
    uni = [l.strip() for l in open("RESIDUAL_UNIVERSE_RESOLVED.txt") if l.strip() and not l.startswith("#")]
    sf = {s: f for s in uni if (f := _find(s)) is not None}
    ff = {s: f for s in FACTOR_ETFS if (f := _find(s)) is not None}
    _save("residmom", residmom_curve(sf, ff, list(sf), ResidMomParams(), cost_mult=2.0)["equity_df"])
except Exception as e:
    print("  residmom SKIP:", e); traceback.print_exc()

# 多因子（qlib 管线）
try:
    from qlab.swing.run_multifactor import MULTIFACTOR_FACTORS
    from qlab.swing.multifactor_signals import MultiFactorParams, multifactor_curve
    from tools.qlib_gen import build_qlib_data, factor_export
    uni = [l.strip() for l in open("RESIDUAL_UNIVERSE_RESOLVED.txt") if l.strip() and not l.startswith("#")]
    uni = [s for s in uni if Path(f"data/daily_full/{s}_1d.parquet").exists()]
    build_qlib_data.build(Path("data/daily_full"), Path("/tmp/qs_inv2"), max_workers=1)
    factor_export.FACTOR_SETS["mf"] = dict(MULTIFACTOR_FACTORS)
    factor_export.export(Path("/tmp/qs_inv2/bin"), Path("/tmp/mf_inv"), start="2006-01-01",
                         end="2024-12-31", factor_set="mf", repo_root=Path.cwd())
    fdf = pd.read_parquet("/tmp/mf_inv/factors.parquet")
    sf = {s: _find(s) for s in uni}; sf = {s: f for s, f in sf.items() if f is not None}
    spy = _find("SPY")
    _save("multifactor", multifactor_curve(fdf, sf, spy, list(sf), MultiFactorParams(), cost_mult=2.0)["equity_df"])
except Exception as e:
    print("  multifactor SKIP:", e)

print("inventory curves →", OUT)
