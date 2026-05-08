import math

import numpy as np
import pandas as pd
import pytest

from sardbot.indicators.atr import atr


def _ohlc(highs, lows, closes):
    n = len(closes)
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({"open": closes, "high": highs, "low": lows, "close": closes,
                         "volume": [1.0] * n}, index=idx)


def test_atr_constant_range():
    # Every bar has high=101, low=99 (range = 2). True range = 2 every bar.
    # ATR should converge to 2 after warmup.
    n = 100
    closes = [100.0] * n
    highs = [101.0] * n
    lows = [99.0] * n
    df = _ohlc(highs, lows, closes)
    a = atr(df, period=14)
    assert math.isclose(a.iloc[-1], 2.0, abs_tol=1e-9)


def test_atr_warmup_is_nan():
    df = _ohlc([101] * 30, [99] * 30, [100] * 30)
    a = atr(df, period=14)
    assert a.iloc[:13].isna().all()


def test_atr_invalid_period():
    df = _ohlc([101] * 30, [99] * 30, [100] * 30)
    with pytest.raises(ValueError):
        atr(df, period=1)


def test_atr_picks_up_gap():
    # Gap up: previous close 100, today's low 110, today's high 120.
    # TR_today = max(120-110, |120-100|, |110-100|) = 20.
    closes = [100.0] * 20 + [115.0]
    highs = [101.0] * 20 + [120.0]
    lows = [99.0] * 20 + [110.0]
    df = _ohlc(highs, lows, closes)
    a = atr(df, period=14)
    assert a.iloc[-1] > a.iloc[-2]
