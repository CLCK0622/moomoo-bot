"""金标准复现 —— 检测**模型漂移**（工部 2026-08-08 第三节）。

`temperature=0` 只是**近似**确定性：供应商可以在同名模型后面换权重，批处理与浮点也带非确定性。
本轨按年计，**中途模型被换掉 = 实验对象在实验中间变了**，而净值序列不会有任何提示——
这个混淆因子比 seed 离散度严重得多，且**唯一验收证据**的连续性全押在它上面。

做法：每轮决策附带跑一次**金标准复现**——固定历史证据 + 固定 prompt（`llm_paper_gold_probe.json`）
→ 输出与首次记录的基线**逐字**比对：

| 结果 | 状态 | 处置 |
|--|--|--|
| 逐字相同 | `determinism_ok` | 记一条；顺带证明「seed 名义化」的前提仍成立 |
| 不同 | **`model_drift_detected`** | 立刻标记 + 落 ALERT + 回报工部；**seed 自此由名义变为实际**，且需判定证据期是否重新起算 |
| 无基线 | `baseline_established` | 首轮**建立**基线；**这一轮什么都没验证到**，不得读成通过 |
| 探针输入被改过 | **`probe_input_changed`** | **fail-closed**：比对对象变了，「相同」不再有意义 |

三条防 fail-open 的设计（本轨反复栽的那一类）：

1. **基线写一次即冻结**：漂移**绝不**回写基线。否则每次漂移都自动接受新基线，护栏永久静默。
2. **基线绑定探针指纹**：探针文件（prompt/证据/参数）被改一个字符即 `probe_input_changed` 并 fail-closed。
   否则「通过」可能是在比对一个已经换过的输入——护栏看着绿、实际什么都没测（假阴性那一侧）。
3. **无基线 ≠ 通过**：首轮只 `baseline_established`，状态与 `determinism_ok` 严格区分。

**一条如实的边界（本护栏抓不到的）**：本轨的决策者就是 agent 自己，没有可编程的 LLM 端点，
探针输出由调用方传入 ⇒ 一个**不诚实**的调用方可以把基线原样回传伪造「一致」。本护栏能抓的是
**诚实调用方遇到的无声漂移**，抓不了主动造假。可外部核验的补偿：探针输出与其 sha256
**逐轮原样写进 round JSON**，都察院可拿仓内基线独立复核。
另一侧的边界：长输出遇上批处理/浮点非确定性可能**误报**——方向安全（误报只会升级上报，不会静默放过），
故探针输出契约刻意保持紧凑；误报与真漂移由人看 diff 判定，代码不猜。
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from qlab.llm_paper.decision_chain import _resolve  # noqa: E402  （同一套 cwd/repo-root 解析）

GOLD_PROBE_PATH = "qlab/llm_paper_gold_probe.json"
BASELINE_PATH = "qlab/llm_paper_determinism_baseline.json"
# 测试隔离用（与配额台账 QLAB_AV_QUOTA_LEDGER 同一套路）：绝不让单测碰真基线——
# 真基线写一次即冻结，被单测建立起来就等于用假输出把护栏钉死了。
BASELINE_ENV = "QLAB_LLM_DETERMINISM_BASELINE"

STATUS_OK = "determinism_ok"
STATUS_BASELINE_ESTABLISHED = "baseline_established"
STATUS_DRIFT = "model_drift_detected"
STATUS_PROBE_CHANGED = "probe_input_changed"
STATUS_BASELINE_MISSING = "baseline_missing"


class ProbeUnverifiable(RuntimeError):
    """护栏无法测量（探针输入被改 / 探针缺失）→ fail-closed，绝不当作通过。"""


class BaselineImmutable(RuntimeError):
    """基线写一次即冻结：改写 = 让漂移自动被接受 = 护栏永久静默。"""


class DriftAlarm(RuntimeError):
    """检出模型漂移。默认不打断本轮如实记录，仅在调用方要求时抛。"""


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical(obj: Any) -> str:
    """规范化序列化：排序键 + 固定分隔符，使指纹只随**内容**变，不随排版变。"""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def load_probe(path: str = GOLD_PROBE_PATH) -> Dict[str, Any]:
    try:
        return json.loads(_resolve(path).read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ProbeUnverifiable(
            f"找不到金标准探针 {path} → 无法做漂移检查；**不得跳过**（跳过即护栏静默）") from e


def probe_fingerprint(probe: Dict[str, Any]) -> str:
    """整份探针的内容指纹。改一个字符即变 ⇒ 与基线不符 ⇒ fail-closed。"""
    return _sha256(canonical(probe))


def probe_request(probe: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """交给决策阶段去执行的那次固定调用（prompt + 证据 + 参数，逐轮一字不变）。"""
    p = probe or load_probe()
    return {"probe_id": p["probe_id"], "prompt": p["prompt_template"],
            "evidence": p["evidence"], "params": p["params"],
            "output_contract": p["output_contract"],
            "fingerprint": probe_fingerprint(p)}


def _baseline_path(path: str = BASELINE_PATH) -> str:
    """默认路径可由 `QLAB_LLM_DETERMINISM_BASELINE` 覆盖（仅供测试隔离）。

    显式传入的 `path` 优先级最高——调用方指名道姓时不该被环境变量偷换。
    """
    import os
    if path != BASELINE_PATH:
        return path
    return os.environ.get(BASELINE_ENV) or path


def load_baseline(path: str = BASELINE_PATH) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(_resolve(_baseline_path(path)).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


def _baseline_target(path: str = BASELINE_PATH) -> Path:
    p = _baseline_path(path)
    try:
        return _resolve(p)
    except FileNotFoundError:
        return Path(p) if Path(p).is_absolute() else _REPO_ROOT / p


def record_baseline(*, output: str, model: str, probe: Optional[Dict[str, Any]] = None,
                    round_id: str = "", path: str = BASELINE_PATH) -> Dict[str, Any]:
    """建立基线。**已存在即拒**——写一次就冻结，漂移不得改写（否则护栏永久静默）。"""
    if load_baseline(path) is not None:
        raise BaselineImmutable(
            f"{path} 已存在 → 拒绝改写。漂移的正确处置是标 {STATUS_DRIFT} 并回报，"
            "不是把新输出接受成新基线。")
    p = probe or load_probe()
    rec = {
        "status": "baselined",
        "probe_id": p["probe_id"],
        "probe_fingerprint": probe_fingerprint(p),
        "model": model,
        "output": output,
        "output_sha256": _sha256(output),
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "recorded_at_round": round_id,
        "immutable": ("写一次即冻结。漂移一律标 model_drift_detected 并回报工部，"
                      "**绝不改写本文件**——改写等于每次漂移都自动被接受，护栏永久失效。"),
    }
    tgt = _baseline_target(path)
    tgt.parent.mkdir(parents=True, exist_ok=True)
    tgt.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    return rec


def check(*, output: str, model: str, probe: Optional[Dict[str, Any]] = None,
          baseline_path: str = BASELINE_PATH) -> Dict[str, Any]:
    """纯比对，不写任何文件。`output` 须为模型**原样**输出（不 strip、不规范化、不解析）。"""
    p = probe or load_probe()
    fp = probe_fingerprint(p)
    base = load_baseline(baseline_path)
    out_sha = _sha256(output)
    res: Dict[str, Any] = {"probe_id": p["probe_id"], "probe_fingerprint": fp,
                           "model": model, "output_sha256": out_sha,
                           "output_matches": None, "reasons": []}
    if base is None:
        res["status"] = STATUS_BASELINE_MISSING
        res["note"] = "尚无基线 → 本轮**什么都没验证到**，不得读成通过"
        return res
    res["baseline_recorded_at"] = base.get("recorded_at_utc")
    res["baseline_model"] = base.get("model")
    if base.get("probe_fingerprint") != fp:
        res["status"] = STATUS_PROBE_CHANGED
        res["reasons"].append("probe_input_changed")
        res["note"] = ("探针输入与基线记录的不符（探针文件被改过）→ **fail-closed**："
                       "此时「输出相同」比对的已不是同一个输入，绿灯毫无意义（假阴性）")
        return res
    res["output_matches"] = bool(output == base.get("output"))   # 逐字，不做任何归一
    if not res["output_matches"]:
        res["reasons"].append("output_differs")
    if model and base.get("model") and model != base["model"]:
        res["reasons"].append("model_id_changed")
    if res["reasons"]:
        res["status"] = STATUS_DRIFT
        res["note"] = ("检出漂移 → 立刻回报工部。自此 **seed 由名义变为实际**（离散度不再只来自 prompt 变体），"
                       "且需判定「证据期是否重新起算」：实验对象换了，之前的净值段与之后不是同一个对象。")
        res["diff_preview"] = _diff_preview(base.get("output", ""), output)
    else:
        res["status"] = STATUS_OK
        res["note"] = "输出逐字一致 ⇒ 模型未被换掉，且「temperature=0 下 seed 无离散」的前提仍成立"
    return res


def _diff_preview(expected: str, got: str, width: int = 240) -> Dict[str, Any]:
    """给人看的最小 diff：首个分歧位置 + 两侧片段（判「误报 vs 真漂移」要看这个）。"""
    i = 0
    for i, (a, b) in enumerate(zip(expected, got)):
        if a != b:
            break
    else:
        i = min(len(expected), len(got))
    return {"first_divergence_index": i,
            "len_expected": len(expected), "len_got": len(got),
            "expected_around": expected[max(0, i - 40): i + width],
            "got_around": got[max(0, i - 40): i + width]}


def verify_or_establish(*, output: str, model: str, round_id: str = "",
                        probe: Optional[Dict[str, Any]] = None,
                        baseline_path: str = BASELINE_PATH,
                        raise_on_drift: bool = False) -> Dict[str, Any]:
    """每轮决策调用这一条。

    - 无基线 → **建立**基线，状态 `baseline_established`（明确「本轮未验证到任何东西」）；
    - 探针输入被改 → 抛 `ProbeUnverifiable`（fail-closed，本轮不得当作通过）；
    - 漂移 → 返回 `model_drift_detected`（**不回写基线**）。默认不抛：本轮决策是真数据、
      应如实记录，但必须带着告警落盘并回报工部；`raise_on_drift=True` 时才抛。
    """
    if not isinstance(output, str) or not output.strip():
        raise ProbeUnverifiable("探针输出为空 → 无法比对；**不得跳过漂移检查**（跳过即护栏静默）")
    p = probe or load_probe()
    res = check(output=output, model=model, probe=p, baseline_path=baseline_path)
    if res["status"] == STATUS_PROBE_CHANGED:
        raise ProbeUnverifiable(f"{res['note']}｜探针指纹 {res['probe_fingerprint']} "
                                f"≠ 基线记录；请核对 {GOLD_PROBE_PATH} 是否被改动")
    if res["status"] == STATUS_BASELINE_MISSING:
        rec = record_baseline(output=output, model=model, probe=p, round_id=round_id,
                              path=baseline_path)
        res = dict(res)
        res.update({"status": STATUS_BASELINE_ESTABLISHED, "baseline_recorded_at": rec["recorded_at_utc"],
                    "note": "首轮：基线已建立。**本轮未验证到任何东西**，不得读成 determinism_ok"})
    if res["status"] == STATUS_DRIFT and raise_on_drift:
        raise DriftAlarm(res["note"])
    res["drift"] = (res["status"] == STATUS_DRIFT)
    res["verified"] = (res["status"] == STATUS_OK)
    return res
