from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class Config:
    # Removed: VST, CRWD, NEE, ISRG, LLY (R1 — consistently negative)
    symbols: list[str] = field(default_factory=lambda: [
        "TSLA", "NVDA", "AMZN", "GOOGL", "META", "AAPL", "MSFT", "MU", "SNDK", "STX",
        "ASML", "TSM", "AMD", "INTC", "AVGO", "MRVL", "KLAC", "QCOM", "ADI",
        "AMAT", "GEV", "CEG", "PLTR", "VRT", "APP", "SNPS", "CDNS", "SCCO",
        "HOOD", "CRCL", "MPWR", "WDC", "PANW", "LRCX", "CVX", "XOM", "NVO",
        "COST", "WMT", "CB", "SMH", "TQQQ", "AXP", "LMT", "UNH",
    ])
    initial_capital: float = 100_000.0
    max_positions: int = 5
    commission_per_trade: float = 1.0
    slippage_pct: float = 0.0002
    history_months: int = 6
    cache_dir: Path = field(default_factory=lambda: Path("data/cache"))
    reports_dir: Path = field(default_factory=lambda: Path("reports"))
    n_cv_folds: int = 5
    n_trials: int = 200
    dashboard_port: int = 8050
    moomoo_host: str = "127.0.0.1"
    moomoo_port: int = 11111

    @property
    def position_size(self) -> float:
        return self.initial_capital / self.max_positions
