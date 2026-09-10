# S5 — FOMC pre-meeting drift (SPY) · EVO-130 Phase 2

**Verdict: `已衰减/不可用` (decayed / not usable) — confirms the pre-registered default.**

Real full-depth SPY (2006-06→2026, qfq) + committed source-cited scheduled FOMC
calendar (`data/fomc_meetings.csv`, Fed official pages). Pre-registration frozen
at `c025d56`; primary口径 = 2015→ subsample pre-FOMC edge significantly positive
after ×2 costs AND surviving the multiple-testing haircut. Full result:
[`report.json`](report.json).

## The decay is unambiguous (primary offset = T-1, per event)

| Window | n | mean/event (×1) | p(mean≤0) | mean/event (×2) | p(mean≤0) |
|---|---|---|---|---|---|
| **pre-2015** | 69 | **+0.34%** | 0.019 ✓sig | — | — |
| **2015→** | 91 | −0.12% | 0.861 | **−0.32%** | 0.998 |
| full 2006→ | 160 | +0.08% | 0.205 | — | — |

Pre-2015 the drift was real and significant (Lucca-Moench 2015); post-2015 it is
indistinguishable from zero gross and **negative after realistic costs** — exactly
the Kurov et al. (2021) decay. The full-sample average masks the regime shift.
All three entry offsets {T-1, T-2, T-3} tell the same story; none survives the
haircut on the 2015→ subsample.

## Why not the EVO-12 50%/20% gates as the primary test

S5 is a sparse event sleeve (~8 in-market days/year), so its full-capital equity
curve is mostly cash and structurally cannot clear a 50%-CAGR hurdle — that gate
is reported in `report.json` for the record (`基线未达标`) but would be a category
error as the decay test. The faithful test of "has the effect decayed" is the
per-event edge significance above, which is the pre-registered primary metric.

## Honest caveats

- Daily bars: exit at decision-day close captures the pre-announcement drift + the
  announcement session; it cannot isolate the exact 2 pm ET cutoff. This makes the
  test slightly *generous* to the effect, and it still decays — strengthening the
  negative.
- Scheduled meetings only; 2020-03 scheduled meeting was cancelled (excluded).

## Reproduce

```bash
python -m qlab.swing.run_swing --candidate s5 --data-dir data/daily_full \
    --out reports/swing_s5_fomc
```

Offline logic pinned by `tests/test_swing.py`.
