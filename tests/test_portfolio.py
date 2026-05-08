import math

import numpy as np
import pandas as pd

from sardbot.engine.costs import CostModel
from sardbot.engine.portfolio import run_portfolio
from sardbot.strategies.benchmarks import BuyAndHold


def _df(closes, start="2020-01-01"):
    n = len(closes)
    idx = pd.date_range(start, periods=n, freq="D", tz="UTC")
    return pd.DataFrame({"open": closes, "high": closes, "low": closes,
                         "close": closes, "volume": [1.0] * n}, index=idx)


def test_portfolio_sums_per_asset_equity():
    df_a = _df(np.linspace(100, 200, 50))
    df_b = _df(np.linspace(50, 100, 50))
    r = run_portfolio({"A": df_a, "B": df_b}, lambda: BuyAndHold(),
                      CostModel(0, 0), initial_capital=2_000)
    # Each sleeve starts with 1000 and roughly doubles (BuyAndHold fills at open[1],
    # so misses the first bar's gain — expected ~3900-4000 not exactly 4000).
    assert 3_800 < r.equity_curve.iloc[-1] < 4_100


def test_portfolio_independent_sleeves():
    """Loss in one asset does not consume the other sleeve's cash."""
    df_up = _df(np.linspace(100, 200, 50))
    df_down = _df(np.linspace(100, 50, 50))
    r = run_portfolio({"UP": df_up, "DOWN": df_down}, lambda: BuyAndHold(),
                      CostModel(0, 0), initial_capital=2_000)
    final_up = r.per_asset["UP"].equity_curve.iloc[-1]
    final_down = r.per_asset["DOWN"].equity_curve.iloc[-1]
    assert final_up > 1_500  # ~doubled from 1000
    assert final_down < 700  # ~halved
    # Total = sum, no interaction
    assert math.isclose(r.equity_curve.iloc[-1], final_up + final_down, rel_tol=1e-9)


def test_portfolio_handles_different_start_dates():
    df_a = _df(np.linspace(100, 110, 50), start="2020-01-01")
    df_b = _df(np.linspace(100, 110, 30), start="2020-01-21")  # starts 20 days later
    r = run_portfolio({"A": df_a, "B": df_b}, lambda: BuyAndHold(),
                      CostModel(0, 0), initial_capital=2_000)
    # Common index covers both
    assert r.equity_curve.index[0] == df_a.index[0]
    assert r.equity_curve.index[-1] == df_a.index[-1]
    # Before B starts, B sleeve = 1000 (idle cash)
    assert r.equity_curve.iloc[0] == 2_000  # both sleeves at face value


def test_portfolio_empty_raises():
    import pytest
    with pytest.raises(ValueError):
        run_portfolio({}, lambda: BuyAndHold(), CostModel(), 1000)
