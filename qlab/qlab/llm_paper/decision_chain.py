"""EVO-8 LLM 定性投资轨 — 决策链路（前向纸面）。

冻结口径见 `qlab/llm_paper_prereg.json`（v3 `8603989`，服务端锚点 2026-08-08T02:10:26Z）。
本模块只做**决策的产生与落盘**，不出 verdict（中途读数只作监控——预注册 §4）。

链路：公开信息 → 结构化论点 + 置信度 + 目标仓位 → 多 seed × 多 prompt 变体 → 决策落盘不可改。

三条时序铁律（`llm_paradigm.validate_decision_log` 逐条核，违规不静默）：
    evidence_available_utc  ≤  decision_ts  ≤  effective_from
- `evidence_available_utc` = 由 `evidence_availability.derive_available_utc` 从**信息源自身时间**
  （EDGAR `acceptanceDateTime` / RSS `pubDate`）派生的**公开可得**时刻，
  含 ≥17:30 ET 顺延、盘前顺延、**SPY 派生真交易日历跳假日**、覆盖外 fail-closed；
- `decision_ts` = LLM 产出该决策的时刻（**决策后**才允许写盘）；
- **收益起算两段式**（工部 2026-08-08 结构性更正）：`intended_start` = 决策后下一个非周末日开盘
  （纯机械、**不查假日**——未来某天开不开市，任何历史 bar 序列都答不了）；
  `actual_start` = 价格腿**首根真实 bar**，执行时观测确定，未开市自然顺延并如实记顺延天数。
  时序核验的 `effective_from` 优先取 `actual_start`（权威），未回填时暂用 `intended_start` 并标 pending。
  **永久去掉对前瞻日历的依赖**：不估算、不需假日表、不会在覆盖边缘失效。

台账：`candidate_id="llm_paper"`，**每 seed × 每变体全额登记**（本轮冻结网格 10 格），
少登即 `REJECTED_honesty`（户部机器核验）。RSS 拒收条目逐条进 run 日志。
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from qlab.events.datafetch.evidence_availability import (  # noqa: E402
    derive_available_utc, load_trading_calendar, CalendarCoverageError)

ET = "America/New_York"
PREREG_PATH = "qlab/llm_paper_prereg.json"
ANCHOR_PATH = "qlab/freeze_anchor.json"


# --------------------------------------------------------------------------- #
# 冻结口径加载（跑中一律以此为准，代码里不再另写常数）
# --------------------------------------------------------------------------- #
def _resolve(path: str) -> Path:
    """相对路径同时按 cwd 与 repo-root 解析（pytest 可能从 qlab/ 或仓根跑）。"""
    p = Path(path)
    if p.exists():
        return p
    for base in (_REPO_ROOT, _REPO_ROOT / "qlab", Path.cwd().parent):
        cand = base / path
        if cand.exists():
            return cand
        cand2 = base / Path(path).name
        if cand2.exists():
            return cand2
    raise FileNotFoundError(f"找不到 {path}（试过 cwd 与 repo-root）")


def load_prereg(path: str = PREREG_PATH) -> Dict[str, Any]:
    cfg = json.loads(_resolve(path).read_text(encoding="utf-8"))
    if cfg.get("paradigm") != "llm_agent":
        raise ValueError("冻结 config 的 paradigm 必须是 llm_agent（否则三关会被跳过）")
    return cfg


def load_anchor(path: str = ANCHOR_PATH) -> Dict[str, Any]:
    a = json.loads(_resolve(path).read_text(encoding="utf-8"))
    if a.get("status") != "anchored" or not (a.get("push_event") or {}).get("created_at"):
        raise ValueError("冻结锚点未就绪（status != anchored）→ 不得产生决策")
    return a


def frozen_grid(cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    """冻结的 seed × prompt 变体网格（跑后不得增删；DSR 的 V 来源）。"""
    fam = cfg["family"]
    grid = [{"seed": s, "prompt_variant": v}
            for s in fam["seeds"] for v in fam["prompt_variants"]]
    if len(grid) != fam["n_trials_total"]:
        raise ValueError(f"网格 {len(grid)} 与冻结 n_trials_total {fam['n_trials_total']} 不符")
    return grid


# --------------------------------------------------------------------------- #
# 决策记录
# --------------------------------------------------------------------------- #
@dataclass
class Decision:
    """单条决策（落盘后不可改；三时间戳 + 论点 + 置信度 + 目标仓位）。"""
    symbol: str
    target_weight: float                 # 目标仓位（NAV 占比；long/flat，绝不为负）
    confidence: float                    # 0~1
    thesis: str                          # 结构化论点（为何）
    evidence_refs: List[str]             # 支撑证据的 ref_id（可回溯到原始记录）
    evidence_available_utc: str          # 派生的**公开可得**时刻（时序核验用这个）
    evidence_acceptance_utc: str         # 原始受理/发布时刻（留档备查）
    decision_ts: str                     # LLM 产出决策的时刻
    intended_start: str                  # 机械算：决策后下一个非周末日开盘（不查假日）
    seed: int
    prompt_variant: str
    actual_start: Optional[str] = None   # 观测：价格腿首根真实 bar（执行时回填；未定为 None）
    actual_start_rolled_days: Optional[int] = None   # 相对 intended 的顺延天数（如实记录）
    actual_start_reason: str = "pending：价格腿未回填"
    model: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_log_entry(self) -> Dict[str, Any]:
        """转成 `validate_decision_log` 认的三时间戳形态（evidence 用**可得**时刻）。"""
        d = asdict(self)
        d["evidence_max_ts"] = self.evidence_available_utc     # 关键：不是受理时刻
        # 收益起算：已由价格腿观测到就用 actual_start（权威）；未回填则暂用 intended 并标 pending
        d["effective_from"] = self.actual_start or self.intended_start
        d["effective_from_is_actual"] = self.actual_start is not None
        return d


def intended_start(ts_utc) -> pd.Timestamp:
    """`intended_start` —— **纯机械**：决策后的下一个非周末日开盘（09:30 ET）。

    工部 2026-08-08 的结构性更正：`effective_from` 问的是**未来某天开不开市**，
    而**任何历史价格序列都答不了这个问题**（SPY 刷到昨天也不知道明天是否开市）。
    故此处**不查假日表、不依赖前瞻日历**，只做周末机械推进；真正的收益起算由
    `actual_start`（价格腿首根真实 bar）在执行时确定——见 `resolve_actual_start`。
    这样永久去掉对前瞻日历的依赖：不估算、不会在覆盖边缘失效。
    """
    et = pd.Timestamp(ts_utc).tz_convert(ET)
    open_today = et.replace(hour=9, minute=30, second=0, microsecond=0, nanosecond=0)
    if et < open_today and et.weekday() < 5:
        return open_today.tz_convert("UTC")          # 盘前决策 → 当日开盘
    d = (et + pd.Timedelta(days=1)).normalize()
    while d.weekday() >= 5:                          # 只跳周末（假日交给市场自己回答）
        d = d + pd.Timedelta(days=1)
    return d.replace(hour=9, minute=30).tz_convert("UTC")


def resolve_actual_start(intended, bar_dates: Sequence[Any]) -> Dict[str, Any]:
    """`actual_start` —— **观测而非预测**：收益起算 = 价格腿在 `intended` 当日或之后
    出现的**第一根真实 bar**。那天若没开市（假日/临时休市），自然顺延到真有 bar 的那天，
    并把顺延如实记进决策记录。「哪天真开市」由市场自己回答，比任何日历都权威。

    `bar_dates` 为价格腿返回的交易日序列（升序即可）。无可用 bar ⇒ `pending`（不猜）。
    """
    itd = pd.Timestamp(intended).tz_convert(ET).normalize()
    days = sorted({pd.Timestamp(b).tz_localize(None).normalize() if pd.Timestamp(b).tzinfo
                   else pd.Timestamp(b).normalize() for b in bar_dates})
    for d in days:
        if d >= itd.tz_localize(None):
            actual = d.tz_localize(ET).replace(hour=9, minute=30).tz_convert("UTC")
            rolled_days = int((d - itd.tz_localize(None)).days)
            return {"actual_start": actual.isoformat(), "rolled_days": rolled_days,
                    "rolled": bool(rolled_days > 0),
                    "reason": ("intended 当日无 bar（未开市）→ 顺延至首根真实 bar"
                               if rolled_days else "intended 当日即有真实 bar")}
    return {"actual_start": None, "rolled_days": None, "rolled": None,
            "reason": "价格腿尚无 >= intended 的 bar（行情未到/价格腿不可用）→ pending，不猜"}


def build_decision(*, symbol: str, target_weight: float, confidence: float, thesis: str,
                   evidence_records: Sequence[Dict[str, Any]], decision_ts,
                   seed: int, prompt_variant: str, model: str = "",
                   cfg: Optional[Dict[str, Any]] = None,
                   observed_days: Optional[Sequence[str]] = None) -> Decision:
    """由证据记录 + LLM 产出构造一条合规决策；**三条时序不等式在此强制成立**。

    `evidence_records` 需含 `source_time_utc`（信息源自身时间）与 `ref_id`。
    """
    cfg = cfg or load_prereg()
    sp = cfg["signal_params"]
    if target_weight < 0:
        raise ValueError("禁做空（long/flat only）：target_weight 不得为负")
    if target_weight > sp["single_name_cap"] + 1e-12:
        raise ValueError(f"{symbol} 目标仓位 {target_weight} 超单标的上限 {sp['single_name_cap']}")
    if not evidence_records:
        raise ValueError("决策必须有支撑证据（无据不决策）")

    # 证据的**可得**时刻取该条决策所有证据里最晚的一条
    # observed_days = 价格腿观测到的真实交易日；处理当日/近日证据必须传（否则陈旧 SPY 日历会 fail-closed）
    avail = [derive_available_utc(r["source_time_utc"], observed_days=observed_days) for r in evidence_records]
    acc = [pd.Timestamp(r["source_time_utc"]) for r in evidence_records]
    ev_available = max(avail)
    dts = pd.Timestamp(decision_ts)
    if dts.tzinfo is None:
        raise ValueError("decision_ts 必须带时区")
    if ev_available > dts:
        raise ValueError(
            f"前视：证据可得 {ev_available} 晚于决策 {dts}——该证据在决策时点尚不可用，不得据以决策")
    itd = intended_start(dts)
    return Decision(
        symbol=symbol, target_weight=float(target_weight), confidence=float(confidence),
        thesis=thesis, evidence_refs=[r.get("ref_id", "") for r in evidence_records],
        evidence_available_utc=ev_available.isoformat(),
        evidence_acceptance_utc=max(acc).isoformat(),
        decision_ts=dts.isoformat(), intended_start=itd.isoformat(),
        seed=seed, prompt_variant=prompt_variant, model=model)


def check_portfolio(decisions: Sequence[Decision], cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """组合级冻结约束：单标的上限 / 总仓上限 / 禁做空 / 杠杆 ≤1x。"""
    cfg = cfg or load_prereg()
    sp = cfg["signal_params"]
    gross = sum(d.target_weight for d in decisions)
    over = [d.symbol for d in decisions if d.target_weight > sp["single_name_cap"] + 1e-12]
    neg = [d.symbol for d in decisions if d.target_weight < 0]
    ok = (not over) and (not neg) and gross <= sp["gross_cap"] + 1e-12
    return {"ok": ok, "gross": gross, "gross_cap": sp["gross_cap"],
            "cash": max(0.0, 1.0 - gross), "violations_single_name": over,
            "violations_short": neg,
            "leverage_ok": gross <= float(cfg["leverage_cap"]) + 1e-12}


def validate_and_dump(decisions: Sequence[Decision], out_dir: str,
                      cfg: Optional[Dict[str, Any]] = None,
                      rejected_evidence: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """逐条时序核验 + 组合约束核验 + 落盘（决策一经落盘不可改）。**不出 verdict**。"""
    from research.gate.llm_paradigm import validate_decision_log
    cfg = cfg or load_prereg()
    anchor = load_anchor()
    log = [d.to_log_entry() for d in decisions]
    chk = validate_decision_log(log)
    port = check_portfolio(decisions, cfg)

    # 决策必须晚于冻结锚点（前向轨的定义）
    frozen_at = pd.Timestamp(anchor["push_event"]["created_at"])
    too_early = [d.symbol for d in decisions if pd.Timestamp(d.decision_ts) < frozen_at]

    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    payload = {
        "prereg_frozen_at": anchor["push_event"]["created_at"],
        "freeze_sha": anchor["freeze_sha"],
        "mode": "forward_paper",
        "n_decisions": len(decisions),
        "timing_check": asdict(chk) if hasattr(chk, "__dataclass_fields__") else chk.__dict__,
        "portfolio_check": port,
        "decisions_before_freeze": too_early,
        "rejected_evidence": list(rejected_evidence or []),   # RSS 拒收逐条留档
        "decisions": [asdict(d) for d in decisions],
        "note": "中途读数只作监控，不出 verdict（预注册 §4）；verdict 一律走 certify()+llm_paradigm",
    }
    ok = chk.ok and port["ok"] and not too_early
    payload["all_checks_passed"] = bool(ok)
    (out / "decisions.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    return payload
