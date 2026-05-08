"""Side-by-side strategy vs benchmarks comparison.

Always runs the candidate against BuyAndHold and DCA so the user can see
whether the strategy is actually adding value over "do nothing."
"""

from __future__ import annotations

import pandas as pd

from sardbot.engine.backtester import BacktestResult, run_backtest
from sardbot.engine.costs import CostModel
from sardbot.engine.dca import run_dca
from sardbot.metrics.performance import summary
from sardbot.strategies.base import Strategy
from sardbot.strategies.benchmarks import BuyAndHold


def compare(
    df: pd.DataFrame,
    strategy: Strategy | list[Strategy],
    cost_model: CostModel | None = None,
    initial_capital: float = 10_000.0,
    periods_per_year: int = 365,
    dca_frequency: str = "W",
    stop_loss_atr_multiple: float | None = None,
    atr_window: int = 14,
) -> tuple[pd.DataFrame, dict[str, BacktestResult]]:
    """Run candidate(s) against B&H and DCA benchmarks.

    Stop-loss applies ONLY to candidates — applying a stop to a buy-and-hold
    benchmark would defeat its purpose as "do nothing" reference.
    """
    cost_model = cost_model or CostModel()
    candidates = strategy if isinstance(strategy, list) else [strategy]

    results: dict[str, BacktestResult] = {}
    for s in candidates:
        results[s.name] = run_backtest(
            df, s, cost_model, initial_capital,
            stop_loss_atr_multiple=stop_loss_atr_multiple, atr_window=atr_window,
        )
    results["buy_and_hold"] = run_backtest(df, BuyAndHold(), cost_model, initial_capital)
    results[f"dca_{dca_frequency.lower()}"] = run_dca(df, cost_model, initial_capital, frequency=dca_frequency)

    rows = {name: summary(r, periods_per_year) for name, r in results.items()}
    table = pd.DataFrame(rows).T
    return table, results
