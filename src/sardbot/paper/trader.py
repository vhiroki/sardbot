"""Paper trader: one iteration of the bot's lifecycle.

Each invocation (cron-triggered or manual):
1. Load state.
2. Fetch latest OHLCV.
3. Idempotency check: skip if we already processed the latest closed bar.
4. Generate signal on full history.
5. Check stop-loss against latest bar's low (intra-bar protection).
6. Apply signal-driven entries/exits at latest close.
7. Mark-to-market and update high watermark.
8. Kill switch check.
9. Persist state and append to logs.
10. Notify on trades, stop-outs, kill switch trips.

Convention: we operate on closed bars only. The bot should run AFTER the
day's UTC candle closes — schedule for 00:05 UTC of the next day.

Equity model (single source of truth):
- We track a virtual `cash` and `units` each iteration.
- If position.is_long: cash=0 (all-in convention), units>0.
- If flat:             cash=equity.current, units=0.
- Equity invariant: equity.current = cash + units * last_close.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from sardbot.data.loader import CCXTLoader
from sardbot.engine.costs import CostModel
from sardbot.indicators.atr import atr as atr_indicator
from sardbot.paper.notifier import Notifier, NullNotifier
from sardbot.paper.state import Position, State
from sardbot.paper.storage import Storage
from sardbot.strategies.donchian import DonchianBreakout

log = logging.getLogger(__name__)

STATE_PATH = "state.json"
TRADES_PATH = "trades.parquet"
EQUITY_PATH = "equity.parquet"


def run_iteration(
    state: State,
    df: pd.DataFrame,
    cost_model: CostModel,
    kill_switch_dd: float = -0.25,
) -> tuple[State, list[dict], dict | None]:
    """Pure logic. Mutates state, returns (new_state, events, kill_switch_alert)."""
    if df.empty:
        return state, [], None

    last_bar = df.iloc[-1]
    last_bar_ts = df.index[-1].isoformat()

    if state.last_processed_bar == last_bar_ts:
        log.info("Bar %s already processed; skipping.", last_bar_ts)
        return state, [], None

    strategy = DonchianBreakout(
        entry=state.params["entry"],
        exit_=state.params["exit"],
        trend_filter_window=state.params.get("trend_filter"),
    )
    signals = strategy.generate_signals(df)
    new_signal = int(signals.iloc[-1])

    atr_window = state.params.get("atr_window", 14)
    atr_series = atr_indicator(df, period=atr_window)
    atr_value = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else None

    # Reconstruct cash/units snapshot from state.
    if state.position.is_long:
        cash = 0.0
        units = state.position.units
    else:
        cash = state.equity.current
        units = 0.0

    events: list[dict] = []
    just_stopped_out = False

    # ---- 1. Intra-bar stop-loss (highest priority) --------------------------
    if state.position.is_long and state.position.stop_level is not None:
        if float(last_bar["low"]) <= state.position.stop_level:
            fill = state.position.stop_level
            cost = cost_model.apply(units * fill)
            proceeds = units * fill - cost
            pnl = proceeds - units * state.position.entry_price
            events.append({
                "time": last_bar_ts, "type": "exit_stop", "price": fill,
                "units": units, "pnl": pnl, "reason": "stop_loss",
            })
            cash = proceeds
            units = 0.0
            state.position = Position()
            state.stopped_out_cooldown = True
            just_stopped_out = True

    # ---- 2. Cooldown release: signal must hit 0 to allow re-entry -----------
    if state.stopped_out_cooldown and new_signal == 0:
        state.stopped_out_cooldown = False

    target_long = (new_signal == 1) and not state.stopped_out_cooldown

    # ---- 3. Signal-driven entry/exit (only if no stop fired this bar) -------
    if not just_stopped_out:
        if not state.position.is_long and target_long:
            fill = float(last_bar["close"])
            cost = cost_model.apply(cash)
            units = (cash - cost) / fill if fill > 0 else 0.0
            cash = 0.0
            stop_level = fill - state.params.get("stop_atr", 2.0) * atr_value if atr_value else None
            state.position = Position(
                is_long=True, entry_time=last_bar_ts, entry_price=fill,
                units=units, stop_level=stop_level,
            )
            events.append({
                "time": last_bar_ts, "type": "entry", "price": fill,
                "units": units, "stop_level": stop_level, "reason": "signal_long",
            })

        elif state.position.is_long and not target_long:
            fill = float(last_bar["close"])
            cost = cost_model.apply(units * fill)
            proceeds = units * fill - cost
            pnl = proceeds - units * state.position.entry_price
            events.append({
                "time": last_bar_ts, "type": "exit_signal", "price": fill,
                "units": units, "pnl": pnl, "reason": "signal_flat",
            })
            cash = proceeds
            units = 0.0
            state.position = Position()

    # ---- 4. Mark-to-market equity at latest close ---------------------------
    last_close = float(last_bar["close"])
    state.equity.current = cash + units * last_close
    state.update_high_watermark()
    state.last_signal = new_signal
    state.last_processed_bar = last_bar_ts
    state.stamp_run()

    # ---- 5. Kill switch -----------------------------------------------------
    alert = None
    dd = state.drawdown()
    if dd <= kill_switch_dd:
        alert = {
            "type": "kill_switch",
            "drawdown": dd,
            "threshold": kill_switch_dd,
            "message": f"Drawdown {dd:.2%} <= threshold {kill_switch_dd:.2%}",
        }

    return state, events, alert


def run_once(
    storage: Storage,
    notifier: Notifier | None = None,
    symbol: str = "BTC/USDT",
    timeframe: str = "1d",
    initial_capital: float = 10_000.0,
    fee_bps: float = 10.0,
    slippage_bps: float = 5.0,
    kill_switch_dd: float = -0.25,
    cache_dir: str = "data/raw",
    strategy_params: dict | None = None,
) -> dict:
    """Top-level orchestration: load state, fetch data, run iteration, persist."""
    notifier = notifier or NullNotifier()
    strategy_params = strategy_params or {
        "entry": 20, "exit": 10, "trend_filter": 200, "stop_atr": 2.0, "atr_window": 14,
    }

    raw = storage.read_text(STATE_PATH)
    if raw is None:
        state = State.fresh(symbol, "donchian_breakout_filt200", strategy_params, initial_capital)
        log.info("Initialized fresh state for %s", symbol)
    else:
        state = State.from_json(raw)

    loader = CCXTLoader()
    since = datetime(2018, 1, 1, tzinfo=timezone.utc)
    df = loader.fetch_ohlcv(symbol, timeframe, since=since, cache_dir=Path(cache_dir))

    cost_model = CostModel(fee_bps=fee_bps, slippage_bps=slippage_bps)
    new_state, events, alert = run_iteration(state, df, cost_model, kill_switch_dd)

    storage.write_text(STATE_PATH, new_state.to_json())

    if events:
        storage.append_parquet(TRADES_PATH, pd.DataFrame(events))

    equity_row = pd.DataFrame([{
        "time": new_state.last_processed_bar,
        "equity": new_state.equity.current,
        "high_watermark": new_state.equity.high_watermark,
        "drawdown": new_state.drawdown(),
        "is_long": new_state.position.is_long,
    }])
    storage.append_parquet(EQUITY_PATH, equity_row)

    for ev in events:
        msg = f"📊 *{ev['type']}* {symbol}\nprice: ${ev['price']:,.2f}\nreason: {ev['reason']}"
        if "pnl" in ev and ev["pnl"] is not None:
            msg += f"\npnl: ${ev['pnl']:,.2f}"
        notifier.send(msg)

    if alert:
        notifier.send(
            f"🚨 *KILL SWITCH* {symbol}\n{alert['message']}\n"
            f"bot will stop entering new positions"
        )

    return {
        "bar": new_state.last_processed_bar,
        "signal": new_state.last_signal,
        "is_long": new_state.position.is_long,
        "equity": new_state.equity.current,
        "drawdown": new_state.drawdown(),
        "events": events,
        "alert": alert,
    }
