"""Инлайн-кнопки и формат callback_data."""
from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup

CHOOSE_TEXT = "Что делаем с видео?"
EDIT_STUB_TEXT = "✂️ Скоро: обработка видео.\nПока можно скачать оригинал."


class VideoAction(CallbackData, prefix="v"):
    action: str  # original | edit | back
    key: str     # ключ ссылки в LinkStore


def choose_kb(key: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="📥 Оригинал", callback_data=VideoAction(action="original", key=key))
    kb.button(text="✂️ Редактировать", callback_data=VideoAction(action="edit", key=key))
    kb.adjust(2)
    return kb.as_markup()


def edit_stub_kb(key: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="← Назад", callback_data=VideoAction(action="back", key=key))
    return kb.as_markup()
