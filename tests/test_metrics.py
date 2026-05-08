import math

import numpy as np
import pandas as pd

from sardbot.metrics.performance import (
    cagr,
    max_drawdown,
    num_trades,
    sharpe,
    total_return,
    win_rate,
)


def _series(values, freq="D"):
    idx = pd.date_range("2020-01-01", periods=len(values), freq=freq, tz="UTC")
    return pd.Series(values, index=idx)


def test_total_return_basic():
    eq = _series([100, 110, 121])
    assert math.isclose(total_return(eq), 0.21, abs_tol=1e-9)


def test_cagr_double_in_one_year():
    eq = _series(np.linspace(100, 200, 366))  # 365 periods
    assert math.isclose(cagr(eq, periods_per_year=365), 1.0, abs_tol=1e-9)


def test_max_drawdown_known_curve():
    # Goes 100 -> 200 -> 100. From peak 200 to trough 100 is -50%.
    eq = _series([100, 150, 200, 150, 100])
    assert math.isclose(max_drawdown(eq), -0.5, abs_tol=1e-9)


def test_max_drawdown_monotonic_up_is_zero():
    eq = _series([100, 110, 120, 130])
    assert max_drawdown(eq) == 0.0


def test_sharpe_zero_variance_is_zero_by_convention():
    # Flat curve => returns are exactly 0 every period => std == 0 => we return 0.0.
    eq = _series([100.0] * 100)
    assert sharpe(eq, periods_per_year=365) == 0.0


def test_sharpe_random_walk_is_finite():
    rng = np.random.default_rng(42)
    rets = rng.normal(loc=0.0005, scale=0.01, size=500)
    eq = _series(100 * np.cumprod(1 + rets))
    s = sharpe(eq, periods_per_year=365)
    assert math.isfinite(s)
    assert -10 < s < 10


def test_win_rate_and_num_trades():
    trades = pd.DataFrame([
        {"pnl": 10, "open_at_end": False},
        {"pnl": -5, "open_at_end": False},
        {"pnl": 20, "open_at_end": False},
        {"pnl": -1, "open_at_end": False},
    ])
    assert win_rate(trades) == 0.5
    assert num_trades(trades) == 4


def test_open_trades_excluded():
    trades = pd.DataFrame([
        {"pnl": 10, "open_at_end": False},
        {"pnl": float("nan"), "open_at_end": True},
    ])
    assert num_trades(trades) == 1
    assert win_rate(trades) == 1.0
