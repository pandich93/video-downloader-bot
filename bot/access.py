"""Проверка доступа: чужим пользователям бот сообщает их ID и ничего не выполняет."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

log = logging.getLogger(__name__)


class AccessMiddleware(BaseMiddleware):
    """Подключается и к сообщениям, и к нажатиям кнопок."""

    def __init__(self, allowed_ids: frozenset[int]) -> None:
        self.allowed_ids = allowed_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user and user.id in self.allowed_ids:
            return await handler(event, data)

        uid = user.id if user else None
        log.warning("Отказ в доступе: user_id=%s (@%s)", uid, user.username if user else "-")
        if isinstance(event, CallbackQuery):
            await event.answer("⛔ Нет доступа", show_alert=True)
        elif isinstance(event, Message):
            await event.answer(
                f"⛔ Нет доступа.\nВаш ID: <code>{uid}</code>\n"
                "Добавьте его в ALLOWED_USER_IDS в .env и перезапустите бота.",
                parse_mode="HTML",
            )
