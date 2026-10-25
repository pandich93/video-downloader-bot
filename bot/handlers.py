"""Обработчики сообщений бота."""
from __future__ import annotations

import contextlib
import logging
import re
from urllib.parse import urlparse

from aiogram import Bot, Router, F
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import FSInputFile, LinkPreviewOptions, Message, ReplyParameters

from bot.cache import VideoCache
from bot.captions import build_caption, original_text
from bot.config import Settings
from bot.downloader import DownloadFailed, VideoFile, download_video
from bot.keyboards import CHOOSE_TEXT, choose_kb
from bot.link_store import links
from bot.notify import Notifier
from bot.slots import SlotQueue
from bot.tiktok import URL_UPLOAD_LIMIT, download_tiktok_file, get_tiktok_info
from bot.users import LimitError, Users

log = logging.getLogger(__name__)
router = Router()

URL_RE = re.compile(r"https?://\S+")
SUPPORTED_DOMAINS = ("youtube.com", "youtu.be", "tiktok.com", "instagram.com")

# Не больше 2 загрузок одновременно, остальные ждут в очереди и видят свой номер.
# Эту же очередь использует модуль обработки (bot/editor).
download_queue = SlotQueue(2)
_active_jobs = 0  # сколько задач сейчас в работе (для безопасного перезапуска)


def is_busy() -> bool:
    return _active_jobs > 0


def queue_text(pos: int, what: str = "скачивание") -> str:
    return f"🕒 Очередь на {what}: вы {pos}-й. Сообщу, когда начну."


@contextlib.asynccontextmanager
async def job_slot():
    """Учитывает задачу в is_busy(): перезапуск бота дождётся её окончания."""
    global _active_jobs
    _active_jobs += 1
    try:
        yield
    finally:
        _active_jobs -= 1


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


async def send_extra(bot: Bot, chat_id: int, video_message_id: int | None, parts: list[str]) -> None:
    """Полный текст оригинала, не влезший в подпись, — ответом на видео."""
    reply = (ReplyParameters(message_id=video_message_id, allow_sending_without_reply=True)
             if video_message_id else None)
    for part in parts:
        try:
            await bot.send_message(chat_id, part, reply_parameters=reply,
                                   link_preview_options=LinkPreviewOptions(is_disabled=True))
        except TelegramAPIError as e:
            log.info("Не удалось отправить описание: %s", e)
            return


async def _reply_video(message: Message, video, text: str, **kwargs) -> Message:
    """Видео с названием и описанием оригинала в подписи (без parse_mode — текст как есть)."""
    caption, extra = build_caption(text)
    sent = await message.reply_video(video, caption=caption, supports_streaming=True, **kwargs)
    await send_extra(message.bot, sent.chat.id, sent.message_id, extra)
    return sent


async def _send_file(message: Message, video: VideoFile) -> Message:
    await message.bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
    return await _reply_video(message, FSInputFile(video.path), original_text(video.title, video.description),
                              duration=video.duration, width=video.width, height=video.height)


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
            sent = await _reply_video(message, link, info.title, duration=info.duration)
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
        cache.set(cache.key(url), hit.file_id, hit.title, hit.description)


async def _send_cached(message: Message, cache: VideoCache, key: str) -> bool:
    """Отправить видео из кэша. False — в кэше нет или file_id устарел."""
    hit = cache.get(key)
    if not hit:
        return False
    try:
        await _reply_video(message, hit.file_id, original_text(hit.title, hit.description))
        log.info("Отправлено из кэша: %s", key)
        return True
    except TelegramAPIError as e:
        log.info("file_id из кэша не подошёл (%s), качаем заново", e)
        cache.delete(key)
        return False


@router.message(CommandStart())
async def cmd_start(message: Message, settings: Settings, users: Users) -> None:
    uid = message.from_user.id
    left = users.left_today(uid)
    if left is None:
        limits = "• Лимитов нет."
    else:
        limits = (f"• До {settings.daily_limit} задач в сутки (сегодня осталось {left}), "
                  "одна задача за раз.")
    text = (
        "👋 Привет! Я скачиваю видео и готовлю их к публикации в TikTok, Reels и Shorts.\n\n"
        "📥 Пришлите ссылку на YouTube, TikTok или Instagram — скачаю оригинал или обработаю.\n"
        "✂️ Своё видео пришлите файлом — сразу открою обработку: формат 9:16, текст-хук, "
        "логотип, очистка метаданных.\n\n"
        f"{limits}\n"
        "• Обрабатывайте только видео, на которые у вас есть права.\n\n"
        "💡 Отправляйте видео именно файлом: «медиа» Telegram сжимает ещё на телефоне.\n"
        "iPhone: 📎 → Файл → Фото или видео. ПК: перетащите файл и выключите «Сжать»."
    )
    if users.is_admin(uid):
        text += "\n\n🛠 Админ: /stats, /ban id, /unban id, /restart"
    await message.answer(text)


def _admin_only(message: Message, users: Users) -> bool:
    return users.is_admin(message.from_user.id)


@router.message(Command("stats"))
async def cmd_stats(message: Message, settings: Settings, users: Users) -> None:
    if not _admin_only(message, users):
        return
    st = users.stats()
    top = "\n".join(f"  • {name or uid} ({uid}) — {n}" for uid, name, n in st.top_today) or "  —"
    mode = "открыт для всех" if settings.is_public else f"приватный (в списке {len(settings.allowed_user_ids)})"
    await message.answer(
        f"📊 Статистика\n\n"
        f"Режим: {mode}, лимит {settings.daily_limit or '∞'}/сутки\n"
        f"Пользователи: {st.users_total} (новых сегодня {st.users_new_today}, "
        f"активных сегодня {st.users_active_today}, заблокировано {st.blocked})\n"
        f"Задачи сегодня: {st.jobs_today} (с ошибкой {st.jobs_failed_today}), всего {st.jobs_total}\n"
        f"В работе сейчас: {_active_jobs}\n\n"
        f"Топ за сегодня:\n{top}"
    )


async def _set_ban(message: Message, command: CommandObject, users: Users, blocked: bool) -> None:
    if not _admin_only(message, users):
        return
    arg = (command.args or "").strip()
    if not arg.lstrip("-").isdigit():
        await message.reply(f"Использование: /{command.command} 123456789")
        return
    uid = int(arg)
    if users.is_admin(uid):
        await message.reply("Себя заблокировать нельзя 🙂")
        return
    users.set_blocked(uid, blocked)
    await message.reply(("⛔ Заблокирован: " if blocked else "✅ Разблокирован: ") + str(uid))


@router.message(Command("ban"))
async def cmd_ban(message: Message, command: CommandObject, users: Users) -> None:
    await _set_ban(message, command, users, True)


@router.message(Command("unban"))
async def cmd_unban(message: Message, command: CommandObject, users: Users) -> None:
    await _set_ban(message, command, users, False)


@router.message(Command("restart"))
async def cmd_restart(message: Message, notifier: Notifier, users: Users) -> None:
    """Перезапуск бота из Telegram — только для администратора."""
    if not users.is_admin(message.from_user.id):
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
                       settings: Settings, cache: VideoCache, users: Users, user_id: int) -> None:
    """Скачивает и отправляет оригинал. status — сообщение бота, в котором показываем прогресс."""
    global _active_jobs
    _active_jobs += 1
    try:
        # Уже отправляли это видео — пересылаем мгновенно, без скачивания и без списания лимита
        key = cache.key(url)
        if await _send_cached(reply_to, cache, key):
            await status.delete()
            return
        with users.job(user_id, "original"):
            await _download_original(reply_to, status, url, key, settings, cache, users, user_id)
    except LimitError as e:
        await status.edit_text(str(e))
    except DownloadFailed as e:
        await status.edit_text(str(e))
    except Exception:
        log.exception("Ошибка при обработке %s (пользователь %s)", url, user_id)
        await status.edit_text("💥 Что-то пошло не так. Администратор получил уведомление.")
    finally:
        _active_jobs -= 1


async def _download_original(reply_to: Message, status: Message, url: str, key: str,
                             settings: Settings, cache: VideoCache, users: Users, user_id: int) -> None:
    async def show(text: str) -> None:
        with contextlib.suppress(TelegramAPIError):  # в т.ч. «текст не изменился»
            await status.edit_text(text)  # edit_text без reply_markup заодно убирает кнопки

    async def on_position(pos: int) -> None:
        await show(queue_text(pos))

    async with download_queue.slot(0 if users.is_admin(user_id) else 1, on_position):
        await show("⏳ Скачиваю…")
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
        await show("📤 Отправляю…")
        sent = await _send_file(reply_to, video)
        if _file_id(sent):
            cache.set(key, _file_id(sent), video.title, video.description)
        await status.delete()
    finally:
        video.cleanup()
