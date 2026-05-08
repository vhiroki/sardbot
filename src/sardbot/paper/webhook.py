"""Telegram webhook — handles `/status`, `/equity`, `/why`, `/trades` commands.

Architecture: this is a Cloud Run Service (long-lived HTTP) running alongside
the Cloud Run Job that does paper trading. They share the same image but use
different entrypoints. The Service is publicly accessible (Telegram needs to
reach it) but verified two ways:

1. `X-Telegram-Bot-Api-Secret-Token` header — set when we register the webhook
   via setWebhook, Telegram echoes it on every request. Mismatched header = 401.
2. `chat.id` from the message — must match our authorized chat. Other senders
   silently ignored.

Both checks together mean: even if someone discovers the URL, they can't make
the bot reply to them.

Commands are read-only (state, equity, trades). Administrative commands (pause,
reset) deliberately stay on gcloud CLI — if the bot token leaks, the worst an
attacker can do is read your state and find out what you bought.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from flask import Flask, abort, request

from sardbot.data.loader import CCXTLoader
from sardbot.indicators.atr import atr as atr_indicator
from sardbot.paper.notifier import TelegramNotifier
from sardbot.paper.state import State
from sardbot.paper.storage import make_storage_from_env
from sardbot.paper.trader import EQUITY_PATH, STATE_PATH, TRADES_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)


@app.route("/", methods=["GET"])
def health() -> dict:
    return {"status": "ok", "service": "sardbot-webhook"}


@app.route("/telegram", methods=["POST"])
def telegram_webhook() -> dict:
    expected_secret = os.environ.get("WEBHOOK_SECRET")
    if expected_secret:
        actual = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if actual != expected_secret:
            log.warning("Webhook called with bad/missing secret token")
            abort(401)

    update = request.get_json(silent=True) or {}
    msg = update.get("message") or update.get("edited_message") or {}
    chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip()

    authorized_chat = os.environ.get("TELEGRAM_CHAT_ID")
    if not authorized_chat or str(chat_id) != str(authorized_chat):
        log.warning("Ignoring message from unauthorized chat: %s", chat_id)
        return {"ok": True}

    if not text.startswith("/"):
        return {"ok": True}

    cmd = text.split()[0].lower().split("@")[0]  # strip @BotName suffix
    handlers = {
        "/status": cmd_status,
        "/equity": cmd_equity,
        "/why": cmd_why,
        "/trades": cmd_trades,
        "/help": cmd_help,
        "/start": cmd_help,
    }
    handler = handlers.get(cmd, cmd_unknown)
    try:
        reply = handler()
    except Exception as exc:  # noqa: BLE001 — never crash the webhook
        log.exception("Command %s failed", cmd)
        reply = f"❌ erro: {exc}"

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if token:
        TelegramNotifier(bot_token=token, chat_id=str(chat_id)).send(reply)
    return {"ok": True}


# -----------------------------------------------------------------------------
# Command handlers (pure functions of state/storage — easy to unit test)
# -----------------------------------------------------------------------------

def cmd_help() -> str:
    return (
        "*sardbot — comandos*\n"
        "`/status` — posição atual, equity, drawdown\n"
        "`/equity` — equity vs initial, high water, drawdown\n"
        "`/trades` — últimos 5 trades\n"
        "`/why` — explica por que estou flat/long agora\n"
        "`/help` — esta mensagem"
    )


def cmd_unknown() -> str:
    return "comando não reconhecido. /help pra lista"


def _load_state() -> State | None:
    storage = make_storage_from_env()
    raw = storage.read_text(STATE_PATH)
    return State.from_json(raw) if raw else None


def cmd_status() -> str:
    state = _load_state()
    if not state:
        return "❌ sem estado ainda. bot não rodou nenhuma vez."
    pos_label = "🟢 LONG" if state.position.is_long else "⚪️ flat"
    lines = [
        f"*Status* — {state.symbol}",
        f"posição: {pos_label}",
        f"equity: ${state.equity.current:,.2f}",
        f"drawdown: {state.drawdown():.2%}",
        f"último bar: `{state.last_processed_bar}`",
    ]
    if state.position.is_long:
        lines.append(f"entrada: ${state.position.entry_price:,.2f} em `{state.position.entry_time}`")
        if state.position.stop_level:
            lines.append(f"stop: ${state.position.stop_level:,.2f}")
    if state.stopped_out_cooldown:
        lines.append("⏸ em cooldown pós-stop-out")
    return "\n".join(lines)


def cmd_equity() -> str:
    state = _load_state()
    if not state:
        return "❌ sem estado ainda."
    eq = state.equity
    pnl = eq.current - eq.initial_capital
    pnl_pct = (eq.current / eq.initial_capital - 1) * 100 if eq.initial_capital else 0
    lines = [
        f"*Equity* — {state.symbol}",
        f"atual:    ${eq.current:,.2f}",
        f"inicial:  ${eq.initial_capital:,.2f}",
        f"PnL:      ${pnl:+,.2f} ({pnl_pct:+.2f}%)",
        f"high water: ${eq.high_watermark:,.2f}",
        f"drawdown:   {state.drawdown():.2%}",
    ]
    storage = make_storage_from_env()
    eq_df = storage.read_parquet(EQUITY_PATH)
    if eq_df is not None and len(eq_df) > 1:
        last7 = eq_df.tail(7)
        if len(last7) > 1:
            change = (last7["equity"].iloc[-1] / last7["equity"].iloc[0] - 1) * 100
            lines.append(f"últimos {len(last7)} runs: {change:+.2f}%")
    return "\n".join(lines)


def cmd_trades() -> str:
    storage = make_storage_from_env()
    df = storage.read_parquet(TRADES_PATH)
    if df is None or df.empty:
        return "📊 nenhum trade ainda."
    last = df.tail(5)
    lines = [f"*Últimos {len(last)} trades* (de {len(df)} total)"]
    for _, row in last.iterrows():
        time_str = str(row.get("time", ""))[:10]
        type_str = str(row.get("type", "?"))
        emoji = {"entry": "🟢", "exit_signal": "🔴", "exit_stop": "🛑"}.get(type_str, "•")
        line = f"{emoji} `{time_str}` {type_str} @ ${row['price']:,.2f}"
        pnl = row.get("pnl")
        if pnl is not None and pd.notna(pnl):
            line += f"  pnl=${pnl:+,.0f}"
        lines.append(line)
    return "\n".join(lines)


def cmd_why() -> str:
    state = _load_state()
    if not state:
        return "❌ sem estado ainda."

    loader = CCXTLoader()
    since = datetime(2018, 1, 1, tzinfo=timezone.utc)
    df = loader.fetch_ohlcv(state.symbol, "1d", since=since,
                            cache_dir=Path("/tmp/sardbot_cache"))

    fast = state.params.get("entry", 20)
    exit_lookback = state.params.get("exit", 10)
    trend_window = state.params.get("trend_filter") or 200
    atr_window = state.params.get("atr_window", 14)

    upper_band = float(df["high"].rolling(fast).max().shift(1).iloc[-1])
    lower_band = float(df["low"].rolling(exit_lookback).min().shift(1).iloc[-1])
    sma_trend = float(df["close"].rolling(trend_window).mean().shift(1).iloc[-1])
    atr_val = float(atr_indicator(df, period=atr_window).iloc[-1])
    close = float(df["close"].iloc[-1])

    lines = [
        f"*Why?* {state.symbol} @ ${close:,.2f}",
        f"posição: {'🟢 LONG' if state.position.is_long else '⚪️ flat'}",
        "",
        "*Indicadores no fechamento atual:*",
        f"• Donchian upper ({fast}d): ${upper_band:,.2f}",
        f"• Donchian lower ({exit_lookback}d): ${lower_band:,.2f}",
        f"• SMA{trend_window}: ${sma_trend:,.2f}",
        f"• ATR({atr_window}): ${atr_val:,.2f}",
        "",
    ]

    if state.position.is_long:
        lines.append("*Por que LONG:*")
        lines.append(f"• entrei em ${state.position.entry_price:,.2f} quando close cruzou acima da Donchian {fast}d")
        lines.append(f"• filtro SMA{trend_window} confirmou tendência")
        lines.append("*Vou sair se:*")
        lines.append(f"• close < ${lower_band:,.2f} (Donchian {exit_lookback}d)")
        if state.position.stop_level:
            lines.append(f"• low <= ${state.position.stop_level:,.2f} (stop ATR)")
    else:
        lines.append("*Por que flat:*")
        if state.stopped_out_cooldown:
            lines.append("• ⏸ em cooldown pós-stop-out")
            lines.append("  → preciso ver sinal voltar a 0 antes de re-entrar")
        elif close <= sma_trend:
            gap_pct = (sma_trend / close - 1) * 100
            lines.append(f"• filtro SMA{trend_window} BLOQUEIA: close está {gap_pct:.2f}% abaixo")
            lines.append("  → não entro mesmo se Donchian breakout acontecer")
        elif close <= upper_band:
            gap_pct = (upper_band / close - 1) * 100
            lines.append(f"• sem breakout: close está {gap_pct:.2f}% abaixo da Donchian upper")
            lines.append(f"  → preciso fechar acima de ${upper_band:,.2f} pra entrar")
        else:
            lines.append("• condições parecem favoráveis mas posição não foi aberta")
            lines.append("  → próximo run deve abrir; investigar logs se persistir")

    return "\n".join(lines)
