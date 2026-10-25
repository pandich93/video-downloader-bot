"""Исходник для обработки: файл из Telegram, кэш уже отправленных видео, TikTok или yt-dlp."""
from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from bot import mtproto
from bot.cache import VideoCache
from bot.config import Settings
from bot.downloader import DownloadFailed, VideoFile, download_video
from bot.handlers import is_tiktok
from bot.tiktok import URL_UPLOAD_LIMIT, TikTokInfo, download_tiktok_file, get_tiktok_info

log = logging.getLogger(__name__)

# Исходник может быть больше лимитов Telegram: результат всё равно пережимается
EDIT_SOURCE_MAX_BYTES = 500 * 1024 * 1024
EDIT_SOURCE_HEIGHTS = (1080, 720, 480)          # для обработки качаем до 1080p
TELEGRAM_DOWNLOAD_LIMIT = 20 * 1024 * 1024      # больше Bot API скачать не даёт


@dataclass(frozen=True)
class Source:
    url: str | None = None
    file_id: str | None = None
    file_size: int = 0
    chat_id: int = 0
    message_id: int | None = None   # сообщение пользователя (ссылка или видео)
    title: str = ""


def _workdir(base: Path) -> Path:
    return Path(tempfile.mkdtemp(prefix="ed_", dir=base))


async def from_telegram(bot: Bot, file_id: str, base_dir: Path, title: str = "",
                        description: str = "") -> VideoFile:
    workdir = _workdir(base_dir)
    try:
        file = await bot.get_file(file_id)
        if file.file_size and file.file_size > TELEGRAM_DOWNLOAD_LIMIT:
            raise DownloadFailed("📦 Файл больше 20 МБ — через Bot API его не скачать.")
        dest = workdir / "source.mp4"
        await bot.download_file(file.file_path, destination=dest, timeout=180)
        return VideoFile(path=dest, title=title, duration=None, width=None, height=None,
                         workdir=workdir, description=description)
    except BaseException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise


async def _from_mtproto(src: Source, base_dir: Path, progress) -> VideoFile:
    workdir = _workdir(base_dir)
    try:
        path = await mtproto.download(src.message_id, workdir / "source.mp4", progress)
        return VideoFile(path=path, title=src.title, duration=None, width=None, height=None,
                         workdir=workdir)
    except BaseException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise


async def _try_cached(bot: Bot, cache: VideoCache, key: str, base_dir: Path) -> VideoFile | None:
    """Видео уже отправляли — берём из Telegram (до 20 МБ). Так обходятся блокировки сайтов."""
    hit = cache.get(key)
    if not hit:
        return None
    try:
        return await from_telegram(bot, hit.file_id, base_dir, hit.title, hit.description)
    except (TelegramAPIError, DownloadFailed) as e:
        log.info("Исходник из кэша не получен (%s), качаем заново", e)
        return None


async def _tiktok_via_telegram(bot: Bot, src: Source, info: TikTokInfo, cache: VideoCache,
                               base_dir: Path) -> VideoFile | None:
    """CDN TikTok заблокирован, а серверы Telegram — нет: отдаём им ссылку, забираем файл.

    Служебное сообщение с видео сразу удаляется, file_id запоминается в кэше.
    """
    if not src.chat_id:
        return None
    for link in info.links(URL_UPLOAD_LIMIT):
        try:
            sent = await bot.send_video(src.chat_id, link, disable_notification=True)
        except TelegramAPIError as e:
            log.info("Telegram не принял ссылку TikTok (%s)", e)
            continue
        try:
            await sent.delete()
        except TelegramAPIError:
            pass
        if not sent.video:
            continue
        fid = sent.video.file_id
        for key in {cache.key(src.url), cache.key_for(f"tt:{info.id}") if info.id else None} - {None}:
            cache.set(key, fid, info.title)
        try:
            return await from_telegram(bot, fid, base_dir, info.title)
        except (TelegramAPIError, DownloadFailed) as e:
            log.info("Не удалось забрать TikTok из Telegram: %s", e)
    return None


async def fetch(bot: Bot, src: Source, settings: Settings, cache: VideoCache,
                progress=None) -> VideoFile:
    base = settings.download_dir

    # 1. Видео прислали файлом
    if src.file_id:
        if src.file_size > TELEGRAM_DOWNLOAD_LIMIT:
            if not mtproto.enabled() or not src.message_id:
                raise DownloadFailed("📦 Файл больше 20 МБ. Чтобы обрабатывать большие файлы, "
                                     "впишите API_ID и API_HASH в .env (см. README).")
            try:
                return await _from_mtproto(src, base, progress)
            except Exception as e:
                log.warning("MTProto: не удалось скачать файл: %s", e)
                raise DownloadFailed("😕 Не удалось скачать большой файл. Пришлите его ещё раз.") from e
        try:
            return await from_telegram(bot, src.file_id, base, src.title)
        except TelegramAPIError as e:
            log.warning("Не удалось скачать файл из Telegram: %s", e)
            raise DownloadFailed("😕 Telegram не отдал файл. Пришлите его ещё раз или ссылкой.") from e

    # 2. Ссылка, которую уже скачивали, — берём из Telegram
    url = src.url
    video = await _try_cached(bot, cache, cache.key(url), base)
    if video:
        return video

    # 3. TikTok: кэш по id → через серверы Telegram → напрямую с CDN
    tiktok_error: DownloadFailed | None = None
    if is_tiktok(url):
        try:
            info = await get_tiktok_info(url)
        except DownloadFailed:
            raise  # видео удалено, приватное или это фото-карусель — дальше пробовать бессмысленно
        except Exception as e:
            log.warning("tikwm недоступен (%s), пробуем yt-dlp", e)
            info = None
        if info:
            if info.id:
                video = await _try_cached(bot, cache, cache.key_for(f"tt:{info.id}"), base)
                if video:
                    return video
            video = await _tiktok_via_telegram(bot, src, info, cache, base)
            if video:
                return video
            try:
                return await download_tiktok_file(info, max_bytes=EDIT_SOURCE_MAX_BYTES,
                                                  base_dir=base, proxy=settings.proxy)
            except DownloadFailed as e:
                tiktok_error = e

    # 4. yt-dlp (YouTube, Instagram и запасной путь для TikTok)
    try:
        return await download_video(url, max_bytes=EDIT_SOURCE_MAX_BYTES, base_dir=base,
                                    cookies=settings.cookies_file, proxy=settings.proxy,
                                    heights=EDIT_SOURCE_HEIGHTS)
    except DownloadFailed:
        if tiktok_error:
            raise tiktok_error from None
        raise
