"""Average True Range (ATR).

ATR measures typical bar-to-bar movement size. It's volatility expressed in
the asset's own price units, so a "2 ATR" stop adapts to whether the asset is
calm (small stop) or wild (wider stop) — much better than a flat percent.

True Range at bar t:
    TR_t = max(high_t - low_t,
               |high_t - close_{t-1}|,
               |low_t  - close_{t-1}|)

ATR is the moving average of TR over `period` bars. We use Wilder's
smoothing (the original 1978 definition), which is equivalent to an EMA
with alpha = 1/period.
"""

from __future__ import annotations

import pandas as pd


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if period < 2:
        raise ValueError(f"period must be >= 2, got {period}")
    if not all(c in df.columns for c in ("high", "low", "close")):
        raise ValueError("df must have 'high', 'low', 'close' columns")

    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)

    # Wilder's smoothing: equivalent to EMA with alpha = 1/period.
    return tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
