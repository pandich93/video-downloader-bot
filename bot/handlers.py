"""Обработчики сообщений бота."""
from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urlparse

from aiogram import Router, F
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import FSInputFile, Message

from bot.cache import VideoCache
from bot.config import Settings
from bot.downloader import DownloadFailed, VideoFile, download_video
from bot.keyboards import CHOOSE_TEXT, choose_kb
from bot.link_store import links
from bot.notify import Notifier
from bot.tiktok import URL_UPLOAD_LIMIT, download_tiktok_file, get_tiktok_info

log = logging.getLogger(__name__)
router = Router()

URL_RE = re.compile(r"https?://\S+")
SUPPORTED_DOMAINS = ("youtube.com", "youtu.be", "tiktok.com", "instagram.com")

# Не больше 2 загрузок одновременно, остальные ждут в очереди
_semaphore = asyncio.Semaphore(2)
_active_jobs = 0  # сколько ссылок сейчас в работе (для безопасного перезапуска)


def is_busy() -> bool:
    return _active_jobs > 0


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def is_supported(url: str) -> bool:
    host = _host(url)
    return any(host == d or host.endswith("." + d) for d in SUPPORTED_DOMAINS)


def is_tiktok(url: str) -> bool:
    host = _host(url)
    return host == "tiktok.com" or host.endswith(".tiktok.com")


def _file_id(sent: Message | None) -> str | None:
    return sent.video.file_id if sent and sent.video else None


async def _send_file(message: Message, video: VideoFile) -> Message:
    await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
    return await message.reply_video(
        FSInputFile(video.path),
        caption=video.title[:1000] or None,
        duration=video.duration,
        width=video.width,
        height=video.height,
        supports_streaming=True,
    )


async def _handle_tiktok(message: Message, status: Message, url: str,
                         settings: Settings, cache: VideoCache) -> bool:
    """True — видео отправлено. False — tikwm недоступен, пусть пробует yt-dlp."""
    try:
        info = await get_tiktok_info(url)
    except DownloadFailed:
        raise
    except Exception as e:
        log.warning("tikwm недоступен (%s), пробуем yt-dlp", e)
        return False

    # Короткая ссылка и полная ведут на одно видео — проверяем кэш по его id
    id_key = cache.key_for(f"tt:{info.id}") if info.id else None
    if id_key and await _send_cached(message, cache, id_key):
        cache_link(cache, url, id_key)
        return True

    def remember(sent: Message | None) -> None:
        fid = _file_id(sent)
        if fid:
            for k in {cache.key(url), id_key} - {None}:
                cache.set(k, fid, info.title)

    # 1) Отдаём ссылку Telegram — его серверы скачают видео сами, блокировка им не мешает
    await status.edit_text("📤 Отправляю…")
    for link in info.links(URL_UPLOAD_LIMIT):
        try:
            sent = await message.reply_video(link, caption=info.title[:1000] or None,
                                             duration=info.duration, supports_streaming=True)
            remember(sent)
            return True
        except TelegramAPIError as e:
            log.info("Telegram не принял ссылку (%s)", e)

    # 2) Не вышло (например, видео > 20 МБ) — качаем сами
    await status.edit_text("⏳ Скачиваю…")
    video = await download_tiktok_file(info, max_bytes=settings.max_file_bytes,
                                       base_dir=settings.download_dir, proxy=settings.proxy)
    try:
        await status.edit_text("📤 Отправляю…")
        remember(await _send_file(message, video))
    finally:
        video.cleanup()
    return True


def cache_link(cache: VideoCache, url: str, id_key: str) -> None:
    """Запоминаем и эту форму ссылки — в следующий раз хватит одного запроса к кэшу."""
    hit = cache.get(id_key)
    if hit:
        cache.set(cache.key(url), hit[0], hit[1])


async def _send_cached(message: Message, cache: VideoCache, key: str) -> bool:
    """Отправить видео из кэша. False — в кэше нет или file_id устарел."""
    hit = cache.get(key)
    if not hit:
        return False
    file_id, title = hit
    try:
        await message.reply_video(file_id, caption=title[:1000] or None, supports_streaming=True)
        log.info("Отправлено из кэша: %s", key)
        return True
    except TelegramAPIError as e:
        log.info("file_id из кэша не подошёл (%s), качаем заново", e)
        cache.delete(key)
        return False


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(
        "Привет! Пришли ссылку на видео из YouTube, TikTok или Instagram — "
        "я предложу скачать оригинал или обработать его."
    )


@router.message(Command("restart"))
async def cmd_restart(message: Message, settings: Settings, notifier: Notifier) -> None:
    """Перезапуск бота из Telegram — только для администратора."""
    if message.from_user.id != settings.admin_id:
        await message.reply("⛔ Команда только для администратора.")
        return
    from bot.watcher import graceful_restart  # локальный импорт: watcher зависит от updater
    await message.reply("🔄 Перезапускаюсь…" + (" Дождусь окончания загрузок." if is_busy() else ""))
    await graceful_restart(notifier, is_busy, "команда /restart", notify=False)


@router.message(F.text)
async def on_link(message: Message) -> None:
    match = URL_RE.search(message.text)
    if not match:
        await message.reply("Пришли ссылку на видео 🙂")
        return

    url = match.group(0)
    if not is_supported(url):
        await message.reply("⚠️ Поддерживаются только YouTube, TikTok и Instagram.")
        return

    # Сначала спрашиваем, что делать: оригинал или редактирование
    key = links.put(url)
    await message.reply(CHOOSE_TEXT, reply_markup=choose_kb(key))


async def run_original(reply_to: Message, status: Message, url: str,
                       settings: Settings, cache: VideoCache) -> None:
    """Скачивает и отправляет оригинал. status — сообщение бота, в котором показываем прогресс."""
    global _active_jobs
    _active_jobs += 1
    try:
        # Уже отправляли это видео — пересылаем мгновенно, без скачивания
        key = cache.key(url)
        if await _send_cached(reply_to, cache, key):
            await status.delete()
            return

        queued = _semaphore.locked()
        # edit_text без reply_markup заодно убирает кнопки
        await status.edit_text("🕒 В очереди…" if queued else "⏳ Скачиваю…")
        async with _semaphore:
            if queued:  # повторный edit того же текста Telegram отклоняет
                await status.edit_text("⏳ Скачиваю…")

            if is_tiktok(url) and await _handle_tiktok(reply_to, status, url, settings, cache):
                await status.delete()
                return

            video = await download_video(
                url,
                max_bytes=settings.max_file_bytes,
                base_dir=settings.download_dir,
                cookies=settings.cookies_file,
                proxy=settings.proxy,
            )
        try:
            await status.edit_text("📤 Отправляю…")
            sent = await _send_file(reply_to, video)
            if _file_id(sent):
                cache.set(key, _file_id(sent), video.title)
            await status.delete()
        finally:
            video.cleanup()
    except DownloadFailed as e:
        await status.edit_text(str(e))
    except Exception:
        log.exception("Ошибка при обработке %s", url)
        await status.edit_text("💥 Что-то пошло не так. Администратор получил уведомление.")
    finally:
        _active_jobs -= 1
