"""Walk-forward analysis.

A single backtest reports one number for "the strategy over the whole period."
That hides the only thing that matters: did the strategy work *consistently*,
or did it luck into one or two great years?

Walk-forward chops the data into rolling fixed-length test windows and
reports metrics per window. We run the strategy once on the full dataframe
(continuous run, like it would be in real life) and then slice the equity
curve by window. For each window:

- window_return: equity at end / equity at start - 1
- window_max_dd:  worst drawdown experienced WITHIN the window
- window_num_trades: trades whose exit fell inside the window
- window_winners: number of those trades with pnl > 0

Then a summary across all windows: % positive, mean, median, std, worst.

A robust strategy looks like: most windows positive, no catastrophic loser,
moderate variance. A strategy that's "great in backtest" but rides on 1-2
massive years tends to show: a few huge winners and many flat or negative
windows.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from sardbot.engine.backtester import BacktestResult, run_backtest
from sardbot.engine.costs import CostModel
from sardbot.strategies.base import Strategy


@dataclass
class WalkForwardResult:
    windows: pd.DataFrame  # one row per test window
    summary: dict[str, float]
    equity_curve: pd.Series  # underlying continuous-run equity curve, for plotting


def compute_window_stats(
    equity_curve: pd.Series,
    trades: pd.DataFrame | None = None,
    test_window_days: int = 180,
    warmup_days: int = 250,
) -> WalkForwardResult:
    """Slice an equity curve into rolling test windows and compute per-window metrics.

    Pure analysis: works for single-asset backtests, multi-asset portfolios, or
    any equity curve indexed by time.
    """
    n = len(equity_curve)
    if n < warmup_days + test_window_days:
        raise ValueError(
            f"Need at least {warmup_days + test_window_days} bars, got {n}"
        )

    rows = []
    start = warmup_days
    window_id = 0
    while start + test_window_days <= n:
        window_eq = equity_curve.iloc[start:start + test_window_days]
        window_index = window_eq.index
        running_max = window_eq.cummax()
        dd = window_eq / running_max - 1.0

        num_trades = 0
        winners = 0
        if trades is not None and not trades.empty and "exit_time" in trades.columns:
            mask = (trades["exit_time"] >= window_index[0]) & \
                   (trades["exit_time"] <= window_index[-1])
            wt = trades[mask]
            num_trades = int(len(wt[wt.get("open_at_end", False) == False]))  # noqa: E712
            winners = int((wt["pnl"] > 0).sum()) if "pnl" in wt.columns else 0

        rows.append({
            "window_id": window_id,
            "start_date": window_index[0].date(),
            "end_date": window_index[-1].date(),
            "return": float(window_eq.iloc[-1] / window_eq.iloc[0] - 1.0),
            "max_dd": float(dd.min()),
            "num_trades": num_trades,
            "winners": winners,
        })

        start += test_window_days
        window_id += 1

    windows = pd.DataFrame(rows)
    if windows.empty:
        summary = {"n_windows": 0}
    else:
        rets = windows["return"]
        dds = windows["max_dd"]
        summary = {
            "n_windows": int(len(windows)),
            "pct_positive": float((rets > 0).mean()),
            "mean_return": float(rets.mean()),
            "median_return": float(rets.median()),
            "std_return": float(rets.std(ddof=1)) if len(rets) > 1 else 0.0,
            "worst_return": float(rets.min()),
            "best_return": float(rets.max()),
            "mean_max_dd": float(dds.mean()),
            "worst_max_dd": float(dds.min()),
            "total_trades": int(windows["num_trades"].sum()),
        }

    return WalkForwardResult(windows=windows, summary=summary, equity_curve=equity_curve)


def walk_forward(
    df: pd.DataFrame,
    strategy: Strategy,
    cost_model: CostModel | None = None,
    initial_capital: float = 10_000.0,
    test_window_days: int = 180,
    warmup_days: int = 250,
    stop_loss_atr_multiple: float | None = None,
    atr_window: int = 14,
) -> WalkForwardResult:
    """Run one continuous backtest, then slice equity into per-window metrics."""
    if len(df) < warmup_days + test_window_days:
        raise ValueError(
            f"Need at least {warmup_days + test_window_days} bars, got {len(df)}"
        )

    bt = run_backtest(df, strategy, cost_model, initial_capital,
                      stop_loss_atr_multiple=stop_loss_atr_multiple,
                      atr_window=atr_window)

    return compute_window_stats(bt.equity_curve, bt.trades, test_window_days, warmup_days)
