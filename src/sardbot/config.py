"""Typed config loaded from config/default.yaml.

YAML in, validated dataclass out. CLI flags override values when needed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

DEFAULT_CONFIG_PATH = Path("config/default.yaml")


class MarketConfig(BaseModel):
    exchange: str = "binance"
    symbol: str = "BTC/USDT"
    timeframe: str = "1d"
    since: str = "2018-01-01"

    def since_dt(self) -> datetime:
        return datetime.fromisoformat(self.since).replace(tzinfo=timezone.utc)


class BacktestConfig(BaseModel):
    initial_capital: float = 10_000.0
    fee_bps: float = 10.0
    slippage_bps: float = 5.0
    oos_fraction: float = 0.2


class SMAConfig(BaseModel):
    fast: int = 50
    slow: int = 200


class DonchianConfig(BaseModel):
    entry: int = 20
    exit_: int = 10
    trend_filter_window: int | None = None


class StrategyConfig(BaseModel):
    default: str = "sma_crossover"
    sma_crossover: SMAConfig = Field(default_factory=SMAConfig)
    donchian_breakout: DonchianConfig = Field(default_factory=DonchianConfig)


class RiskConfig(BaseModel):
    stop_loss_atr_multiple: float | None = None
    atr_window: int = 14


class PathsConfig(BaseModel):
    data_raw: str = "data/raw"
    reports: str = "reports"


class Config(BaseModel):
    market: MarketConfig = Field(default_factory=MarketConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> Config:
    p = Path(path)
    if not p.exists():
        return Config()
    with p.open() as f:
        raw = yaml.safe_load(f) or {}
    return Config(**raw)
