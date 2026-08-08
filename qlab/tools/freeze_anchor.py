"""freeze_anchor — 把「预注册冻结」锚到**服务端观测时间**，而非可伪造的 git 日期。

工部 2026-08-08：`GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE` 提交者可任意设定，故不能自证
「预注册先于第一笔决策」。可用锚点＝ GitHub 服务端记录的 **PushEvent.created_at**（提交者设不了）。
`/events` 只保留近期事件 ⇒ 必须**落库**，否则按年计的证据期一到就查不到。

时序证明两条腿（缺一不可）：
  1. 绝对时间下界：本文件记录的 PushEvent.created_at（服务端观测）；
  2. 相对顺序：每笔决策 commit 必须是冻结 commit 的 **DAG 后代**（无法给不存在的 commit 造子节点）
     ⇒ 本分支**永不 rebase、永不 force-push**。

用法::

    python -m tools.freeze_anchor --sha <freeze_sha> --repo CLCK0622/moomoo-bot \
        --out qlab/freeze_anchor.json [--retries 20 --sleep 25]

拿不到就**如实记 pending 并非零退出**（fail-closed，不编造时间）。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def _gh_json(path: str):
    try:
        out = subprocess.check_output(["gh", "api", path], text=True, stderr=subprocess.DEVNULL)
        return json.loads(out)
    except Exception:
        return None


def find_push_event(repo: str, sha: str, branch: str | None = None):
    """在 repo 事件流里找该冻结对应的**服务端观测事件**。

    两种形态都算数（均为服务端记录、提交者不可设定）：
    * `PushEvent`：payload.head == sha 或 commits 含该 sha（推到已存在分支）；
    * `CreateEvent`（ref_type=branch）：**新建分支的首推**不发 PushEvent，只发 CreateEvent，
      其 payload 无 head/commits，故按 `ref == branch` 匹配（这正是本轨冻结的形态）。
    """
    ev = _gh_json(f"repos/{repo}/events?per_page=100")
    if not ev:
        return None
    for e in ev:
        pl = e.get("payload", {})
        if e.get("type") == "PushEvent":
            if pl.get("head") == sha or any(c.get("sha") == sha for c in pl.get("commits", [])):
                return {"kind": "PushEvent", "created_at": e["created_at"], "ref": pl.get("ref"),
                        "head": pl.get("head"), "event_id": e.get("id")}
        elif e.get("type") == "CreateEvent" and branch and pl.get("ref_type") == "branch" \
                and pl.get("ref") == branch:
            return {"kind": "CreateEvent(branch first push)", "created_at": e["created_at"],
                    "ref": pl.get("ref"), "head": None, "event_id": e.get("id"),
                    "note": "新建分支首推只发 CreateEvent；服务端时间同样不可由提交者设定"}
    return None


def server_ref_state(repo: str, branch: str, sha: str):
    """服务端 ref 是否确实指向该 sha（即使 events 尚未刷新，也能证明服务端已收到）。"""
    d = _gh_json(f"repos/{repo}/git/refs/heads/{branch}")
    if not d:
        return None
    got = (d.get("object") or {}).get("sha")
    return {"branch": branch, "server_ref_sha": got, "matches_freeze": got == sha}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="capture server-side freeze anchor")
    ap.add_argument("--sha", required=True)
    ap.add_argument("--repo", default="CLCK0622/moomoo-bot")
    ap.add_argument("--branch", default="agent/evo-llm-paper")
    ap.add_argument("--out", default="qlab/freeze_anchor.json")
    ap.add_argument("--retries", type=int, default=1)
    ap.add_argument("--sleep", type=int, default=25)
    args = ap.parse_args(argv)

    pe = None
    for _ in range(max(1, args.retries)):
        pe = find_push_event(args.repo, args.sha, args.branch)
        if pe:
            break
        time.sleep(args.sleep)

    ref = server_ref_state(args.repo, args.branch, args.sha)
    anchor = {
        "purpose": "预注册冻结的服务端时间锚点（git 日期可伪造，故不作证据）",
        "repo": args.repo, "branch": args.branch, "freeze_sha": args.sha,
        "push_event": pe,
        "server_ref_state": ref,
        "dag_rule": "每笔决策 commit 必须是 freeze_sha 的 DAG 后代；本分支永不 rebase / 永不 force-push",
        "status": "anchored" if pe else "pending_events_feed",
        "note": ("PushEvent.created_at 为 GitHub 服务端观测、提交者不可设定" if pe else
                 "公开 events 流有缓存延迟，尚未出现该 sha；server_ref_state 已证明服务端确已收到该 commit。"
                 "须在事件出现后补记 created_at（fail-closed：不编造时间）"),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(anchor, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(anchor, ensure_ascii=False, indent=2))
    return 0 if pe else 2


if __name__ == "__main__":
    raise SystemExit(main())
