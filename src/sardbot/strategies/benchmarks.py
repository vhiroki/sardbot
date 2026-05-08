"""Benchmark strategies expressible as a {0, 1} position series.

DCA is *not* here — it requires periodic cash drip, which doesn't fit the
Strategy contract. See engine/dca.py.
"""

from __future__ import annotations

import pandas as pd

from sardbot.strategies.base import Strategy


class BuyAndHold(Strategy):
    name = "buy_and_hold"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        return pd.Series(1, index=df.index, dtype=int, name="signal")
