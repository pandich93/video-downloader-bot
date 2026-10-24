"""Большие файлы через MTProto (Telethon) — в обход лимитов Bot API.

Bot API: бот скачивает из Telegram файлы до 20 МБ и отправляет до 50 МБ.
MTProto с тем же токеном бота: до 2 ГБ в обе стороны. Всё остальное по-прежнему
делает aiogram, Telethon подключается только для больших файлов.

Нужны API_ID и API_HASH (my.telegram.org → API development tools).
Без них модуль выключен, и бот работает с обычными лимитами.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Awaitable, Callable

log = logging.getLogger(__name__)

MAX_BYTES = 2000 * 1024 * 1024
ProgressCb = Callable[[int], Awaitable[None]]

_client = None  # telethon.TelegramClient, если модуль включён


def enabled() -> bool:
    return _client is not None


async def start(api_id: int, api_hash: str, bot_token: str, session: Path) -> None:
    global _client
    from telethon import TelegramClient  # импорт здесь: без ключей telethon не нужен

    logging.getLogger("telethon").setLevel(logging.WARNING)
    client = TelegramClient(str(session), api_id, api_hash)
    await client.start(bot_token=bot_token)
    _client = client
    try:
        import cryptg  # noqa: F401 — ускоряет шифрование в разы
    except ImportError:
        log.warning("cryptg не установлен — большие файлы будут передаваться медленнее")


async def stop() -> None:
    global _client
    if _client:
        await _client.disconnect()
        _client = None


def _progress(cb: ProgressCb | None):
    if not cb:
        return None
    last = [0.0]

    async def inner(current: int, total: int) -> None:
        now = time.monotonic()
        if total and now - last[0] >= 4:  # не чаще раза в 4 секунды
            last[0] = now
            await cb(int(current * 100 / total))
    return inner


async def _message(message_id: int):
    # entity=None: бот получает сообщения из личных чатов по id без поиска собеседника
    msg = await _client.get_messages(None, ids=message_id)
    if not msg:
        raise RuntimeError(f"сообщение {message_id} не найдено через MTProto")
    return msg


async def download(message_id: int, dest: Path, progress: ProgressCb | None = None) -> Path:
    """Скачивает медиа из сообщения пользователя (в личном чате с ботом)."""
    msg = await _message(message_id)
    if not msg.media:
        raise RuntimeError("в сообщении нет файла")
    result = await _client.download_media(msg, file=str(dest), progress_callback=_progress(progress))
    return Path(result)


async def send_video(chat_id: int, reply_to: int | None, path: Path, *, caption: str,
                     duration: float, width: int, height: int, thumb: Path | None = None,
                     progress: ProgressCb | None = None) -> None:
    from telethon.tl.types import DocumentAttributeVideo

    try:
        peer = await _client.get_input_entity(chat_id)
    except ValueError:
        # Собеседник ещё не встречался этой MTProto-сессии — узнаём его из сообщения
        peer = await (await _message(reply_to)).get_input_chat()
    await _client.send_file(
        peer, str(path), caption=caption, reply_to=reply_to, thumb=str(thumb) if thumb else None,
        supports_streaming=True, force_document=False,
        attributes=[DocumentAttributeVideo(duration=int(duration), w=width, h=height,
                                           supports_streaming=True)],
        progress_callback=_progress(progress),
    )
