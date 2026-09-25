# AlphaAgent originality/complexity discipline — for 营缮 (doc-only)

AlphaAgent (KDD 2025, arXiv 2502.16789, `RndmVariableQ/AlphaAgent`) is **not
integrated** here (工部尚书's call: 不接). Its one transferable idea is worth
keeping: two *regularizers* on any machine- or LLM-proposed factor that suppress
the failure modes we keep hitting — **overfit-by-complexity** and
**crowding/duplication**. This is a checklist to apply in the
hypothesis→factor stage, *before* a factor ever reaches the EVO-149 gate. It is
cheap, deterministic, and needs no LLM.

None of this replaces the gate. It's a **pre-filter** that shrinks the honest N
you have to defend downstream — reject junk early so the expensive OOS budget is
spent on plausible factors, and so `n_trials` isn't inflated by obvious dupes.
(It still counts in N when it *is* evaluated; a pre-filter rejection that never
computes a Sharpe is a design choice you must pre-register, not a silent drop.)

## 1. Complexity regularizer — parsimony over cleverness

Longer expression trees fit noise. Score each candidate on its Qlib expression
string and reject before evaluation when it exceeds pre-registered caps.

Concrete, computable from the expression AST / string:

| metric | how | suggested cap |
|--------|-----|---------------|
| operator count | count Qlib ops (`Ref`, `Mean`, `Std`, `Corr`, `Rank`, …) | ≤ 6 |
| nesting depth | max parenthesis / call depth | ≤ 4 |
| distinct lookback windows | count of integer window args | ≤ 3 |
| max lookback | largest window constant | ≤ 252 (1y) unless pre-registered |
| raw-field count | distinct `$field` referenced | ≤ 4 |

Rationale: a factor needing 9 operators and 5 windows to "work" in-sample is
almost always curve-fit. Pre-register the caps in the candidate's
`*_EVAL_PREREGISTRATION.md`; treat a breach as an automatic reject, not a
judgement call.

A regex sketch to flag obvious over-parameterisation (tune to the DSL):

```python
import re
OPS = r"(Ref|Mean|Std|Sum|Corr|Cov|Rank|Delta|Max|Min|Quantile|WMA|EMA|Skew|Kurt|Slope|Rsquare|Resi)"
def complexity(expr: str) -> dict:
    return {
        "n_ops":     len(re.findall(OPS, expr)),
        "depth":     _max_paren_depth(expr),          # simple stack scan
        "windows":   sorted(int(n) for n in re.findall(r",\s*(\d+)\s*\)", expr)),
        "n_fields":  len(set(re.findall(r"\$(\w+)", expr))),
    }
```

## 2. Originality regularizer — reject crowding & near-duplicates

LLM/auto miners converge on the same handful of textbook factors; duplicates
inflate N and add nothing. Enforce novelty against the **existing factor pool**
(already-accepted signals + this round's earlier proposals) on two axes:

1. **Structural novelty (cheap, pre-compute):** normalise the expression
   (canonical operator order, window binning) and reject exact/near-exact string
   duplicates. Catches `mom21` vs `$close/Ref($close,21)-1` restated.
2. **Value novelty (the real test):** compute the candidate factor's values on
   the *training* window and reject if its **cross-sectional rank correlation**
   (Spearman) with any pooled factor exceeds a pre-registered threshold, e.g.
   `|ρ| > 0.7`. Redundant signal → drop or merge, don't spend N on it.

```python
# training-window only; never peek at OOS
rho = spearman_rank_corr(candidate_values, pooled_factor_values)   # per-date, then mean
reject_if = abs(rho) > 0.7
```

Keep a small **factor pool registry** (name, canonical expr, train-window value
hash) so novelty is checked against a growing, auditable set — not re-derived
each round.

## 3. Economic-reason gate (the human-in-loop AlphaAgent leaves out)

AlphaAgent's regularizers are structural; they can't tell a real risk premium
from a well-formed coincidence. Keep 户部's rule on top: every surviving factor
carries an **ex-ante economic hypothesis** (risk-premium or behavioural). A
factor that passes complexity + originality but has no stated mechanism is
quarantined / extra-penalised. This is the line between *discovery* and *curve
fitting*.

## How this plugs in (no new dependency)

- Apply §1–§2 as a pre-filter inside your `swing.*_evaluate` factor-proposal
  step, driven by the caps you pre-register per candidate.
- Feed survivors — with their true attempted N (the manifest from
  `factor_export` / `rdagent_skeleton`) — into the existing EVO-149 gate.
- Nothing here is a verdict. It only decides *what's worth spending OOS budget
  on*; PASS/FAIL stays 100% with `qlab.events`.
