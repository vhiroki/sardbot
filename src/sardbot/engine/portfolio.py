"""Multi-asset portfolio: same strategy on N coins, equal capital sleeves.

Design choice: each asset has its own independent capital sleeve (= total / N).
When one sleeve exits, its cash sits idle — it does not flow into another
asset. This is the simplest design and matches the diversification story
("spread risk across uncorrelated bets") rather than cash-recycling.

Cash recycling is more capital-efficient but introduces position-sizing
coupling between assets that makes the result hard to attribute. We can add
it later as a separate `CashPooledPortfolio` if the basic version proves
insufficient.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from sardbot.engine.backtester import BacktestResult, run_backtest
from sardbot.engine.costs import CostModel
from sardbot.strategies.base import Strategy


@dataclass
class PortfolioResult:
    equity_curve: pd.Series           # combined across all sleeves
    per_asset: dict[str, BacktestResult]
    initial_capital: float
    symbols: list[str]


def run_portfolio(
    dfs: dict[str, pd.DataFrame],
    strategy_factory: Callable[[], Strategy],
    cost_model: CostModel | None = None,
    initial_capital: float = 10_000.0,
    stop_loss_atr_multiple: float | None = None,
    atr_window: int = 14,
) -> PortfolioResult:
    if not dfs:
        raise ValueError("Need at least one asset")
    n = len(dfs)
    sleeve_capital = initial_capital / n
    cost_model = cost_model or CostModel()

    per_asset: dict[str, BacktestResult] = {}
    for symbol, df in dfs.items():
        per_asset[symbol] = run_backtest(
            df, strategy_factory(), cost_model, sleeve_capital,
            stop_loss_atr_multiple=stop_loss_atr_multiple,
            atr_window=atr_window,
        )

    # Build a common index from the union of all sleeve indices, then sum
    # forward-filled equity curves. Sleeves with later start dates are valued
    # at sleeve_capital (idle cash) before their first bar.
    all_idx = sorted(set().union(*(r.equity_curve.index for r in per_asset.values())))
    common = pd.DatetimeIndex(all_idx)
    combined = pd.Series(0.0, index=common, name="equity")
    for r in per_asset.values():
        eq = r.equity_curve.reindex(common).ffill().fillna(sleeve_capital)
        combined = combined + eq

    return PortfolioResult(
        equity_curve=combined,
        per_asset=per_asset,
        initial_capital=initial_capital,
        symbols=list(dfs.keys()),
    )
