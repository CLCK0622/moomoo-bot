## Fixed natural-delivery entry

The only repository entry for a frozen M/W/F v2 schedule delivery is:

```bash
python3 qlab/tools/run_llm_paper_mwf_v2.py \
  --delivery qlab/tests/fixtures/mwf_v2_offline_delivery.json \
  --state-dir /path/to/immutable-mwf-v2-state
```

The delivery is a content-hashed `llm_paper_schedule_delivery/v2` object. It
contains separate, typed decision and execution snapshots so evidence cannot
travel backward in time. Every snapshot, RESOLUTION, OpenD `K_DAY/qfq`, and
BIL total-return input carries a fixed source identity, exact symbol/date
coverage, records, and a canonical content hash. The runner never imports a
callback from the delivery and never performs a remote fetch. Missing frozen
coverage therefore fails closed.

The deterministic chain is:

`schedule delivery -> planned round/decisions -> per-cell coalescing -> SIMULATE single_book execution -> settlement -> success manifest`

Artifacts are written below `--state-dir` in `rounds/`, `coalescing/`,
`executions/`, `settlements/`, and `pipeline/`. The durable planned-round key
is `[experiment_version, scheduled_at]`, and its payload hash covers planning
inputs only so later frozen execution/settlement evidence can resume the same
round without rewriting it. Decision, execution, and settlement
keys retain their frozen tuple shapes. Claim records transition from
`incomplete` to `complete` only after the immutable artifact exists. A replay
of an interrupted identical claim recovers the artifact; a different hash for
the same key is rejected without replacement.

Exit codes are stable: `0` complete, `10` delivery/input contract, `20`
planned round/decision, `30` coalescing, `40` execution, and `50` settlement.
Failure records are written under `failures/`, state
`published_cutoff_advanced=false`, and never create a success manifest.

The checked-in fixture is offline evidence only. It uses historical frozen
records, does not fetch quotes, does not invoke an autopilot, does not place an
order, and does not authorize a real or acceptance run.
