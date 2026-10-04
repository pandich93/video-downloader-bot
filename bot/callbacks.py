"""Обработка нажатий на инлайн-кнопки."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.cache import VideoCache
from bot.config import Settings
from bot.handlers import run_original
from bot.keyboards import CHOOSE_TEXT, EDIT_STUB_TEXT, VideoAction, choose_kb, edit_stub_kb
from bot.link_store import links

router = Router()
EXPIRED = "⌛ Ссылка устарела, пришлите её заново."


@router.callback_query(VideoAction.filter(F.action == "original"))
async def on_original(callback: CallbackQuery, callback_data: VideoAction,
                      settings: Settings, cache: VideoCache) -> None:
    await callback.answer()
    url = links.pop(callback_data.key)  # pop — защита от двойного нажатия
    if not url:
        await callback.message.edit_text(EXPIRED)
        return
    status = callback.message
    # Видео отправляем ответом на исходное сообщение со ссылкой
    reply_to = status.reply_to_message or status
    await run_original(reply_to, status, url, settings, cache)


@router.callback_query(VideoAction.filter(F.action == "edit"))
async def on_edit(callback: CallbackQuery, callback_data: VideoAction) -> None:
    await callback.answer()
    if not links.get(callback_data.key):
        await callback.message.edit_text(EXPIRED)
        return
    await callback.message.edit_text(EDIT_STUB_TEXT, reply_markup=edit_stub_kb(callback_data.key))


@router.callback_query(VideoAction.filter(F.action == "back"))
async def on_back(callback: CallbackQuery, callback_data: VideoAction) -> None:
    await callback.answer()
    if not links.get(callback_data.key):
        await callback.message.edit_text(EXPIRED)
        return
    await callback.message.edit_text(CHOOSE_TEXT, reply_markup=choose_kb(callback_data.key))
