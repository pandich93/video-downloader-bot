"""Автообновление yt-dlp: раз в сутки проверяет новую версию и перезапускает бота."""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Callable

import yt_dlp

from bot.notify import Notifier

log = logging.getLogger(__name__)


async def _run(*args: str) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out, _ = await proc.communicate()
    return proc.returncode, out.decode(errors="replace").strip()


async def _installed_version() -> str:
    # Спрашиваем у нового процесса: в текущем загружена старая версия
    _, out = await _run(sys.executable, "-c", "import yt_dlp; print(yt_dlp.version.__version__)")
    return out.splitlines()[-1] if out else ""


async def restart(notifier: Notifier) -> None:
    """Перезапуск процесса на месте — работает и под launchd, и при ручном запуске."""
    await notifier.bot.session.close()
    logging.shutdown()
    os.execv(sys.executable, [sys.executable, *sys.argv])


async def check_and_update(notifier: Notifier, is_busy: Callable[[], bool]) -> None:
    while is_busy():  # не трогаем yt-dlp во время скачивания
        await asyncio.sleep(10)

    before = yt_dlp.version.__version__
    code, out = await _run(sys.executable, "-m", "pip", "install", "-U", "-q",
                           "--disable-pip-version-check", "yt-dlp[default]")
    if code != 0:
        log.warning("Не удалось обновить yt-dlp: %s", out[-500:])
        return

    after = await _installed_version()
    if not after or after == before:
        log.info("yt-dlp актуален: %s", before)
        return

    log.info("yt-dlp обновлён: %s → %s, перезапуск", before, after)
    await notifier.send(f"⬆️ yt-dlp обновлён: {before} → {after}. Перезапускаюсь…")
    while is_busy():
        await asyncio.sleep(10)
    await restart(notifier)


async def auto_update_loop(notifier: Notifier, is_busy: Callable[[], bool],
                           interval_hours: float = 24, first_delay: float = 60) -> None:
    await asyncio.sleep(first_delay)
    while True:
        try:
            await check_and_update(notifier, is_busy)
        except Exception:
            log.exception("Автообновление yt-dlp завершилось ошибкой")
        await asyncio.sleep(interval_hours * 3600)
