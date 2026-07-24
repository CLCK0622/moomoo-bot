"""
统一数据模型 —— 把三家 venue 的行情归一到同一口径。

价格单位：美元概率价，0.0 ~ 1.0（合约到期赢方按 $1 结算）。
买入口径：
  cost_yes = 买到 1 份 YES 的即时可成交价（对手 ask）
  cost_no  = 买到 1 份 NO  的即时可成交价（对手 ask）
"""
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any


@dataclass
class Quote:
    venue: str                      # "kalshi" | "polymarket" | "limitless"
    market_id: str                  # venue 内唯一标识（ticker / conditionId / id）
    title: str
    cost_yes: Optional[float] = None    # 买 YES 的 ask
    cost_no: Optional[float] = None     # 买 NO 的 ask
    yes_bid: Optional[float] = None
    no_bid: Optional[float] = None
    last: Optional[float] = None
    volume: Optional[float] = None
    liquidity: Optional[float] = None
    expiration_ts: Optional[int] = None   # Unix 秒
    event_key: Optional[str] = None       # venue 内事件分组键（如 Kalshi event_ticker）
    raw: Dict[str, Any] = field(default_factory=dict)
    ts: Optional[float] = None            # 本地采样时间戳（Unix 秒）

    def mid_yes(self) -> Optional[float]:
        """YES 中间价：优先 (yes_bid + cost_yes)/2，退化到 last。"""
        if self.yes_bid is not None and self.cost_yes is not None:
            return round((self.yes_bid + self.cost_yes) / 2.0, 6)
        return self.last

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("raw", None)   # raw 体积大，落盘时剔除
        return d


@dataclass
class ArbEdge:
    """一次跨 venue 套利机会评估（某一方向）。

    方向：在 buy_yes_venue 买 YES，在 buy_no_venue 买 NO；同事件同结算 =>
    持有组合到期必得 $1。净边 = 1 - cost_yes - cost_no - fee_yes - fee_no。
    """
    event_label: str
    buy_yes_venue: str
    buy_no_venue: str
    cost_yes: float
    cost_no: float
    fee_yes: float
    fee_no: float
    gross_edge: float      # 1 - cost_yes - cost_no（未扣费）
    net_edge: float        # 扣费后，真正可捕获的每份净利（美元）
    capturable: bool       # net_edge > 0
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
