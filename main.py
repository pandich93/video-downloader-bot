"""Точка входа: python main.py"""
import asyncio
import logging
import shutil
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession

from bot.access import AccessMiddleware
from bot.cache import VideoCache
from bot.callbacks import router as callbacks_router
from bot.config import load_settings, mask_proxy
from bot.handlers import is_busy, router
from bot.notify import Notifier, TelegramLogHandler
from bot.updater import auto_update_loop
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


def clean_downloads(path: Path) -> None:
    """Удаляет временные файлы, оставшиеся после прошлого запуска."""
    for p in path.iterdir():
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)


async def main() -> None:
    settings = load_settings()
    setup_logging(settings.base_dir)
    clean_downloads(settings.download_dir)

    # Увеличенный таймаут: загрузка 50 МБ в Telegram может занять пару минут
    bot = Bot(settings.bot_token, session=AiohttpSession(timeout=300))
    notifier = Notifier(bot, settings.admin_id)
    # Все ошибки (ERROR) из логов — администратору в Telegram
    logging.getLogger().addHandler(TelegramLogHandler(notifier, asyncio.get_running_loop()))

    cache = VideoCache(settings.base_dir / "cache.db")
    dp = Dispatcher(settings=settings, cache=cache, notifier=notifier)
    # Доступ только из белого списка; остальным бот сообщает их ID
    access = AccessMiddleware(settings.allowed_user_ids)
    dp.message.outer_middleware(access)
    dp.callback_query.outer_middleware(access)
    dp.include_routers(router, callbacks_router)

    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Бот запущен. Разрешённые ID: %s, админ: %s",
                 sorted(settings.allowed_user_ids), settings.admin_id)
    logging.info("Прокси: %s", mask_proxy(settings.proxy) if settings.proxy else "не задан")
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

    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
