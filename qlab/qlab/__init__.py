"""qlab — independent reproduction harness for candidate quant strategies.

This package wraps the *vendored, verbatim* deterministic core of a candidate
strategy (under ``qlab/vendor/<name>``) and drives it through a fixed validation
battery: cost x1/x2, walk-forward, out-of-sample, per-year, rolling window, and
parameter perturbation. It emits an auditable artifact set (raw trades, equity
curve, metrics JSON/CSV, config, run manifest with commit hashes + data
provenance) for every scenario.

The harness is data-source agnostic (see ``qlab.datasource``). It does NOT and
cannot manufacture a real-data verdict on its own — the verdict is only as good
as the bars fed in. See ``qlab/README.md`` for the EVO-65 reproduction status.
"""
