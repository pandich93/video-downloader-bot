"""Модуль «✂️ Редактировать»: меню, настройки, ввод фрагмента и хука, запуск обработки."""
from __future__ import annotations

import logging
from dataclasses import replace

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import (CallbackQuery, FSInputFile, InlineKeyboardMarkup, Message,
                           ReplyParameters)

from bot import mtproto
from bot.cache import VideoCache
from bot.config import Settings
from bot.downloader import DownloadFailed
from bot.editor.ffmpeg import PROJECT_DIR, EditFailed, RenderResult, make_thumbnail, render
from bot.editor.keyboards import (AUTHORED_HOOK_PROMPT, EXPIRED_TEXT, FILE_HINT, FRAGMENT_PROMPT,
                                  HOOK_PROMPT, MENU_TEXT, SETTINGS_TEXT, EditCb, cancel_kb,
                                  done_text, menu_kb, result_caption, settings_kb)
from bot.editor.options import (LEVELS, PLATFORMS, EditOptions, apply_level, parse_fragment,
                                preset, toggle, validate_hook)
from bot.editor.sessions import EditSession, sessions
from bot.editor.source import TELEGRAM_DOWNLOAD_LIMIT, Source, fetch
from bot.handlers import download_queue, job_slot, queue_text
from bot.slots import SlotQueue
from bot.users import LimitError, Users

log = logging.getLogger(__name__)
router = Router()

LOGO_PATH = PROJECT_DIR / "assets" / "logo.png"
BIG_OUTPUT_LIMIT = 1900 * 1024 * 1024      # через MTProto — почти 2 ГБ

# FFmpeg загружает процессор целиком — обрабатываем по одному видео, остальные видят свой номер
encode_queue = SlotQueue(1)
# Кто сейчас вводит текст: user_id → (ключ сессии, поле, сообщение-панель, платформы для запуска)
_pending: dict[int, tuple[str, str, Message, list[str] | None]] = {}


async def _edit(message: Message, text: str, kb: InlineKeyboardMarkup | None = None) -> None:
    try:
        await message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "not modified" not in str(e):
            log.info("Не удалось обновить сообщение: %s", e)
    except TelegramAPIError as e:
        log.info("Не удалось обновить сообщение: %s", e)


def _file_limit(settings: Settings, users: Users, uid: int) -> int:
    """Сколько можно прислать файлом: Bot API — 20 МБ; MTProto — 2 ГБ админу, остальным — PUBLIC_MAX_FILE_MB."""
    if not mtproto.enabled():
        return TELEGRAM_DOWNLOAD_LIMIT
    if users.is_admin(uid):
        return mtproto.MAX_BYTES
    return min(mtproto.MAX_BYTES, settings.public_max_file_mb * 1024 * 1024)


def _mb(n: int) -> str:
    return f"{n / 2**30:.0f} ГБ" if n >= 2**30 else f"{n // 2**20} МБ"


# ---------- вход в обработку ----------

async def open_from_link(message: Message, link_key: str, url: str) -> None:
    """Вызывается из callbacks.py по кнопке «✂️ Редактировать»."""
    origin = message.reply_to_message
    s = sessions.create(Source(url=url, chat_id=message.chat.id,
                               message_id=origin.message_id if origin else None), link_key=link_key)
    await _edit(message, MENU_TEXT, menu_kb(s))


@router.message(F.video | F.document)
async def on_video_file(message: Message, settings: Settings, users: Users) -> None:
    """Своё видео файлом — сразу в меню обработки."""
    media = message.video or message.document
    if message.document and not (media.mime_type or "").startswith("video/"):
        await message.reply("Пришлите видео или ссылку на него 🙂")
        return
    size = media.file_size or 0
    limit = _file_limit(settings, users, message.from_user.id)
    if size > limit:
        hint = ""
        if not mtproto.enabled() and users.is_admin(message.from_user.id):
            hint = "\nЧтобы обрабатывать файлы до 2 ГБ, впишите API_ID и API_HASH в .env (см. README)."
        await message.reply(f"📦 Файл больше {_mb(limit)} — пришлите видео поменьше или ссылку на него.{hint}")
        return
    s = sessions.create(Source(file_id=media.file_id, file_size=size, chat_id=message.chat.id,
                               message_id=message.message_id, title=message.caption or ""))
    # Пришло как «медиа» — подсказываем, как отправлять без сжатия
    await message.reply(MENU_TEXT + (FILE_HINT if message.video else ""), reply_markup=menu_kb(s))


# ---------- ввод текста: фрагмент и хук ----------

def _awaiting_input(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id in _pending)


@router.message(F.text, _awaiting_input)
async def on_text_input(message: Message, settings: Settings, cache: VideoCache, users: Users) -> None:
    key, field, panel, run_platforms = _pending[message.from_user.id]
    s = sessions.get(key)
    if not s:
        _pending.pop(message.from_user.id, None)
        await message.reply(EXPIRED_TEXT)
        return
    try:
        if field == "fragment":
            start, end = parse_fragment(message.text)
            s.options = replace(s.options, start=start, end=end)
        else:
            s.options = replace(s.options, hook=validate_hook(message.text))
    except ValueError:
        await message.reply("Не понял 🙂\n\n" + (FRAGMENT_PROMPT if field == "fragment" else
                                                  "Текст слишком длинный — до 80 символов и 3 строк."))
        return
    _pending.pop(message.from_user.id, None)
    if run_platforms:  # авторский уровень: хук получен — сразу в обработку
        await _run(message.bot, panel, message.from_user.id, s, settings, cache, users, run_platforms)
        return
    await _edit(panel, "⚙️ Настройки обновлены ↓")
    await message.reply(SETTINGS_TEXT, reply_markup=settings_kb(s))


# ---------- кнопки ----------

async def _session(callback: CallbackQuery, data: EditCb) -> EditSession | None:
    s = sessions.get(data.key)
    if not s:
        await callback.answer()
        await _edit(callback.message, EXPIRED_TEXT)
        return None
    if s.busy:
        await callback.answer("⏳ Видео ещё обрабатывается")
        return None
    return s


@router.callback_query(EditCb.filter(F.op == "menu"))
async def on_menu(callback: CallbackQuery, callback_data: EditCb) -> None:
    _pending.pop(callback.from_user.id, None)
    if s := await _session(callback, callback_data):
        await callback.answer()
        await _edit(callback.message, MENU_TEXT, menu_kb(s))


@router.callback_query(EditCb.filter(F.op == "settings"))
async def on_settings(callback: CallbackQuery, callback_data: EditCb) -> None:
    _pending.pop(callback.from_user.id, None)
    if s := await _session(callback, callback_data):
        await callback.answer()
        await _edit(callback.message, SETTINGS_TEXT, settings_kb(s))


@router.callback_query(EditCb.filter(F.op == "toggle"))
async def on_toggle(callback: CallbackQuery, callback_data: EditCb, settings: Settings) -> None:
    if s := await _session(callback, callback_data):
        if callback_data.val == "logo" and not s.options.logo and not LOGO_PATH.is_file():
            await callback.answer("Положите PNG-логотип в папку бота: assets/logo.png", show_alert=True)
            return
        if callback_data.val == "nick" and not s.options.nick and not settings.nick:
            await callback.answer("Впишите свой ник в .env: NICK=@ваш_канал", show_alert=True)
            return
        await callback.answer()
        s.options = toggle(s.options, callback_data.val)
        await _edit(callback.message, SETTINGS_TEXT, settings_kb(s))


@router.callback_query(EditCb.filter(F.op == "ask"))
async def on_ask(callback: CallbackQuery, callback_data: EditCb) -> None:
    if s := await _session(callback, callback_data):
        await callback.answer()
        _pending[callback.from_user.id] = (s.key, callback_data.val, callback.message, None)
        prompt = FRAGMENT_PROMPT if callback_data.val == "fragment" else HOOK_PROMPT
        await _edit(callback.message, prompt, cancel_kb(s))


@router.callback_query(EditCb.filter(F.op == "level"))
async def on_level(callback: CallbackQuery, callback_data: EditCb, settings: Settings) -> None:
    if s := await _session(callback, callback_data):
        if callback_data.val not in LEVELS:
            await callback.answer()
            return
        s.level = callback_data.val
        s.options = apply_level(s.options, s.level, LOGO_PATH.is_file(), bool(settings.nick))
        missing = []
        if s.level != "clean" and not LOGO_PATH.is_file():
            missing.append("логотипа — нет assets/logo.png")
        if s.level == "authored" and not settings.nick:
            missing.append("ника — нет NICK в .env")
        note = f" (без {', без '.join(missing)})" if missing else ""
        await callback.answer(f"Уровень: {LEVELS[s.level]}{note}")
        await _edit(callback.message, MENU_TEXT, menu_kb(s))


@router.callback_query(EditCb.filter(F.op == "close"))
async def on_close(callback: CallbackQuery, callback_data: EditCb) -> None:
    await callback.answer()
    _pending.pop(callback.from_user.id, None)
    sessions.close(callback_data.key)
    try:
        await callback.message.delete()
    except TelegramAPIError:
        pass


@router.callback_query(EditCb.filter(F.op == "preset"))
async def on_preset(callback: CallbackQuery, callback_data: EditCb,
                    settings: Settings, cache: VideoCache, users: Users) -> None:
    if s := await _session(callback, callback_data):
        s.options = preset(s.options, callback_data.val)
        await _start(callback, s, settings, cache, users, [s.options.platform])


@router.callback_query(EditCb.filter(F.op == "batch"))
async def on_batch(callback: CallbackQuery, callback_data: EditCb,
                   settings: Settings, cache: VideoCache, users: Users) -> None:
    if s := await _session(callback, callback_data):
        await _start(callback, s, settings, cache, users, list(PLATFORMS))


@router.callback_query(EditCb.filter(F.op == "run"))
async def on_run(callback: CallbackQuery, callback_data: EditCb,
                 settings: Settings, cache: VideoCache, users: Users) -> None:
    if s := await _session(callback, callback_data):
        await _start(callback, s, settings, cache, users, [s.options.platform])


# ---------- обработка и отправка ----------

async def _send(bot: Bot, status: Message, s: EditSession, r: RenderResult, o: EditOptions,
                settings: Settings) -> None:
    chat_id = s.source.chat_id or status.chat.id
    caption = result_caption(r, o)
    await bot.send_chat_action(chat_id, ChatAction.UPLOAD_VIDEO)
    if r.size <= settings.max_file_bytes:
        await bot.send_video(
            chat_id, FSInputFile(r.path, filename=f"{o.platform}.mp4"), caption=caption,
            duration=int(r.duration), width=r.width, height=r.height, supports_streaming=True,
            reply_parameters=(ReplyParameters(message_id=s.source.message_id,
                                              allow_sending_without_reply=True)
                              if s.source.message_id else None),
        )
        return

    # Больше 50 МБ — через MTProto (до 2 ГБ)
    async def progress(pct: int) -> None:
        await _edit(status, f"📤 Отправляю {o.platform_name}… {pct}%")

    thumb = await make_thumbnail(r.path, r.duration)
    try:
        await mtproto.send_video(chat_id, s.source.message_id, r.path, caption=caption,
                                 duration=r.duration, width=r.width, height=r.height,
                                 thumb=thumb, progress=progress)
    finally:
        if thumb:
            thumb.unlink(missing_ok=True)


async def _start(callback: CallbackQuery, s: EditSession, settings: Settings, cache: VideoCache,
                 users: Users, platforms: list[str]) -> None:
    await callback.answer()
    if s.level == "authored" and not s.options.hook:
        _pending[callback.from_user.id] = (s.key, "hook", callback.message, platforms)
        await _edit(callback.message, AUTHORED_HOOK_PROMPT, cancel_kb(s))
        return
    await _run(callback.bot, callback.message, callback.from_user.id, s, settings, cache, users, platforms)


async def _run(bot: Bot, status: Message, user_id: int, s: EditSession, settings: Settings,
               cache: VideoCache, users: Users, platforms: list[str]) -> None:
    _pending.pop(user_id, None)
    if s.busy:
        return
    s.busy = True
    results: list[tuple[RenderResult, EditOptions]] = []
    output_limit = BIG_OUTPUT_LIMIT if mtproto.enabled() else settings.max_file_bytes
    priority = 0 if users.is_admin(user_id) else 1   # админ — без очереди

    async with job_slot():  # перезапуск бота дождётся окончания обработки
        try:
            with users.job(user_id, "edit", count=len(platforms)):
                if s.video is None or not s.video.path.exists():
                    async def dl_position(pos: int) -> None:
                        await _edit(status, queue_text(pos))

                    async def dl_progress(pct: int) -> None:
                        await _edit(status, f"⏳ Скачиваю исходник… {pct}%")

                    async with download_queue.slot(priority, dl_position):
                        await _edit(status, "⏳ Скачиваю исходник…")
                        s.video = await fetch(bot, s.source, settings, cache, dl_progress)

                for i, pid in enumerate(platforms):
                    opts = preset(s.options, pid)
                    label = opts.platform_name + (f" ({i + 1}/{len(platforms)})" if len(platforms) > 1 else "")

                    async def position(pos: int, label: str = label) -> None:
                        await _edit(status, f"{label}: " + queue_text(pos, "обработку"))

                    async def progress(pct: int, label: str = label) -> None:
                        await _edit(status, f"🎬 Обрабатываю {label}… {pct}%")

                    async with encode_queue.slot(priority, position):
                        await _edit(status, f"🎬 Обрабатываю {label}…")
                        result = await render(s.video.path, s.video.workdir, opts, output_limit, progress,
                                              encoder_pref=settings.video_encoder, logo=LOGO_PATH,
                                              brand_color=settings.brand_color, nick=settings.nick)
                    try:
                        await _edit(status, f"📤 Отправляю {label}…")
                        await _send(bot, status, s, result, opts, settings)
                    finally:
                        result.path.unlink(missing_ok=True)
                    results.append((result, opts))

            await _edit(status, done_text(results), menu_kb(s))
        except (LimitError, DownloadFailed, EditFailed) as e:
            await _edit(status, str(e), menu_kb(s))
        except Exception:
            log.exception("Ошибка обработки видео (%s, пользователь %s)",
                          s.source.url or "файл из Telegram", user_id)
            await _edit(status, "💥 Что-то пошло не так. Администратор получил уведомление.",
                        menu_kb(s))
        finally:
            s.busy = False
