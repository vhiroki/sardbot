"""Bar-by-bar backtester.

Deliberately not vectorized — clarity beats speed for Phase 1. Every fee, every
fill, every equity update is in plain code you can step through with a
debugger.

Convention: signal at index t means "target position from open[t+1] onward."
Signals on the last bar have nowhere to fill, so they are ignored. Fills always
happen at the open of the next bar; equity is marked-to-market at every close.

Optional risk overlay: if `stop_loss_atr_multiple` is set, on entry we record
a stop level at `entry_price - multiple * ATR(entry_bar)`. If a subsequent
bar's low touches that level we exit at the stop level (not the close), and
suppress re-entry until the strategy signal flips to 0 and back to 1.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from sardbot.engine.costs import CostModel
from sardbot.indicators.atr import atr as atr_indicator
from sardbot.risk.sizing import fixed_fraction
from sardbot.strategies.base import Strategy


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: pd.DataFrame
    positions: pd.Series
    signals: pd.Series
    initial_capital: float
    cost_model: CostModel
    strategy_name: str


def run_backtest(
    df: pd.DataFrame,
    strategy: Strategy,
    cost_model: CostModel | None = None,
    initial_capital: float = 10_000.0,
    fraction: float = 1.0,
    stop_loss_atr_multiple: float | None = None,
    atr_window: int = 14,
) -> BacktestResult:
    if df.empty:
        raise ValueError("Cannot backtest on empty dataframe")
    for col in ("open", "high", "low", "close"):
        if col not in df.columns:
            raise ValueError(f"DataFrame needs '{col}' column")

    cost_model = cost_model or CostModel()
    signals = strategy.generate_signals(df).reindex(df.index).fillna(0).astype(int)

    n = len(df)
    open_px = df["open"].to_numpy()
    high_px = df["high"].to_numpy()
    low_px = df["low"].to_numpy()
    close_px = df["close"].to_numpy()
    sig_arr = signals.to_numpy()

    if stop_loss_atr_multiple is not None:
        atr_series = atr_indicator(df, period=atr_window).to_numpy()
    else:
        atr_series = np.full(n, np.nan)

    cash = initial_capital
    units = 0.0
    target_pos = 0
    stop_level: float | None = None
    stopped_out = False  # suppress re-entry until signal cycles
    equity = [0.0] * n
    pos_units = [0.0] * n
    trades: list[dict] = []
    open_trade: dict | None = None

    for t in range(n):
        # 1. Execute the order decided at the previous bar's close, at this bar's open.
        if t > 0 and target_pos != _current_pos(units) and not stopped_out:
            fill_price = open_px[t]
            current_equity = cash + units * fill_price
            desired_notional = fixed_fraction(current_equity, fraction) if target_pos == 1 else 0.0
            desired_units = desired_notional / fill_price if fill_price > 0 else 0.0
            delta_units = desired_units - units
            trade_notional = abs(delta_units) * fill_price
            cost = cost_model.apply(trade_notional)
            cash -= delta_units * fill_price
            cash -= cost
            units = desired_units

            if delta_units > 0 and open_trade is None:
                open_trade = {
                    "entry_time": df.index[t],
                    "entry_price": fill_price,
                    "units": delta_units,
                    "entry_cost": cost,
                }
                if stop_loss_atr_multiple is not None and not np.isnan(atr_series[t]):
                    stop_level = fill_price - stop_loss_atr_multiple * atr_series[t]
                else:
                    stop_level = None
            elif delta_units < 0 and open_trade is not None:
                _close_trade(trades, open_trade, df.index[t], fill_price, cost, exit_reason="signal")
                open_trade = None
                stop_level = None

        # 2. Intra-bar stop-loss check.
        if units > 0 and stop_level is not None and low_px[t] <= stop_level:
            fill_price = stop_level  # assume stop fills at stop level (best-case approximation)
            trade_notional = abs(units) * fill_price
            cost = cost_model.apply(trade_notional)
            cash += units * fill_price
            cash -= cost
            if open_trade is not None:
                _close_trade(trades, open_trade, df.index[t], fill_price, cost, exit_reason="stop_loss")
                open_trade = None
            units = 0.0
            stop_level = None
            stopped_out = True
            target_pos = 0

        # 3. Mark to market at this bar's close.
        equity[t] = cash + units * close_px[t]
        pos_units[t] = units

        # 4. Decide target position to fill at next bar's open.
        new_signal = int(sig_arr[t])
        if stopped_out and new_signal == 0:
            stopped_out = False  # cooldown released; ready to take next entry
        if not stopped_out:
            target_pos = new_signal
        else:
            target_pos = 0

    # If we ended in an open position, close it virtually for trade accounting.
    if open_trade is not None:
        last_close = close_px[-1]
        exit_units = open_trade["units"]
        pnl = exit_units * (last_close - open_trade["entry_price"]) - open_trade["entry_cost"]
        trades.append({
            "entry_time": open_trade["entry_time"],
            "exit_time": df.index[-1],
            "entry_price": open_trade["entry_price"],
            "exit_price": last_close,
            "units": exit_units,
            "pnl": pnl,
            "return_pct": (last_close / open_trade["entry_price"] - 1.0)
                          - open_trade["entry_cost"] / (exit_units * open_trade["entry_price"]),
            "exit_reason": "open_at_end",
            "open_at_end": True,
        })

    return BacktestResult(
        equity_curve=pd.Series(equity, index=df.index, name="equity"),
        trades=pd.DataFrame(trades),
        positions=pd.Series(pos_units, index=df.index, name="position_units"),
        signals=signals,
        initial_capital=initial_capital,
        cost_model=cost_model,
        strategy_name=strategy.name,
    )


def _close_trade(trades, open_trade, exit_time, exit_price, exit_cost, exit_reason: str):
    units = open_trade["units"]
    pnl = units * (exit_price - open_trade["entry_price"]) - open_trade["entry_cost"] - exit_cost
    trades.append({
        "entry_time": open_trade["entry_time"],
        "exit_time": exit_time,
        "entry_price": open_trade["entry_price"],
        "exit_price": exit_price,
        "units": units,
        "pnl": pnl,
        "return_pct": (exit_price / open_trade["entry_price"] - 1.0)
                      - (open_trade["entry_cost"] + exit_cost) / (units * open_trade["entry_price"]),
        "exit_reason": exit_reason,
        "open_at_end": False,
    })


def _current_pos(units: float) -> int:
    if units > 0:
        return 1
    if units < 0:
        return -1
    return 0
