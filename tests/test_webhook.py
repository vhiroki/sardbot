"""Tests for webhook command handlers — invoked directly, no HTTP."""
from __future__ import annotations

import os

import pandas as pd
import pytest

from sardbot.paper.state import Position, State
from sardbot.paper.storage import LocalStorage
from sardbot.paper.trader import EQUITY_PATH, STATE_PATH, TRADES_PATH


PARAMS = {"entry": 20, "exit": 10, "trend_filter": 200, "stop_atr": 2.0, "atr_window": 14}


@pytest.fixture
def storage_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SARDBOT_STORAGE", f"local:{tmp_path}")
    return tmp_path


def _seed_state(storage_dir, **overrides):
    storage = LocalStorage(base_dir=storage_dir)
    state = State.fresh("BTC/USDT", "donchian_breakout_filt200", PARAMS, 10_000)
    for k, v in overrides.items():
        if "." in k:
            obj_name, attr = k.split(".")
            setattr(getattr(state, obj_name), attr, v)
        else:
            setattr(state, k, v)
    storage.write_text(STATE_PATH, state.to_json())
    return storage, state


def test_status_no_state_yet(storage_dir):
    from sardbot.paper.webhook import cmd_status
    out = cmd_status()
    assert "sem estado" in out


def test_status_flat(storage_dir):
    _seed_state(storage_dir, last_processed_bar="2025-01-01T00:00:00+00:00")
    from sardbot.paper.webhook import cmd_status
    out = cmd_status()
    assert "flat" in out
    assert "BTC/USDT" in out


def test_status_long_with_stop(storage_dir):
    _seed_state(
        storage_dir,
        **{"position.is_long": True, "position.entry_price": 50_000.0,
           "position.entry_time": "2025-01-01T00:00:00+00:00",
           "position.stop_level": 47_000.0, "position.units": 0.2},
    )
    from sardbot.paper.webhook import cmd_status
    out = cmd_status()
    assert "LONG" in out
    assert "$50,000.00" in out
    assert "$47,000.00" in out


def test_equity_basic(storage_dir):
    _seed_state(storage_dir,
                **{"equity.current": 11_000.0, "equity.high_watermark": 11_500.0})
    from sardbot.paper.webhook import cmd_equity
    out = cmd_equity()
    assert "$11,000.00" in out
    assert "+10" in out  # +10% pnl


def test_trades_empty(storage_dir):
    _seed_state(storage_dir)
    from sardbot.paper.webhook import cmd_trades
    out = cmd_trades()
    assert "nenhum" in out


def test_trades_with_history(storage_dir):
    _seed_state(storage_dir)
    storage = LocalStorage(base_dir=storage_dir)
    storage.append_parquet(TRADES_PATH, pd.DataFrame([
        {"time": "2025-01-15T00:00:00+00:00", "type": "entry", "price": 50_000.0, "pnl": None},
        {"time": "2025-02-10T00:00:00+00:00", "type": "exit_signal", "price": 55_000.0, "pnl": 950.0},
    ]))
    from sardbot.paper.webhook import cmd_trades
    out = cmd_trades()
    assert "entry" in out
    assert "$50,000.00" in out
    assert "$55,000.00" in out


def test_help_lists_commands(storage_dir):
    from sardbot.paper.webhook import cmd_help
    out = cmd_help()
    for cmd in ["/status", "/equity", "/trades", "/why"]:
        assert cmd in out


def test_unknown_command(storage_dir):
    from sardbot.paper.webhook import cmd_unknown
    out = cmd_unknown()
    assert "/help" in out


def test_telegram_endpoint_rejects_bad_secret(storage_dir, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "correct")
    from sardbot.paper.webhook import app
    client = app.test_client()
    resp = client.post("/telegram", json={}, headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"})
    assert resp.status_code == 401


def test_telegram_endpoint_ignores_unauthorized_chat(storage_dir, monkeypatch):
    monkeypatch.setenv("WEBHOOK_SECRET", "correct")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456789")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    from sardbot.paper.webhook import app
    client = app.test_client()
    resp = client.post("/telegram",
                       json={"message": {"chat": {"id": 99999}, "text": "/status"}},
                       headers={"X-Telegram-Bot-Api-Secret-Token": "correct"})
    # Returns 200 (we acknowledge to Telegram) but does nothing.
    assert resp.status_code == 200


def test_health_endpoint(storage_dir):
    from sardbot.paper.webhook import app
    client = app.test_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"
