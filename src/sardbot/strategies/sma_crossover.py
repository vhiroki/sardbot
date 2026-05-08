"""SMA crossover ("Golden Cross / Death Cross").

Long when the fast simple moving average is above the slow one, flat otherwise.
The most studied trend-following rule; useful as a baseline because its behavior
is intuitive and well-documented.
"""

from __future__ import annotations

import pandas as pd

from sardbot.strategies.base import Strategy


class SMACrossover(Strategy):
    name = "sma_crossover"

    def __init__(self, fast: int = 50, slow: int = 200):
        if fast >= slow:
            raise ValueError(f"fast ({fast}) must be < slow ({slow})")
        if fast < 2:
            raise ValueError(f"fast ({fast}) must be >= 2")
        self.fast = fast
        self.slow = slow

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        close = df["close"]
        fast_ma = close.rolling(self.fast, min_periods=self.fast).mean()
        slow_ma = close.rolling(self.slow, min_periods=self.slow).mean()
        signal = (fast_ma > slow_ma).astype(int)
        # Bars before slow MA is defined produce NaN comparison -> 0 (flat).
        signal = signal.where(slow_ma.notna(), 0)
        signal.name = "signal"
        return signal.astype(int)
