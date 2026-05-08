"""Performance metrics computed from an equity curve.

All metrics are derived from `equity_curve` (a pd.Series indexed by time, values
in cash terms). No surprises: read the math and you can verify each one.

- total_return: equity[-1] / equity[0] - 1
- CAGR: (equity[-1] / equity[0]) ** (1 / years) - 1
- max_drawdown: min over time of (equity / running_max - 1). Always <= 0.
- sharpe: (mean_excess_return / stddev_return) * sqrt(periods_per_year).
  We use simple returns and rf=0 by default.
- win_rate: fraction of closed trades with pnl > 0.
- num_trades: number of round-trip trades.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def total_return(equity: pd.Series) -> float:
    if len(equity) < 2 or equity.iloc[0] == 0:
        return 0.0
    return float(equity.iloc[-1] / equity.iloc[0] - 1.0)


def cagr(equity: pd.Series, periods_per_year: int = 365) -> float:
    if len(equity) < 2 or equity.iloc[0] == 0:
        return 0.0
    n_periods = len(equity) - 1
    years = n_periods / periods_per_year
    if years <= 0:
        return 0.0
    ratio = equity.iloc[-1] / equity.iloc[0]
    if ratio <= 0:
        return -1.0
    return float(ratio ** (1.0 / years) - 1.0)


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    return float(drawdown.min())


def sharpe(equity: pd.Series, periods_per_year: int = 365, rf: float = 0.0) -> float:
    if len(equity) < 3:
        return 0.0
    returns = equity.pct_change().dropna()
    excess = returns - rf / periods_per_year
    std = excess.std(ddof=1)
    if std == 0 or np.isnan(std):
        return 0.0
    return float(excess.mean() / std * np.sqrt(periods_per_year))


def win_rate(trades: pd.DataFrame) -> float:
    closed = _closed_trades(trades)
    if closed.empty:
        return 0.0
    return float((closed["pnl"] > 0).mean())


def num_trades(trades: pd.DataFrame) -> int:
    return int(len(_closed_trades(trades)))


def _closed_trades(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty or "pnl" not in trades.columns:
        return trades.iloc[0:0]
    if "open_at_end" in trades.columns:
        return trades[trades["open_at_end"].fillna(False) == False]  # noqa: E712
    return trades


def summary(result, periods_per_year: int = 365) -> dict[str, float]:
    """Convenience: every metric for a BacktestResult, in a flat dict."""
    eq = result.equity_curve
    return {
        "total_return": total_return(eq),
        "cagr": cagr(eq, periods_per_year),
        "max_drawdown": max_drawdown(eq),
        "sharpe": sharpe(eq, periods_per_year),
        "win_rate": win_rate(result.trades),
        "num_trades": num_trades(result.trades),
        "final_equity": float(eq.iloc[-1]) if len(eq) else 0.0,
    }
