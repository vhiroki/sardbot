"""Dollar-cost averaging simulation.

DCA doesn't fit the Strategy contract (which is a {-1, 0, 1} target position).
Instead, here we simulate periodic cash drips: every period (e.g. weekly), buy
a fixed cash amount of the asset and hold forever.

Returns a BacktestResult so it can be compared apples-to-apples to other
strategies in reports.
"""

from __future__ import annotations

import pandas as pd

from sardbot.engine.backtester import BacktestResult
from sardbot.engine.costs import CostModel


def run_dca(
    df: pd.DataFrame,
    cost_model: CostModel | None = None,
    initial_capital: float = 10_000.0,
    frequency: str = "W",
) -> BacktestResult:
    """Simulate DCA: split initial_capital across periodic buys.

    The capital is divided evenly across all scheduled buy dates, then on each
    one we buy at that bar's open. Held to the end.
    """
    if df.empty:
        raise ValueError("Cannot run DCA on empty dataframe")
    cost_model = cost_model or CostModel()

    schedule_index = df.resample(frequency).first().dropna().index
    schedule_index = schedule_index.intersection(df.index)
    if schedule_index.empty:
        raise ValueError(f"No buy dates found at frequency {frequency}")

    per_buy_cash = initial_capital / len(schedule_index)
    buy_set = set(schedule_index)

    cash = initial_capital
    units = 0.0
    equity = []
    positions = []
    trades = []

    for ts, row in df.iterrows():
        if ts in buy_set:
            fill_price = row["open"]
            cost = cost_model.apply(per_buy_cash)
            spendable = per_buy_cash - cost
            new_units = spendable / fill_price if fill_price > 0 else 0.0
            cash -= per_buy_cash
            units += new_units
            trades.append({
                "entry_time": ts,
                "exit_time": pd.NaT,
                "entry_price": fill_price,
                "exit_price": float("nan"),
                "units": new_units,
                "pnl": float("nan"),
                "return_pct": float("nan"),
                "open_at_end": True,
            })
        equity.append(cash + units * row["close"])
        positions.append(units)

    return BacktestResult(
        equity_curve=pd.Series(equity, index=df.index, name="equity"),
        trades=pd.DataFrame(trades),
        positions=pd.Series(positions, index=df.index, name="position_units"),
        signals=pd.Series(0, index=df.index, dtype=int, name="signal"),
        initial_capital=initial_capital,
        cost_model=cost_model,
        strategy_name=f"dca_{frequency.lower()}",
    )
