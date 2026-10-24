"""Модуль обработки видео (кнопка «✂️ Редактировать»)."""
from bot.editor.router import open_from_link
from bot.editor.router import router as editor_router

__all__ = ["editor_router", "open_from_link"]
