"""Уведомления администратору в Telegram: об ошибках, перезапусках и обновлениях."""
from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot

log = logging.getLogger(__name__)

COOLDOWN_SECONDS = 10 * 60  # одинаковое уведомление — не чаще раза в 10 минут
SEND_TIMEOUT = 20           # уведомление не должно подвешивать бота при проблемах с сетью

# Временные сетевые сбои, которые aiogram сам переживает (повторяет запрос) — не беспокоим
TRANSIENT = ("Failed to fetch updates",)


class Notifier:
    def __init__(self, bot: Bot, admin_id: int, cooldown: int = COOLDOWN_SECONDS) -> None:
        self.bot = bot
        self.admin_id = admin_id
        self.cooldown = cooldown
        self._last_sent: dict[str, float] = {}

    async def send(self, text: str, dedupe_key: str | None = None) -> None:
        if dedupe_key:
            now = time.monotonic()
            last = self._last_sent.get(dedupe_key)
            if last is not None and now - last < self.cooldown:
                return
            self._last_sent[dedupe_key] = now
        try:
            await asyncio.wait_for(self.bot.send_message(self.admin_id, text[:4000]), SEND_TIMEOUT)
        except Exception as e:  # уведомление не должно ронять бота
            log.warning("Не удалось отправить уведомление: %s %s", type(e).__name__, e)


class TelegramLogHandler(logging.Handler):
    """Пересылает в Telegram все записи лога уровня ERROR и выше."""

    def __init__(self, notifier: Notifier, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__(level=logging.ERROR)
        self.notifier = notifier
        self.loop = loop

    def emit(self, record: logging.LogRecord) -> None:
        if record.name.startswith(__name__) or self.loop.is_closed():
            return
        if isinstance(record.msg, str) and record.msg.startswith(TRANSIENT):
            return
        try:
            text = f"⚠️ Ошибка в боте\n{record.name}: {record.getMessage()}"
            exc_type = ""
            if record.exc_info and record.exc_info[1]:
                exc_type = record.exc_info[0].__name__
                text += f"\n\n{exc_type}: {str(record.exc_info[1])[:1500]}"
            # Ключ — шаблон сообщения + тип ошибки: одна и та же проблема на разных ссылках не спамит
            key = f"{record.name}|{record.msg}|{exc_type}"
            self.loop.call_soon_threadsafe(
                lambda: self.loop.create_task(self.notifier.send(text, key)))
        except Exception:
            self.handleError(record)
