"""Notification channels.

NullNotifier   — no-op, for tests / local dev without Telegram.
TelegramNotifier — POST to the Bot API.

We don't take a hard dependency on python-telegram-bot or similar — a single
HTTP call is all we need, requests is already a transitive dep.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod

import requests

log = logging.getLogger(__name__)


class Notifier(ABC):
    @abstractmethod
    def send(self, message: str) -> bool: ...


class NullNotifier(Notifier):
    def send(self, message: str) -> bool:
        log.info("[NullNotifier] %s", message)
        return True


class TelegramNotifier(Notifier):
    def __init__(self, bot_token: str, chat_id: str):
        if not bot_token or not chat_id:
            raise ValueError("TelegramNotifier requires bot_token and chat_id")
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    def send(self, message: str) -> bool:
        try:
            resp = requests.post(
                self.url,
                json={"chat_id": self.chat_id, "text": message, "parse_mode": "Markdown"},
                timeout=10,
            )
            resp.raise_for_status()
            return True
        except Exception as e:  # noqa: BLE001 — we never want notification failure to crash the bot
            log.error("Telegram send failed: %s", e)
            return False


def make_notifier_from_env() -> Notifier:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat = os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat:
        return TelegramNotifier(bot_token=token, chat_id=chat)
    return NullNotifier()
