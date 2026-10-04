"""Перезапуск бота без доступа к Mac.

Раз в 30 секунд проверяем:
  • изменился ли .env — чтобы новые настройки применялись сами;
  • появился ли файл restart.flag — «кнопка перезапуска» для того, кто может положить файл в папку.
Перед перезапуском ждём окончания текущих загрузок.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Callable

from bot.notify import Notifier
from bot.updater import restart

log = logging.getLogger(__name__)

CHECK_INTERVAL = 30
FLAG_NAME = "restart.flag"


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return None


async def graceful_restart(notifier: Notifier, is_busy: Callable[[], bool], reason: str,
                           notify: bool = True) -> None:
    log.info("Перезапуск: %s", reason)
    if notify:
        await notifier.send(f"🔄 Перезапускаюсь: {reason}")
    while is_busy():
        await asyncio.sleep(5)
    await restart(notifier)


async def watch_loop(base_dir: Path, notifier: Notifier, is_busy: Callable[[], bool]) -> None:
    env_path = base_dir / ".env"
    flag_path = base_dir / FLAG_NAME
    flag_path.unlink(missing_ok=True)  # старый флаг от прошлого запуска не считается
    env_mtime = _mtime(env_path)

    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        try:
            if flag_path.exists():
                flag_path.unlink(missing_ok=True)
                await graceful_restart(notifier, is_busy, f"найден файл {FLAG_NAME}")
            current = _mtime(env_path)
            if current != env_mtime:
                env_mtime = current
                await graceful_restart(notifier, is_busy, "изменён .env")
        except Exception:
            log.exception("Ошибка в наблюдателе за файлами")
