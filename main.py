"""Точка входа: python main.py"""
import asyncio
import logging
import shutil
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession

from bot import mtproto
from bot.access import AccessMiddleware
from bot.cache import VideoCache
from bot.callbacks import router as callbacks_router
from bot.config import load_settings, mask_proxy
from bot.editor import editor_router
from bot.editor.ffmpeg import missing_tools
from bot.handlers import is_busy, router
from bot.notify import Notifier, TelegramLogHandler
from bot.updater import auto_update_loop, ensure_requirements
from bot.users import Users
from bot.watcher import watch_loop

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(base_dir: Path) -> None:
    logs = base_dir / "logs"
    logs.mkdir(exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Лог в файл с ротацией: до 5 МБ × 3 файла
    file_handler = RotatingFileHandler(logs / "bot.log", maxBytes=5 * 1024 * 1024,
                                       backupCount=3, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(FORMAT))
    root.addHandler(file_handler)
    # В консоль — только при ручном запуске (под launchd консоли нет)
    if sys.stdout.isatty():
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(FORMAT))
        root.addHandler(console)


# Временные папки, которые бот создаёт в DOWNLOAD_DIR через tempfile.mkdtemp:
# vid_ — bot/downloader.py, tt_ — bot/tiktok.py, ed_ — bot/editor/source.py
TEMP_PREFIXES = ("vid_", "tt_", "ed_")


def clean_downloads(path: Path) -> None:
    """Удаляет временные папки бота, оставшиеся после прошлого запуска. Чужие файлы не трогает."""
    for p in path.iterdir():
        if p.is_dir() and p.name.startswith(TEMP_PREFIXES):
            shutil.rmtree(p, ignore_errors=True)


async def main() -> None:
    settings = load_settings()
    setup_logging(settings.base_dir)
    await ensure_requirements(settings.base_dir)  # новые пакеты из requirements.txt — сами
    clean_downloads(settings.download_dir)

    # Увеличенный таймаут: загрузка 50 МБ в Telegram может занять пару минут
    bot = Bot(settings.bot_token, session=AiohttpSession(timeout=300))
    notifier = Notifier(bot, settings.admin_id)
    # Все ошибки (ERROR) из логов — администратору в Telegram
    logging.getLogger().addHandler(TelegramLogHandler(notifier, asyncio.get_running_loop()))

    cache = VideoCache(settings.base_dir / "cache.db")
    users = Users(settings.base_dir / "cache.db", settings.admin_id, settings.daily_limit,
                  settings.blocked_user_ids)
    dp = Dispatcher(settings=settings, cache=cache, notifier=notifier, users=users)
    # Открытый режим или белый список, блокировки, учёт пользователей
    access = AccessMiddleware(settings, users, notifier)
    dp.message.outer_middleware(access)
    dp.callback_query.outer_middleware(access)
    # editor_router первым: он перехватывает ввод фрагмента и хука раньше обработчика ссылок
    dp.include_routers(editor_router, router, callbacks_router)

    await bot.delete_webhook(drop_pending_updates=True)
    mode = ("открыт для всех" if settings.is_public
            else f"только для {sorted(settings.allowed_user_ids)}")
    logging.info("Бот запущен: %s, админ %s, лимит %s задач/сутки", mode, settings.admin_id,
                 settings.daily_limit or "∞")
    logging.info("Прокси: %s", mask_proxy(settings.proxy) if settings.proxy else "не задан")
    if missing := missing_tools():
        logging.warning("Не найдены %s — обработка видео работать не будет (README)", ", ".join(missing))
    if settings.api_id and settings.api_hash:
        try:
            await mtproto.start(settings.api_id, settings.api_hash, settings.bot_token,
                                settings.base_dir / "mtproto")
            logging.info("MTProto включён: файлы до 2 ГБ")
        except Exception:
            logging.exception("MTProto не запустился — работаем с лимитами Bot API (20/50 МБ)")
    else:
        logging.info("MTProto выключен (нет API_ID/API_HASH): лимиты Bot API 20/50 МБ")
    if settings.notify_on_start:
        # В фоне: если Telegram отвечает медленно, бот всё равно сразу начинает работать
        start_note = asyncio.create_task(notifier.send("✅ Бот запущен"))  # noqa: F841

    if settings.auto_update:
        # ссылку на задачу держим, иначе её может убрать сборщик мусора
        updater_task = asyncio.create_task(  # noqa: F841
            auto_update_loop(notifier, is_busy, settings.update_interval_hours))

    # Перезапуск при изменении .env или появлении restart.flag
    watcher_task = asyncio.create_task(  # noqa: F841
        watch_loop(settings.base_dir, notifier, is_busy))

    try:
        await dp.start_polling(bot)
    finally:
        await mtproto.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
