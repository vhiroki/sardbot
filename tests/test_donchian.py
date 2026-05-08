import numpy as np
import pandas as pd
import pytest

from sardbot.strategies.donchian import DonchianBreakout


def _ohlc(highs, lows, closes):
    n = len(closes)
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({"open": closes, "high": highs, "low": lows, "close": closes,
                         "volume": [1.0] * n}, index=idx)


def test_warmup_signal_zero():
    closes = np.linspace(100, 110, 30)
    df = _ohlc(closes, closes, closes)
    s = DonchianBreakout(entry=20, exit_=10).generate_signals(df)
    assert (s.iloc[:20] == 0).all()


def test_breakout_enters_long():
    # 25 flat bars at 100, then a strong breakout above on bar 25.
    closes = [100.0] * 25 + [120.0]
    highs = [100.5] * 25 + [121.0]
    lows = [99.5] * 25 + [119.0]
    df = _ohlc(highs, lows, closes)
    s = DonchianBreakout(entry=20, exit_=10).generate_signals(df)
    assert s.iloc[-1] == 1


def test_breakdown_exits():
    # Up 30 bars to enter, then sharp drop.
    closes = list(np.linspace(100, 200, 30)) + [50.0]
    highs = list(np.linspace(101, 201, 30)) + [51.0]
    lows = list(np.linspace(99, 199, 30)) + [49.0]
    df = _ohlc(highs, lows, closes)
    s = DonchianBreakout(entry=20, exit_=10).generate_signals(df)
    assert s.iloc[-2] == 1  # was long before the crash
    assert s.iloc[-1] == 0  # exited on the drop


def test_invalid_params():
    with pytest.raises(ValueError):
        DonchianBreakout(entry=1, exit_=10)
    with pytest.raises(ValueError):
        DonchianBreakout(entry=20, exit_=1)


def test_trend_filter_blocks_entry_below_ma():
    # Long downtrend then a small breakout: without filter, we'd enter on the
    # breakout. With a trend filter, close still below SMA(200), so no entry.
    closes = list(np.linspace(1000, 100, 250))  # 250 bars trending down
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    # Force a tiny breakout on the last bar
    closes[-1] = max(closes[-21:-1]) + 5  # close above prior 20-day high
    highs[-1] = closes[-1] + 1
    df = _ohlc(highs, lows, closes)

    no_filter = DonchianBreakout(entry=20, exit_=10).generate_signals(df)
    with_filter = DonchianBreakout(entry=20, exit_=10, trend_filter_window=200).generate_signals(df)
    assert no_filter.iloc[-1] == 1
    assert with_filter.iloc[-1] == 0


def test_trend_filter_invalid():
    with pytest.raises(ValueError):
        DonchianBreakout(trend_filter_window=1)


def test_no_lookahead_uses_prior_window():
    # The breakout level must be the prior-window max, not include today.
    # If today's high were included, every fresh-high day would trigger entry
    # trivially. We engineer a case where today's high is highest of the window
    # but yesterday's close was below the prior-window high — so signal stays 0.
    closes = [100.0] * 25
    highs = [100.5] * 24 + [200.0]  # bar 24 has a huge intraday high...
    lows = [99.5] * 25
    closes[24] = 100.0  # ...but closes back at 100. No breakout on close.
    df = _ohlc(highs, lows, closes)
    s = DonchianBreakout(entry=20, exit_=10).generate_signals(df)
    assert s.iloc[-1] == 0
