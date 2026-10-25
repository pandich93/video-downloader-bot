"""Скачивание видео через yt-dlp с автоматическим понижением качества."""
from __future__ import annotations

import asyncio
import copy
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadError

log = logging.getLogger(__name__)

# Порядок качества: если файл не влезает в лимит — пробуем следующее
QUALITY_STEPS = (720, 480, 360)


class DownloadFailed(Exception):
    """Ошибка, текст которой можно показать пользователю."""


@dataclass
class VideoFile:
    path: Path
    title: str
    duration: int | None
    width: int | None
    height: int | None
    workdir: Path
    description: str = ""   # описание оригинала: YouTube description, текст поста Instagram

    def cleanup(self) -> None:
        shutil.rmtree(self.workdir, ignore_errors=True)


def _format_for(h: int) -> str:
    # Предпочитаем H.264 (avc/h264) — такое видео Telegram проигрывает прямо в чате
    return (
        f"bv*[height<={h}][vcodec~='^(avc|h264)']+ba[ext=m4a]/"
        f"b[height<={h}][vcodec~='^(avc|h264)']/"
        f"bv*[height<={h}]+ba/"
        f"b[height<={h}]/b"
    )


class _YdlLogger:
    """Направляет вывод yt-dlp в logging, чтобы ошибки не дублировались в консоли."""
    def debug(self, msg): log.debug(msg)
    def info(self, msg): log.debug(msg)
    def warning(self, msg): log.debug(msg)
    def error(self, msg): log.debug(msg)


def _humanize(err: Exception) -> str:
    msg = str(err).lower()
    if any(k in msg for k in ("ssl", "eof occurred", "connection reset", "timed out",
                              "unable to connect", "proxy", "network is unreachable",
                              "connection refused", "failed to establish",
                              # разрыв соединения провайдером: ConnectionResetError / WinError 10054
                              "connection aborted", "connectionreseterror", "10054")):
        return ("🌐 Сайт недоступен из вашей сети — похоже, он заблокирован.\n"
                "Включите VPN или укажите PROXY в .env (см. README).")
    if any(k in msg for k in ("private", "login", "log in", "sign in", "cookies", "not a bot")):
        return ("🔒 Видео приватное или сайт требует вход в аккаунт.\n"
                "Для Instagram/YouTube добавьте cookies (см. README).")
    if any(k in msg for k in ("unavailable", "not available", "removed", "404", "does not exist")):
        return "❌ Видео недоступно или удалено."
    if "unsupported url" in msg:
        return "⚠️ Эта ссылка не поддерживается."
    return GENERIC_ERROR


def _clear_dir(path: Path) -> None:
    for p in path.iterdir():
        if p.is_file():
            p.unlink(missing_ok=True)
        else:
            shutil.rmtree(p, ignore_errors=True)


GENERIC_ERROR = "😕 Не удалось скачать видео. Попробуйте позже."
SIZE_MARGIN = 0.95  # оценка размера у yt-dlp приблизительная — оставляем запас 5%


def _estimate_size(fmt: dict) -> int | None:
    """Оценка размера выбранного формата (видео + аудио). None — если неизвестно."""
    total = 0
    for part in fmt.get("requested_formats") or [fmt]:
        size = part.get("filesize") or part.get("filesize_approx")
        if not size:
            return None
        total += size
    return int(total)


def _plan(ydl: yt_dlp.YoutubeDL, info: dict, max_bytes: int,
          heights: tuple[int, ...] = QUALITY_STEPS) -> list[tuple[int, str, int | None]]:
    """Подбирает форматы по ступеням качества БЕЗ скачивания.

    Возвращает [(высота, format_id, оценка_размера)] — только те, что могут влезть в лимит.
    """
    formats = info.get("formats") or []
    ctx = {
        "formats": formats,
        "has_merged_format": any("none" not in (f.get("acodec"), f.get("vcodec")) for f in formats),
        "incomplete_formats": (all(f.get("vcodec") == "none" for f in formats)
                               or all(f.get("acodec") == "none" for f in formats)),
    }
    plan, seen = [], set()
    for h in heights:
        selected = list(ydl.build_format_selector(_format_for(h))(ctx))
        if not selected:
            continue
        fmt = selected[0]
        fid = fmt.get("format_id")
        if not fid or fid in seen:
            continue
        seen.add(fid)
        est = _estimate_size(fmt)
        if est is not None and est > max_bytes * SIZE_MARGIN:
            log.info("%sp (%s): ~%.1f МБ — больше лимита, пропускаем", h, fid, est / 2**20)
            continue
        plan.append((h, fid, est))
    return plan


def _find_file(workdir: Path) -> Path | None:
    files = [p for p in workdir.iterdir()
             if p.is_file() and p.suffix not in (".part", ".ytdl", ".temp")]
    return max(files, key=lambda p: p.stat().st_size) if files else None


def _download_sync(url: str, workdir: Path, cookies: str | None, max_bytes: int,
                   proxy: str | None, heights: tuple[int, ...] = QUALITY_STEPS) -> tuple[dict, Path | None]:
    """Блокирующее скачивание (запускается в отдельном потоке).

    1. Один раз получаем информацию о видео (без скачивания).
    2. По оценке размера выбираем лучшее качество, которое влезает в лимит.
    3. Скачиваем только его. Если размер неизвестен — пробуем ступени по очереди.
    """
    opts = {
        "format": _format_for(heights[0]),
        "outtmpl": str(workdir / "%(id)s.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "playlist_items": "1",          # карусель Instagram — берём первое видео
        "max_filesize": max_bytes,       # страховка: не качаем заведомо большие файлы
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
        "retries": 3,
        "logger": _YdlLogger(),
    }
    if cookies:
        opts["cookiefile"] = cookies
    if proxy:
        opts["proxy"] = proxy

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info and info.get("entries"):
            info = next((e for e in info["entries"] if e), info)
        if not info:
            return {}, None

        plan = _plan(ydl, info, max_bytes, heights) if info.get("formats") else [(0, None, None)]
        for h, fid, est in plan:
            log.info("Качаем %sp (%s), оценка: %s", h, fid,
                     f"{est / 2**20:.1f} МБ" if est else "неизвестно")
            if fid:
                ydl.format_selector = ydl.build_format_selector(fid)
            ydl.process_ie_result(copy.deepcopy(info), download=True)
            path = _find_file(workdir)
            if path and path.stat().st_size <= max_bytes:
                return info, path
            log.info("Файл не влез в лимит — пробуем качество ниже")
            _clear_dir(workdir)
    return info, None


async def download_video(url: str, *, max_bytes: int, base_dir: Path,
                         cookies: str | None = None, proxy: str | None = None,
                         heights: tuple[int, ...] = QUALITY_STEPS) -> VideoFile:
    """heights — ступени качества (по умолчанию 720 → 480 → 360; для обработки — с 1080)."""
    workdir = Path(tempfile.mkdtemp(prefix="vid_", dir=base_dir))
    try:
        try:
            info, path = await asyncio.to_thread(
                _download_sync, url, workdir, cookies, max_bytes, proxy, heights)
        except DownloadError as e:
            text = _humanize(e)
            # Неизвестная ошибка — повод для уведомления администратору (ERROR)
            log.log(logging.ERROR if text == GENERIC_ERROR else logging.WARNING, "yt-dlp: %s", e)
            raise DownloadFailed(text) from e

        if path:
            return VideoFile(
                path=path,
                title=(info.get("title") or "").strip(),
                duration=int(info["duration"]) if info.get("duration") else None,
                width=info.get("width"),
                height=info.get("height"),
                workdir=workdir,
                description=(info.get("description") or "").strip(),
            )
        mb = max_bytes // (1024 * 1024)
        raise DownloadFailed(f"📦 Видео больше {mb} МБ даже в {heights[-1]}p — Telegram не даст его отправить.")
    except BaseException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
