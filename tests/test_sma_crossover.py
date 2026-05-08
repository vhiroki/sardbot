import numpy as np
import pandas as pd
import pytest

from sardbot.strategies.sma_crossover import SMACrossover


def _df(closes):
    n = len(closes)
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes,
                         "volume": [1.0] * n}, index=idx)


def test_signal_zero_until_slow_ma_defined():
    df = _df(np.linspace(100, 200, 250))
    s = SMACrossover(fast=10, slow=50).generate_signals(df)
    assert (s.iloc[:49] == 0).all()


def test_uptrend_eventually_long():
    df = _df(np.linspace(100, 1000, 500))
    s = SMACrossover(fast=10, slow=50).generate_signals(df)
    # In a steady uptrend, fast > slow eventually.
    assert s.iloc[-1] == 1


def test_downtrend_eventually_flat():
    df = _df(np.linspace(1000, 100, 500))
    s = SMACrossover(fast=10, slow=50).generate_signals(df)
    assert s.iloc[-1] == 0


def test_invalid_params():
    with pytest.raises(ValueError):
        SMACrossover(fast=200, slow=50)
    with pytest.raises(ValueError):
        SMACrossover(fast=1, slow=50)
