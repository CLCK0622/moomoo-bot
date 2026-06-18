# qlab — quant-strategies → moomoo OpenD execution layer (EVO-65)

Scope (per the updated EVO-65 / 吏部 brief): **wire the existing
`quant-strategies` signals into a `qlab` skeleton and a moomoo OpenD execution
layer, paper-trading first.** This is *not* a from-scratch backtest rebuild —
the author's research/backtest stands; we only take their **decision functions**
and put a live-capable, risk-controlled, observable execution engine around them.

> **Live trading is OFF by default.** Default mode is offline **paper** trading
> on a deterministic fixture, which runs anywhere with no OpenD gateway and no
> brokerage account. Real-money (`live`) orders require an explicit triple gate.

## What's here

```
qlab/
  vendor/qstrat/          # quant-strategies deterministic CORE, vendored VERBATIM @ 61341f0
                          #   (signals/indicators/exit logic — the author's code, unchanged)
  qlab/
    signals.py            # SignalAdapter — calls the vendored combiner/conditions/exit_manager
    config.py             # env-driven ExecConfig + RiskLimits (NO secrets in repo)
    risk.py               # RiskManager — kill switch, caps, intraday loss, 20% DD breaker, …
    observability.py      # JSONL channels: signals/orders/fills/positions/equity/
                          #   broker_events/errors/heartbeat (credential-redacted)
    engine.py             # ExecutionEngine — signal→risk→broker→observability tick loop
    run_paper.py          # CLI (paper-first)
    brokers/
      base.py             # Broker interface + Order/Fill/Position/Account model
      paper.py            # PaperBroker — in-memory simulated fills (default, no deps)
      moomoo_opend.py     # MoomooOpenDBroker — real OpenD adapter (SIMULATE by default)
    synthetic.py          # deterministic fixture bars (replay/testing only — NOT performance)
    datasource.py, params.py, runner.py   # bar sources, baseline params, offline driver
  tests/                  # 12 tests: paper broker, risk controls, engine replay, redaction
  reports/SAMPLE_paper_run/   # committed sample paper run (synthetic; non-performance)
```

## Run it

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-lock.txt      # pandas/numpy/pyarrow/pytest (no moomoo-api needed)

# Default: offline PAPER trading on a synthetic fixture (no OpenD, reproducible):
python -m qlab.run_paper --mode paper --out reports/paper_run

# Signals + intended orders only, no fills:
python -m qlab.run_paper --mode dry_run --out reports/dryrun

# Real OpenD SIMULATE account (needs OpenD gateway + SDK — see preconditions):
python -m qlab.run_paper --mode opend_paper --out reports/opend_paper

pytest tests/ -q
```

Each run writes `config.json`, `params.json`, `summary.json` and the eight JSONL
observability channels.

## Execution modes & the live gate

| mode | broker | fills | external deps |
|---|---|---|---|
| `dry_run` | none | none (intended orders logged) | none |
| `paper` | `PaperBroker` | simulated | none |
| `opend_paper` | `MoomooOpenDBroker` (`TrdEnv.SIMULATE`) | real paper account | OpenD gateway + SDK |
| `live` | `MoomooOpenDBroker` (`TrdEnv.REAL`) | **real money** | OpenD + SDK + **triple gate** |

**`live` triple gate** (all required): `QLAB_ALLOW_LIVE=1` **and** CLI
`--i-understand-live` **and** `MOOMOO_TRADING_PASSWORD` in the env for
`unlock_trade`. Absent any one, the engine refuses to start.

## Risk controls (all enforced in `risk.py`, every entry passes through)

- **Global kill switch** (manual + auto-tripped by the breakers below).
- **20% drawdown circuit breaker** → trips the kill switch.
- **Intraday loss limit** (% of day-start equity) → blocks new entries.
- **Per-symbol** and **per-strategy** notional caps; **global max positions**.
- **Abnormal single-bar move** halt (skips a symbol on likely bad print / halt).
- **Trading-session validation** (entries only inside RTH).
- **Connection-error / market-halt** → kill switch. Exits are *never* blocked.

## Credentials & logging

No secrets in the repo. Config is env-only (`QLAB_*`); the REAL trading password
is read from `MOOMOO_TRADING_PASSWORD` at unlock time only. The observability
sink redacts any field whose key matches `password|token|secret|api_key|unlock`.
(The legacy `backend/config.py` committed a plaintext trading password — this
layer deliberately does not.)

## OpenD connection preconditions (for `opend_paper` / `live`)

1. `pip install moomoo-api` (or `futu-api`).
2. moomoo **OpenD** gateway running and logged in on `127.0.0.1:11111`.
3. A moomoo account with a **paper (SIMULATE)** sub-account enabled.
4. For `live` only: the triple gate above.

## Lightweight consistency check (NOT a full historical reproduction)

`tests/test_harness.py::test_adapter_uses_vendored_entry_logic_verbatim` replays
a fixture and asserts the adapter's entry decision **never diverges** from the
vendored `build_entry_evaluator` — i.e. the integrated signal/order behaviour is
the author's logic, not a reimplementation. Exits call the vendored
`ExitManager.evaluate` directly for the same reason. Per the brief we do **not**
re-run the author's full multi-month backtest.

## Status / blocker

The paper path is proven end-to-end (`reports/SAMPLE_paper_run/`, synthetic
fixture). A **real paper-account run is blocked here**: no OpenD gateway and no
moomoo/futu SDK/account in this workspace — `opend_paper` connects and returns a
precise blocker rather than fabricating fills. To clear it, run on a host with
OpenD + a SIMULATE account (see preconditions). **Synthetic numbers are harness
self-tests, never strategy performance.**
