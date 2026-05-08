import numpy as np
import pandas as pd
import pytest

from sardbot.engine.costs import CostModel
from sardbot.engine.walkforward import walk_forward
from sardbot.strategies.benchmarks import BuyAndHold


def _df(n, drift=0.0005, seed=0):
    rng = np.random.default_rng(seed)
    closes = 100 * np.cumprod(1 + rng.normal(drift, 0.01, n))
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({
        "open": closes, "high": closes * 1.01, "low": closes * 0.99,
        "close": closes, "volume": [1.0] * n
    }, index=idx)


def test_walk_forward_produces_expected_window_count():
    df = _df(1000)
    r = walk_forward(df, BuyAndHold(), CostModel(0, 0), 10_000,
                     test_window_days=180, warmup_days=250)
    # (1000 - 250) // 180 = 4
    assert r.summary["n_windows"] == 4


def test_walk_forward_window_dates_continuous():
    df = _df(1000)
    r = walk_forward(df, BuyAndHold(), CostModel(0, 0), 10_000,
                     test_window_days=180, warmup_days=250)
    starts = pd.to_datetime(r.windows["start_date"])
    diffs = starts.diff().dropna().dt.days
    assert (diffs == 180).all()


def test_walk_forward_too_short_data():
    df = _df(100)
    with pytest.raises(ValueError):
        walk_forward(df, BuyAndHold(), CostModel(), 10_000,
                     test_window_days=180, warmup_days=250)


def test_walk_forward_summary_fields():
    df = _df(1000)
    r = walk_forward(df, BuyAndHold(), CostModel(0, 0), 10_000,
                     test_window_days=180, warmup_days=250)
    expected_keys = {"n_windows", "pct_positive", "mean_return", "median_return",
                     "std_return", "worst_return", "best_return", "mean_max_dd",
                     "worst_max_dd", "total_trades"}
    assert expected_keys.issubset(r.summary.keys())
    assert 0.0 <= r.summary["pct_positive"] <= 1.0
