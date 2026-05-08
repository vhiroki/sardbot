"""Transaction cost model.

bps = "basis points" = 1/10000. So 10 bps = 0.10%.

We charge fee + slippage on each side of a round-trip trade. Defaults assume
Binance spot taker (~0.10% fee) plus a conservative 5 bps slippage. Real
slippage depends on order book depth and order size — Phase 1 uses a flat
estimate; tighten this when you actually paper-trade and observe fills.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    fee_bps: float = 10.0
    slippage_bps: float = 5.0

    @property
    def total_bps_per_side(self) -> float:
        return self.fee_bps + self.slippage_bps

    def apply(self, notional: float) -> float:
        """Cost in cash terms for trading `notional` of base asset (one side)."""
        return abs(notional) * self.total_bps_per_side / 10_000.0
