import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from sardbot.engine.costs import CostModel
from sardbot.paper.state import Position, State
from sardbot.paper.storage import LocalStorage
from sardbot.paper.trader import EQUITY_PATH, STATE_PATH, TRADES_PATH, run_iteration


PARAMS = {"entry": 20, "exit": 10, "trend_filter": 200, "stop_atr": 2.0, "atr_window": 14}


def _df(closes, opens=None, highs=None, lows=None):
    n = len(closes)
    idx = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame({
        "open": opens if opens is not None else closes,
        "high": highs if highs is not None else closes,
        "low": lows if lows is not None else closes,
        "close": closes, "volume": [1.0] * n,
    }, index=idx)


def test_idempotency_skip_already_processed():
    state = State.fresh("BTC/USDT", "donchian_breakout_filt200", PARAMS, 10_000)
    state.last_processed_bar = "2020-01-30T00:00:00+00:00"
    df = _df(np.linspace(100, 200, 30))
    new, events, alert = run_iteration(state, df, CostModel(0, 0))
    assert events == []
    assert alert is None
    # State unchanged (last_processed_bar still the same date as latest bar, skipped)
    assert new.last_processed_bar == "2020-01-30T00:00:00+00:00"


def test_fresh_state_no_signal_yet():
    """During warmup (< 200 bars for trend filter), no entry should fire."""
    state = State.fresh("BTC/USDT", "donchian_breakout_filt200", PARAMS, 10_000)
    df = _df(np.linspace(100, 200, 50))  # only 50 bars, way less than 200
    new, events, _ = run_iteration(state, df, CostModel(0, 0))
    assert events == []
    assert not new.position.is_long


def test_entry_on_breakout_after_warmup():
    """After enough bars, an upward breakout should trigger entry."""
    # 250 bars trending up — by the end, fast SMA > slow, in donchian breakout territory
    state = State.fresh("BTC/USDT", "donchian_breakout_filt200", PARAMS, 10_000)
    closes = list(np.linspace(100, 1000, 250))
    df = _df(closes, highs=[c + 1 for c in closes], lows=[c - 1 for c in closes])
    new, events, _ = run_iteration(state, df, CostModel(0, 0))
    assert any(e["type"] == "entry" for e in events)
    assert new.position.is_long
    assert new.position.units > 0
    assert new.position.stop_level is not None


def test_stop_loss_triggers_on_low():
    """Already long; today's low touches stop level → exit at stop."""
    state = State.fresh("BTC/USDT", "donchian_breakout_filt200", PARAMS, 10_000)
    state.position = Position(
        is_long=True, entry_time="2020-12-01T00:00:00+00:00",
        entry_price=500.0, units=20.0, stop_level=480.0,
    )
    state.equity.current = 20.0 * 500.0  # MTM at entry close

    # Build df where last bar gaps down through stop
    closes = [500.0] * 250 + [490.0]  # last bar closes above stop
    highs = [501.0] * 250 + [495.0]
    lows = [499.0] * 250 + [475.0]   # but low touches 475 < 480
    df = _df(closes, highs=highs, lows=lows)
    new, events, _ = run_iteration(state, df, CostModel(0, 0))
    assert any(e["type"] == "exit_stop" for e in events)
    assert not new.position.is_long
    # stopped_out_cooldown is set at stop-out, but is released same-bar if
    # signal is 0 (which is the case here — flat market). The functional check
    # that matters is "position is flat", which we already asserted.


def test_kill_switch_fires_on_deep_drawdown():
    state = State.fresh("BTC/USDT", "donchian_breakout_filt200", PARAMS, 10_000)
    # Force deep drawdown
    state.equity.current = 7_000  # -30% from initial
    state.equity.high_watermark = 10_000

    df = _df(np.linspace(100, 105, 250))
    _, _, alert = run_iteration(state, df, CostModel(0, 0), kill_switch_dd=-0.25)
    assert alert is not None
    assert alert["type"] == "kill_switch"


def test_storage_roundtrip(tmp_path):
    storage = LocalStorage(base_dir=tmp_path)
    s = State.fresh("BTC/USDT", "x", PARAMS, 10_000)
    storage.write_text(STATE_PATH, s.to_json())
    raw = storage.read_text(STATE_PATH)
    assert raw is not None
    restored = State.from_json(raw)
    assert restored.symbol == s.symbol
    assert restored.equity.current == s.equity.current


def test_storage_append_parquet(tmp_path):
    storage = LocalStorage(base_dir=tmp_path)
    storage.append_parquet("trades.parquet", pd.DataFrame([{"a": 1, "b": "x"}]))
    storage.append_parquet("trades.parquet", pd.DataFrame([{"a": 2, "b": "y"}]))
    df = storage.read_parquet("trades.parquet")
    assert len(df) == 2


def test_state_drawdown_zero_when_at_high_watermark():
    s = State.fresh("BTC/USDT", "x", PARAMS, 10_000)
    assert s.drawdown() == 0.0


def test_state_drawdown_negative_when_below():
    import math
    s = State.fresh("BTC/USDT", "x", PARAMS, 10_000)
    s.equity.current = 8_000
    assert math.isclose(s.drawdown(), -0.2, abs_tol=1e-9)
