## Default offline suite

From `qlab/`, with the existing dependencies installed:

```bash
unset QLAB_LIVE_NET
python -m pytest tests/ -q -rs
```

`tests/conftest.py` installs a CPython socket audit hook before test collection.
External DNS lookups, TCP connections (including `connect_ex`), and UDP
datagrams (`sendto` / `sendmsg`) fail with `external network blocked`. Loopback
IPv4/IPv6, `localhost`, and AF_UNIX remain available. A pytest failure escapes
ordinary fetcher exception handlers, so a missed marker cannot quietly turn
an accidental request into a data gap or skip. The switch is captured once at
session configuration; changing the environment inside a test does not unlock
networking. Blocked attempts also fail the test report if a worker thread or an
overbroad exception handler swallows the immediate failure.
Converting a report to a hard failure removes its xfail metadata. Violations
remain recorded across reports, so the session exits nonzero even if a reporter
discards failure counts. Already reported attempts do not fail unrelated tests.

The Python guard covers collection, fixtures, and test bodies in the pytest
process. For full isolation, run the suite inside an OS network sandbox too:
subprocesses and native libraries using their own networking do not inherit
Python audit hooks. Dependency installation is separate from the offline run.

## Explicit live tests

Every test that fetches external data must carry the registered
`@pytest.mark.live_net` marker. The collection hook skips these tests with a
reason unless the environment contains exactly `QLAB_LIVE_NET=1` (`0`, `true`,
and an absent variable all keep the offline policy).

To run only the live tests when an external fetch is intended:

```bash
QLAB_LIVE_NET=1 python -m pytest tests/ -m live_net -q -rs
```

This opt-in also disables the session's socket guard. The marker itself never
grants network access.

## Network inventory

The external-fetch inventory after scanning all of `tests/` is:

| Test | External operation | Default |
| --- | --- | --- |
| `tests/test_fred_yields.py::test_live_fred_covers_2022_rate_shock` | FRED DGS2 CSV, 2022-01-01 through 2022-12-31 | `live_net`, skipped |

Other network-adjacent coverage remains offline and does not need a live marker:

| Tests | Offline boundary |
| --- | --- |
| Other `test_fred_yields.py` cases | Injected fake HTTP session / canned CSV |
| `test_fred_vintage.py` | Fake API session, or missing-key failure before any request |
| `test_datafetch.py` | Fake SEC/Yahoo sessions; local normalization and proof-of-work logic |
| `test_kline_depth_probe.py` | Injected fake quote context; no OpenD connection |
| `test_qlib_gen.py` | Local parquet/store, mock LLM or budget rejection before LLM call |
| `dynamic_factor/test_contract_and_harness.py::test_offline_guard_rejects_network` | The harness's own socket stub rejects the deliberate probe |
| `test_network_guard.py` | Child pytest sessions prove external probes fail, live markers skip, and opt-in passes a synthetic socket event through a fake transport; real I/O is local loopback / AF_UNIX only |

The remaining tests use local fixtures, files, SQLite, or offline CLI workers.
There are no additional external-fetch tests in this suite.
