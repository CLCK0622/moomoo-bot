"""
跨 venue 二元合约套利净额计算（纸面，仅评估）。

同一事件、同一结算口径下：
  在 venue_A 买 1 份 YES（付 cost_yes_A），在 venue_B 买 1 份 NO（付 cost_no_B），
  组合到期必得 $1（无论结果）。每份净利：
      net = 1 - cost_yes_A - cost_no_B - fee_A(cost_yes_A) - fee_B(cost_no_B)
  两个方向都算，取更优；net > 0 才是扣费后可捕获的机会。

重要限定（写进 notes / 报告，避免高估）：
  - 结算口径必须真等价（见 event_matcher 警示），否则不是无风险套利。
  - cost 必须是**可成交价**且订单簿深度足够；参考价/中间价会高估边。
  - 资金锁定到结算（跨日/跨周），年化需按持有期折算；且跨 venue 资金
    （Kalshi 美元账户 vs Polymarket/Limitless 链上 USDC）无法互相净额，
    实际需两边各备库存，属「库存型」而非「零成本无风险」。
"""
from typing import Optional, Tuple
from .models import Quote, ArbEdge
from . import fees


def _one_direction(buy_yes: Quote, buy_no: Quote, label: str) -> Optional[ArbEdge]:
    if buy_yes.cost_yes is None or buy_no.cost_no is None:
        return None
    cy, cn = float(buy_yes.cost_yes), float(buy_no.cost_no)
    fy = fees.leg_fee(buy_yes.venue, cy)
    fn = fees.leg_fee(buy_no.venue, cn)
    gross = 1.0 - cy - cn
    net = gross - fy - fn
    notes = []
    if buy_yes.raw.get("price_is_reference") or buy_no.raw.get("price_is_reference"):
        notes.append("含参考价(非可成交ask)，边被高估")
    if buy_yes.raw.get("no_derived_from_yes_bid") or buy_no.raw.get("no_derived_from_yes_bid"):
        notes.append("NO价由1-YESbid近似")
    return ArbEdge(
        event_label=label,
        buy_yes_venue=buy_yes.venue,
        buy_no_venue=buy_no.venue,
        cost_yes=round(cy, 6), cost_no=round(cn, 6),
        fee_yes=round(fy, 6), fee_no=round(fn, 6),
        gross_edge=round(gross, 6),
        net_edge=round(net, 6),
        capturable=net > 0,
        notes="; ".join(notes),
    )


def best_edge(qa: Quote, qb: Quote, label: str = "") -> Optional[ArbEdge]:
    """两方向取更优净边。label 缺省用两边标题。"""
    label = label or f"{qa.title[:40]} | {qb.title[:40]}"
    cand = [e for e in (_one_direction(qa, qb, label),
                        _one_direction(qb, qa, label)) if e is not None]
    if not cand:
        return None
    return max(cand, key=lambda e: e.net_edge)


def within_venue_book_check(q: Quote) -> Optional[float]:
    """venue 内部无套利自检：yes_ask + no_ask 应 >= 1（否则同 venie 内即有套利，
    多半是抓取口径问题）。返回 (yes_ask+no_ask)，供诊断。"""
    if q.cost_yes is None or q.cost_no is None:
        return None
    return round(q.cost_yes + q.cost_no, 6)
