"""Доступ к боту: открытый режим или белый список, блокировки, учёт пользователей."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.config import Settings
from bot.notify import Notifier
from bot.users import Users

log = logging.getLogger(__name__)


class AccessMiddleware(BaseMiddleware):
    """Подключается и к сообщениям, и к нажатиям кнопок."""

    def __init__(self, settings: Settings, users: Users, notifier: Notifier) -> None:
        self.settings = settings
        self.users = users
        self.notifier = notifier

    def _allowed(self, uid: int) -> bool:
        if self.users.is_admin(uid):
            return True
        if self.users.is_blocked(uid):
            return False
        return self.settings.is_public or uid in self.settings.allowed_user_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if not user or user.is_bot:
            return None

        if self._allowed(user.id):
            name = " ".join(x for x in (user.first_name, user.last_name) if x)
            if self.users.touch(user.id, user.username, name):
                log.info("Новый пользователь: %s (@%s) %s", user.id, user.username or "-", name)
                if self.settings.notify_new_users and not self.users.is_admin(user.id):
                    await self.notifier.send(
                        f"👤 Новый пользователь: {name or 'без имени'}"
                        f"{' @' + user.username if user.username else ''} (id {user.id})")
            return await handler(event, data)

        log.warning("Отказ в доступе: user_id=%s (@%s)", user.id, user.username or "-")
        blocked = self.users.is_blocked(user.id)
        if isinstance(event, CallbackQuery):
            await event.answer("⛔ Нет доступа", show_alert=True)
        elif isinstance(event, Message):
            if blocked:
                await event.answer("⛔ Доступ к боту ограничен.")
            else:
                await event.answer(
                    f"⛔ Нет доступа.\nВаш ID: <code>{user.id}</code>\n"
                    "Попросите владельца бота добавить его в ALLOWED_USER_IDS.",
                    parse_mode="HTML",
                )
        return None
