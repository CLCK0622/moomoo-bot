"""EVO-891 B v2: the single authoritative EVO-881 cumulative-attempt ledger (append-only JSONL + independent tip witness).

Hashing follows EVO-884 f7b57b2 (qlab/qlab/dynamic_factor/contract.py + ledger_anchor.py):
  canonical(x) = json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
  digest(x)    = sha256(canonical(x)).hexdigest()
  record k>=1: previous_hash = digest(record k-1); record 0 (genesis) has previous_hash = null
  tip          = digest(last record);  witness fields: ledger_id, genesis_sha256, sequence, tip, snapshot_sha256,
                 N, n_high_water, self_report_n, ledger_file_sha256

Subcommands (python3, stdlib only):
  build    <v1_attempts.jsonl> <repo_evidence.json> <out_dir>      deterministic v2 build from the v1 evidence records
  verify   <ledger.jsonl> <tip.json> [--expect-tip H --expect-sequence K --expect-high-water N]
  append   <ledger.jsonl> <tip.json> <record.json> [--checkpoint]   append one attempt / gap_update / self_report_n record
  selftest <ledger.jsonl> <tip.json>                                 tamper cases on temporary copies; never touches inputs
Exit 0 = ok; any violation raises and exits 2 with the reason code.
"""
import hashlib, json, os, shutil, sys, tempfile
from pathlib import Path

LEDGER_NAME = "EVO-881 project cumulative attempt ledger (authoritative N)"
ATTEMPT_FIELDS = ("attempt_id", "run_id", "n_trials_total", "n_evaluated", "n_contribution", "scope_labels", "evidence")


def canonical(x):
    return json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(x):
    return hashlib.sha256(canonical(x)).hexdigest()


def fail(code):
    raise ValueError(code)


def load(path):
    recs = []
    for i, line in enumerate(Path(path).read_bytes().split(b"\n")):
        if not line:
            continue
        r = json.loads(line)
        if canonical(r) != line:
            fail(f"ledger.line_{i}_not_canonical")
        recs.append(r)
    return recs


def state(recs):
    """Recompute everything from the records alone. Raises on any structural violation."""
    if not recs or recs[0].get("event") != "genesis" or recs[0].get("seq") != 0 or recs[0].get("previous_hash") is not None:
        fail("ledger.genesis_missing_or_invalid")
    g = recs[0]
    prev, n, hw, srn, ids, checkpoints = g, 0, 0, 0, set(), []
    for k, r in enumerate(recs[1:], start=1):
        if r.get("seq") != k:
            fail(f"ledger.sequence_invalid_at_{k}")
        if r.get("previous_hash") != digest(prev):
            fail(f"ledger_hash_chain_invalid_at_{k}")
        ev = r.get("event")
        if ev == "attempt":
            for f in ATTEMPT_FIELDS:
                if f not in r:
                    fail(f"ledger.attempt_field_missing_{f}_at_{k}")
            c = r["n_contribution"]
            if not isinstance(c, int) or c < 0:
                fail(f"ledger.n_contribution_invalid_at_{k}")
            if r["attempt_id"] in ids:
                fail(f"ledger.attempt_id_duplicate_{r['attempt_id']}")
            ids.add(r["attempt_id"])
            if c == 0 and not r.get("same_cells_as"):
                fail(f"ledger.zero_contribution_requires_same_cells_as_at_{k}")
            if r.get("same_cells_as") and r["same_cells_as"] not in ids:
                fail(f"ledger.same_cells_as_unknown_at_{k}")
            if not r["evidence"] or not all(len(e.get("sha256", "")) == 64 for e in r["evidence"]):
                fail(f"ledger.evidence_sha_missing_at_{k}")
            n += c
            if r.get("n_after") != n:
                fail(f"ledger.n_after_mismatch_at_{k}")
        elif ev == "self_report_n":
            if not isinstance(r.get("value"), int):
                fail(f"ledger.self_report_invalid_at_{k}")
            srn = max(srn, r["value"])
        elif ev in ("open_gap", "gap_update"):
            if "gap_id" not in r or "status" not in r:
                fail(f"ledger.gap_record_invalid_at_{k}")
        elif ev == "checkpoint":
            want_hw = max(hw, n, srn)
            if r.get("N") != n or r.get("n_high_water") != want_hw:
                fail(f"ledger.checkpoint_mismatch_at_{k}")
            if r["n_high_water"] < hw:
                fail("ledger.high_water_decrease")
            hw = r["n_high_water"]
            checkpoints.append(k)
        else:
            fail(f"ledger.unknown_event_at_{k}")
        prev = r
    hw = max(hw, n, srn)
    return dict(ledger_id=g["ledger_id"], genesis_sha256=digest(g), sequence=len(recs) - 1, tip=digest(recs[-1]),
                snapshot_sha256=digest(recs), N=n, n_high_water=hw, self_report_n=srn,
                last_checkpoint_seq=checkpoints[-1] if checkpoints else None)


def verify(ledger, tip, expect_tip=None, expect_seq=None, expect_hw=None):
    recs = load(ledger)
    cur = state(recs)
    w = json.loads(Path(tip).read_bytes())
    for k in ("ledger_id", "genesis_sha256", "sequence", "tip", "snapshot_sha256", "N", "n_high_water", "self_report_n"):
        if w.get(k) != cur[k]:
            fail(f"ledger.tail_or_high_water_mismatch:{k}")
    if w.get("ledger_file_sha256") != hashlib.sha256(Path(ledger).read_bytes()).hexdigest():
        fail("ledger.file_sha_mismatch")
    if cur["last_checkpoint_seq"] != cur["sequence"]:
        fail("ledger.tail_not_checkpoint")
    if expect_tip and cur["tip"] != expect_tip:
        fail("ledger.external_tip_mismatch")
    if expect_seq is not None and cur["sequence"] < expect_seq:
        fail("ledger.truncated_vs_external_witness")
    if expect_hw is not None and cur["n_high_water"] < expect_hw:
        fail("ledger.high_water_decrease_vs_external_witness")
    return cur


def write_tip(ledger, tip, cur):
    w = {k: cur[k] for k in ("ledger_id", "genesis_sha256", "sequence", "tip", "snapshot_sha256", "N", "n_high_water", "self_report_n")}
    w["ledger_file_sha256"] = hashlib.sha256(Path(ledger).read_bytes()).hexdigest()
    w["ledger_file"] = Path(ledger).name
    tmp = Path(str(tip) + ".pending")
    tmp.write_bytes(canonical(w) + b"\n")
    os.replace(tmp, tip)
    return w


def append(ledger, tip, record, checkpoint_note=None):
    """Verify the current file against its witness first, then append record (+ a checkpoint) and rewrite the witness."""
    before = verify(ledger, tip)
    recs = load(ledger)
    new = []
    r = dict(record)
    if r.get("event") not in ("attempt", "self_report_n", "gap_update"):
        fail("ledger.append_event_not_allowed")
    for f in ("seq", "previous_hash", "n_after"):
        r.pop(f, None)
    r["seq"] = len(recs); r["previous_hash"] = digest(recs[-1])
    if r["event"] == "attempt":
        r["n_after"] = before["N"] + r.get("n_contribution", -1)
    new.append(r)
    trial = recs + new
    mid = state(trial)
    cp = dict(event="checkpoint", seq=len(trial), previous_hash=digest(trial[-1]), N=mid["N"],
              n_high_water=max(before["n_high_water"], mid["N"], mid["self_report_n"]),
              note=checkpoint_note or "auto checkpoint after append")
    trial.append(cp)
    after = state(trial)
    if after["n_high_water"] < before["n_high_water"] or after["N"] < before["N"]:
        fail("ledger.high_water_decrease")
    with open(ledger, "ab") as fh:
        for x in new + [cp]:
            fh.write(canonical(x) + b"\n")
        fh.flush(); os.fsync(fh.fileno())
    return write_tip(ledger, tip, verify_noTip(ledger))


def verify_noTip(ledger):
    return state(load(ledger))


def build(v1_attempts, repo_evidence, out_dir):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    v1 = [json.loads(l) for l in Path(v1_attempts).read_bytes().splitlines() if l]
    rep = json.loads(Path(repo_evidence).read_bytes())
    seed = rep["seed"]
    v1_sha = hashlib.sha256(Path(v1_attempts).read_bytes()).hexdigest()
    rep_sha = hashlib.sha256(Path(repo_evidence).read_bytes()).hexdigest()
    ledger_id = digest(dict(ledger=LEDGER_NAME, created_by="EVO-891", seed_commit=seed["commit"], seed_sha256=seed["sha256"]))
    g = dict(
        event="genesis", seq=0, previous_hash=None, ledger_id=ledger_id, ledger=LEDGER_NAME, version="v2",
        created_by="EVO-891 度支主事", project="EVO-881",
        seed_source=dict(commit=seed["commit"], path=seed["path"], sha256=seed["sha256"], rows=len(seed["rows"]),
                         seed_ledger_total=seed["n_sum"], description="种子台账合计（e51f8023 trial_ledger.jsonl 8 行之和）"),
        derived_from=dict(v1_attempts_sha256=v1_sha, repo_evidence_sha256=rep_sha, note="v1 files are kept unchanged"),
        counting_rules=[
            "frozen EVO883-prereg-v1 gate_thresholds: N = max(authoritative project cumulative attempts, self report), never decrease",
            "append_only_attempts = true; supersedes_deletes_prior_attempt = false (supersedes is a link only)",
            "failed_nan_duplicate_attempts_preserved = true",
            "N_complete_reconciliation: same-universe static batches and true retries after the seed included; no assumed zero missing",
            "one attempt record per frozen cell set: a later record re-registering the same cells carries n_contribution 0 and same_cells_as",
            "N = sum(n_contribution) over attempt records; scope_labels are views, not alternative N values",
        ],
        hash_rule="canonical JSON (sort_keys, separators=(',',':'), ensure_ascii=False, allow_nan=False); "
                  "previous_hash = sha256(canonical(previous record)); tip = sha256(canonical(last record)) — same as EVO-884 f7b57b2",
        append_rules=[
            "1. Never edit or delete a line; corrections are new records that link to the old one.",
            "2. Before appending, run `verify` against the latest witness; the externally published tip/sequence/high-water (issue comment) must also match or be exceeded.",
            "3. New attempt record: event=attempt, attempt_id unique, run_id, n_trials_total, n_evaluated, n_contribution (int >= 0), scope_labels, evidence[] with sha256; seq/previous_hash/n_after are filled by `append`.",
            "4. Every append is followed by a checkpoint record (N and n_high_water recomputed); the file must end in a checkpoint.",
            "5. n_high_water may never decrease; an append that reduces N or the high-water mark is rejected.",
            "6. After append, rewrite the tip witness atomically and publish its tip, sequence and n_high_water outside the file (issue comment) as the independent anchor.",
            "7. Closing an open gap is a gap_update record; any attempts it finds are separate attempt records, so N can only go up.",
        ],
    )
    recs = [g]
    def push(r):
        r = dict(r, seq=len(recs), previous_hash=digest(recs[-1]))
        recs.append(r)
    n = 0
    V1, V2 = "view:seed_plus_291", "view:seed_plus_291_and_subset"
    scope = {"seed": ["seed_ledger_row", V1, V2], "M01": ["omitted_from_seed_lineage", "universe:291", V1, V2],
             "M02": ["omitted_from_seed_lineage", "universe:other(BIL/IEF/SPY)"],
             "M03": ["omitted_from_seed_lineage", "universe:other(BIL/IEF/TLT)", "duplicate_execution"],
             "P01": ["post_seed", "universe:291_subset(94)", V2], "P02": ["post_seed", "universe:291_subset(94)", V2]}
    viewed = {
        "M01": "report.json: CAGR 11.55%, MDD 37.91%, DSR 0.545; OOS shot recorded",
        "M02": "report.json: CAGR 4.35%, MDD 23.12%, certify REJECTED_dsr evaluated at N=38",
        "M03": "report.json metrics and 3 cell Sharpes identical to carry_rates_A-16be273 (seed row S06)",
        "P01": "derived settlement file is_performance_reading=true; 15 daily NAV points 2026-08-10..08-28 for seed11 x pv1_baseline",
        "P02": "round-2 decisions on the same 10 frozen cells; settlement pending_archive_integrity at read time",
    }
    for r in v1:
        aid = r["attempt_id"]
        is_seed = aid.startswith("S")
        contrib = 0 if aid == "P02" else r["n_trials_total"]
        n += contrib
        rec = dict(event="attempt", attempt_id=aid, run_id=r["run_id"], n_trials_total=r["n_trials_total"],
                   n_evaluated=r["n_evaluated"], n_contribution=contrib, n_after=n,
                   scope_labels=scope["seed"] if is_seed else scope[aid],
                   origin="seed_ledger_row" if is_seed else r["class_"],
                   performance_viewed=True if is_seed else viewed[aid],
                   universe=r.get("universe"), evidence=r["evidence"])
        if aid == "P02":
            rec["same_cells_as"] = "P01"
        if not is_seed:
            rec["note"] = r.get("note")
            rec["report_metrics"] = r.get("report_metrics")
        if aid == "M01":
            rec["supersedes_link"] = "S08 alpha_mining_i-b1de1d8 (run2) superseded this run1 row; link only, contribution kept"
        if aid == "M03":
            rec["duplicate_of"] = "S06"
        push(rec)
    gaps = [
        ("G1", "llm_paper later recomputations (EVO-496 / EVO-605)", "open", "no workdir or repo object; EVO-605 text says real v2 rounds = 0"),
        ("G2", "EVO-422 QuantMind minimal isolated PoC (2026-08-31)", "open", "no workdir; unknown whether performance was computed or on which universe"),
        ("G3", "EVO-577 synthetic signal-correlation PoC", "open", "described as synthetic; no workdir"),
        ("G4", "seed hist/* rows vs pre-ledger branches (evo-13/23/24/25, EVO-65, EVO-162 C1); human-screened 9 vs 7", "open", "pre-seed per-cell mapping not redone"),
        ("G5", "agent transcripts (~/.claude etc.) and comment attachments outside workdirs", "open", "not searched"),
        ("G6", "EVO-775 separate trial_registry.json (XSP options)", "checked_not_counted", "2 specs registered, alpha_experiments_executed=0, returns null"),
    ]
    for gid, item, st, why in gaps:
        push(dict(event="open_gap", gap_id=gid, item=item, status=st, reason=why,
                  effect_on_N="closing this gap can only add attempt records; N can only go up" if st == "open" else "none"))
    push(dict(event="checkpoint", N=n, n_high_water=n,
              note="authoritative N after EVO-891 historical reconciliation; G1-G5 open, closing them can only raise N; scope labels on rows are views, not alternative N values"))
    ledger = out / "EVO891-B-ledger-v2.jsonl"; tip = out / "EVO891-B-ledger-v2.tip.json"
    ledger.write_bytes(b"".join(canonical(r) + b"\n" for r in recs))
    cur = state(load(ledger))
    write_tip(ledger, tip, cur)
    return verify(ledger, tip)


def selftest(ledger, tip):
    base = verify(ledger, tip)
    results = []
    def case(name, mutate, expect_fail=True, **kw):
        d = Path(tempfile.mkdtemp(prefix="evo891_selftest_"))
        try:
            L, T = d / Path(ledger).name, d / Path(tip).name
            shutil.copy(ledger, L); shutil.copy(tip, T)
            mutate(L, T)
            try:
                if kw.get("do_append"):
                    append(L, T, kw["do_append"])
                verify(L, T, expect_tip=kw.get("expect_tip"), expect_seq=kw.get("expect_seq"), expect_hw=kw.get("expect_hw"))
                outcome = "accepted"
            except ValueError as e:
                outcome = "rejected:" + str(e)
            ok = outcome.startswith("rejected") == expect_fail
            results.append(dict(case=name, outcome=outcome, as_expected=ok))
        finally:
            shutil.rmtree(d)
    lines = lambda p: Path(p).read_bytes().split(b"\n")[:-1]
    def wr(p, ls): Path(p).write_bytes(b"".join(x + b"\n" for x in ls))
    case("untouched", lambda L, T: None, expect_fail=False)
    case("drop_last_line", lambda L, T: wr(L, lines(L)[:-1]))
    case("drop_last_line_and_rewrite_tip", lambda L, T: (wr(L, lines(L)[:-1]), write_tip(L, T, state(load(L)))))
    case("truncate_to_seed_rows_and_rewrite_tip_vs_published_witness",
         lambda L, T: (wr(L, lines(L)[:9]), write_tip(L, T, state(load(L)))), expect_seq=base["sequence"], expect_hw=base["n_high_water"])
    def forge(L, T):
        ls = lines(L)[:9]  # genesis + 8 seed rows, then a self-consistent checkpoint at N=47 and a matching new tip
        recs = [json.loads(x) for x in ls]
        recs.append(dict(event="checkpoint", seq=9, previous_hash=digest(recs[-1]), N=47, n_high_water=47, note="forged"))
        wr(L, [canonical(r) for r in recs]); write_tip(L, T, state(load(L)))
    case("forged_consistent_rewrite_local_only", forge, expect_fail=False)
    case("forged_consistent_rewrite_vs_published_witness", forge, expect_seq=base["sequence"], expect_hw=base["n_high_water"])
    case("delete_middle_attempt", lambda L, T: wr(L, lines(L)[:3] + lines(L)[4:]))
    def edit(L, T):
        ls = lines(L); r = json.loads(ls[9]); r["n_trials_total"] = 1; ls[9] = canonical(r); wr(L, ls)
    case("edit_attempt_field", edit)
    def reduce_contribution(L, T):
        ls = lines(L); r = json.loads(ls[9]); r["n_contribution"] = 0; r["same_cells_as"] = "S01"; ls[9] = canonical(r); wr(L, ls)
    case("zero_out_contribution", reduce_contribution)
    case("append_valid_attempt", lambda L, T: None, expect_fail=False,
         do_append=dict(event="attempt", attempt_id="T01", run_id="selftest", n_trials_total=2, n_evaluated=2, n_contribution=2,
                        scope_labels=["selftest"], evidence=[dict(path="x", sha256="0" * 64)]))
    case("append_negative_contribution", lambda L, T: None,
         do_append=dict(event="attempt", attempt_id="T02", run_id="selftest", n_trials_total=1, n_evaluated=1, n_contribution=-5,
                        scope_labels=["selftest"], evidence=[dict(path="x", sha256="0" * 64)]))
    case("append_duplicate_attempt_id", lambda L, T: None,
         do_append=dict(event="attempt", attempt_id="S01", run_id="x", n_trials_total=1, n_evaluated=1, n_contribution=1,
                        scope_labels=["selftest"], evidence=[dict(path="x", sha256="0" * 64)]))
    case("external_tip_mismatch", lambda L, T: None, expect_tip="f" * 64)
    return dict(base=base, cases=results, all_as_expected=all(r["as_expected"] for r in results))


if __name__ == "__main__":
    a = sys.argv[1:]
    try:
        if a[0] == "build":
            print(json.dumps(build(a[1], a[2], a[3]), indent=1))
        elif a[0] == "verify":
            kw = {}
            for i, x in enumerate(a):
                if x == "--expect-tip": kw["expect_tip"] = a[i + 1]
                if x == "--expect-sequence": kw["expect_seq"] = int(a[i + 1])
                if x == "--expect-high-water": kw["expect_hw"] = int(a[i + 1])
            print(json.dumps(verify(a[1], a[2], **kw), indent=1))
        elif a[0] == "append":
            print(json.dumps(append(a[1], a[2], json.loads(Path(a[3]).read_bytes())), indent=1))
        elif a[0] == "selftest":
            r = selftest(a[1], a[2]); print(json.dumps(r, ensure_ascii=False, indent=1))
            sys.exit(0 if r["all_as_expected"] else 1)
        else:
            raise SystemExit(__doc__)
    except ValueError as e:
        print("REJECTED", e, file=sys.stderr); sys.exit(2)
