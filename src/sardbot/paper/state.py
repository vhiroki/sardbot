"""Paper-trading state schema.

The State is the bot's complete in-memory understanding of where it is:
current position, accumulated equity, last signal seen, stop level, etc.
It's serialized to JSON between runs (each Cloud Run Job invocation reads
state, mutates it, writes it back).

Idempotency hinge: `last_processed_bar`. If the job runs twice on the same
day, the second run sees that the latest bar was already processed and
exits without modifying state. This matters when we eventually go live —
we never want to fire two orders for one signal.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass
class Position:
    is_long: bool = False
    entry_time: str | None = None  # ISO 8601 UTC
    entry_price: float | None = None
    units: float = 0.0
    stop_level: float | None = None


@dataclass
class Equity:
    initial_capital: float = 10_000.0
    current: float = 10_000.0
    high_watermark: float = 10_000.0


@dataclass
class State:
    version: int = 1
    symbol: str = "BTC/USDT"
    strategy: str = "donchian_breakout_filt200"
    params: dict = field(default_factory=dict)
    position: Position = field(default_factory=Position)
    equity: Equity = field(default_factory=Equity)
    last_signal: int = 0
    last_processed_bar: str | None = None  # ISO 8601 UTC
    stopped_out_cooldown: bool = False
    last_run: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> State:
        d = json.loads(s)
        return cls(
            version=d.get("version", 1),
            symbol=d["symbol"],
            strategy=d["strategy"],
            params=d.get("params", {}),
            position=Position(**d["position"]),
            equity=Equity(**d["equity"]),
            last_signal=d.get("last_signal", 0),
            last_processed_bar=d.get("last_processed_bar"),
            stopped_out_cooldown=d.get("stopped_out_cooldown", False),
            last_run=d.get("last_run"),
        )

    @classmethod
    def fresh(cls, symbol: str, strategy: str, params: dict, initial_capital: float) -> State:
        return cls(
            symbol=symbol,
            strategy=strategy,
            params=params,
            equity=Equity(
                initial_capital=initial_capital,
                current=initial_capital,
                high_watermark=initial_capital,
            ),
        )

    def stamp_run(self) -> None:
        self.last_run = datetime.now(tz=timezone.utc).isoformat()

    def update_high_watermark(self) -> None:
        if self.equity.current > self.equity.high_watermark:
            self.equity.high_watermark = self.equity.current

    def drawdown(self) -> float:
        """Current drawdown vs high watermark (negative or zero)."""
        if self.equity.high_watermark <= 0:
            return 0.0
        return self.equity.current / self.equity.high_watermark - 1.0
