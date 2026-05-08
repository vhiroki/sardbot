"""Donchian Channel Breakout (Richard Dennis "Turtle Trader" rule).

Long entry: close breaks above the highest high of the prior `entry` bars.
Long exit:  close breaks below the lowest  low  of the prior `exit_`  bars.

Asymmetric lookbacks (entry > exit) is the classic configuration: enter slowly
on confirmed strength, exit quickly on weakness.

Optional trend filter (Faber 2007): if `trend_filter_window` is set, entries
are only taken when close > SMA(trend_filter_window). This gates the strategy
to bull regimes only and skips long sideways markets where breakouts are
mostly false. Once in a position, the filter does not force exit — only the
Donchian exit rule applies.

The state is path-dependent (you're either in a position or not), so this
needs a small bar-by-bar loop instead of a pure vectorized comparison. The
signal at index t still means "target position from open[t+1] onward."
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from sardbot.strategies.base import Strategy


class DonchianBreakout(Strategy):
    name = "donchian_breakout"

    def __init__(self, entry: int = 20, exit_: int = 10, trend_filter_window: int | None = None):
        if entry < 2:
            raise ValueError(f"entry ({entry}) must be >= 2")
        if exit_ < 2:
            raise ValueError(f"exit_ ({exit_}) must be >= 2")
        if trend_filter_window is not None and trend_filter_window < 2:
            raise ValueError(f"trend_filter_window must be None or >= 2, got {trend_filter_window}")
        self.entry = entry
        self.exit = exit_
        self.trend_filter_window = trend_filter_window
        if trend_filter_window:
            self.name = f"donchian_breakout_filt{trend_filter_window}"

    def generate_signals(self, df: pd.DataFrame) -> pd.Series:
        if "high" not in df.columns or "low" not in df.columns:
            raise ValueError("DonchianBreakout needs 'high' and 'low' columns")

        upper = df["high"].rolling(self.entry, min_periods=self.entry).max().shift(1)
        lower = df["low"].rolling(self.exit, min_periods=self.exit).min().shift(1)
        close = df["close"]

        if self.trend_filter_window is not None:
            trend_ma = close.rolling(self.trend_filter_window,
                                     min_periods=self.trend_filter_window).mean().shift(1)
            entry_allowed = (close > trend_ma).to_numpy()
        else:
            entry_allowed = np.ones(len(df), dtype=bool)

        entry_trigger = (close > upper).to_numpy() & entry_allowed
        exit_trigger = (close < lower).to_numpy()

        warmup = upper.isna().to_numpy() | lower.isna().to_numpy()
        if self.trend_filter_window is not None:
            trend_ma = close.rolling(self.trend_filter_window,
                                     min_periods=self.trend_filter_window).mean().shift(1)
            warmup = warmup | trend_ma.isna().to_numpy()

        n = len(df)
        signal = np.zeros(n, dtype=int)
        in_position = False
        for t in range(n):
            if warmup[t]:
                signal[t] = 0
                continue
            if not in_position and entry_trigger[t]:
                in_position = True
            elif in_position and exit_trigger[t]:
                in_position = False
            signal[t] = 1 if in_position else 0

        return pd.Series(signal, index=df.index, name="signal")
