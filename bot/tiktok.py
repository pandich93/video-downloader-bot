"""TikTok через tikwm.com — для стран, где TikTok заблокирован (например, Узбекистан).

1. tikwm.com (не заблокирован) по ссылке отдаёт данные о видео и прямые ссылки на файл.
2. Файл лежит на CDN TikTok, который тоже заблокирован. Поэтому бот отдаёт ссылку
   самому Telegram: его серверы за границей и скачают видео сами (лимит — 20 МБ).
3. Если Telegram не смог — бот качает файл сам (через PROXY, если он задан).
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import aiohttp

from bot.downloader import DownloadFailed, VideoFile

log = logging.getLogger(__name__)

API_URL = "https://www.tikwm.com/api/"
BASE = "https://www.tikwm.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
URL_UPLOAD_LIMIT = 20 * 1024 * 1024  # лимит Telegram на отправку файла по ссылке


def _abs(url: str | None) -> str | None:
    if not url:
        return None
    return url if url.startswith("http") else BASE + url


@dataclass
class TikTokInfo:
    id: str | None
    title: str
    duration: int | None
    size: int            # обычное качество, байт (0 — неизвестно)
    hd_size: int
    hd_links: list[str] = field(default_factory=list)
    sd_links: list[str] = field(default_factory=list)

    def links(self, max_bytes: int) -> list[str]:
        """Ссылки по порядку: HD (если влезает), затем обычное качество."""
        out: list[str] = []
        if self.hd_size and self.hd_size <= max_bytes:
            out += self.hd_links
        if not self.size or self.size <= max_bytes:
            out += self.sd_links
        return list(dict.fromkeys(out))  # без дублей, порядок сохраняется


def _session() -> aiohttp.ClientSession:
    timeout = aiohttp.ClientTimeout(total=180, sock_connect=15, sock_read=60)
    return aiohttp.ClientSession(timeout=timeout, headers=HEADERS)


async def get_tiktok_info(url: str) -> TikTokInfo:
    async with _session() as session:
        async with session.post(API_URL, data={"url": url, "hd": "1"}) as resp:
            payload = await resp.json(content_type=None)

    data = payload.get("data")
    if payload.get("code") != 0 or not data:
        log.warning("tikwm: %s", payload.get("msg"))
        raise DownloadFailed("❌ TikTok: видео не найдено, удалено или приватное.")
    if data.get("images") and not data.get("play"):
        raise DownloadFailed("🖼 Это фото-карусель, а не видео — пока не поддерживается.")

    vid = data.get("id")
    # Прямые ссылки на CDN — первыми: Telegram скачает их без редиректов
    hd = [_abs(data.get("hdplay")), f"{BASE}/video/media/hdplay/{vid}.mp4" if vid else None]
    sd = [_abs(data.get("play")), f"{BASE}/video/media/play/{vid}.mp4" if vid else None]
    return TikTokInfo(
        id=vid,
        title=(data.get("title") or "").strip(),
        duration=int(data["duration"]) if data.get("duration") else None,
        size=int(data.get("size") or 0),
        hd_size=int(data.get("hd_size") or 0),
        hd_links=[u for u in hd if u],
        sd_links=[u for u in sd if u],
    )


async def _save(session, url: str, dest: Path, max_bytes: int, proxy: str | None) -> bool:
    """Потоковое скачивание с ограничением размера. False — если не вышло."""
    try:
        async with session.get(url, proxy=proxy) as resp:
            if resp.status != 200:
                log.info("tikwm: HTTP %s для %s", resp.status, url[:80])
                return False
            size = 0
            with dest.open("wb") as f:
                async for chunk in resp.content.iter_chunked(256 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        log.info("tikwm: файл больше лимита")
                        return False
                    f.write(chunk)
        return size > 0
    except (aiohttp.ClientError, TimeoutError) as e:
        log.info("tikwm: не удалось скачать %s…: %s", url[:80], type(e).__name__)
        return False


async def download_tiktok_file(info: TikTokInfo, *, max_bytes: int, base_dir: Path,
                               proxy: str | None = None) -> VideoFile:
    # aiohttp умеет только HTTP-прокси; SOCKS здесь не используем
    if proxy and not proxy.startswith("http"):
        log.info("tikwm: SOCKS-прокси не поддерживается aiohttp, качаем напрямую")
        proxy = None

    workdir = Path(tempfile.mkdtemp(prefix="tt_", dir=base_dir))
    dest = workdir / f"{info.id or 'tiktok'}.mp4"
    try:
        async with _session() as session:
            for link in info.links(max_bytes):
                if await _save(session, link, dest, max_bytes, proxy):
                    return VideoFile(path=dest, title=info.title, duration=info.duration,
                                     width=None, height=None, workdir=workdir)
        raise DownloadFailed(
            "🌐 TikTok: не удалось получить файл — CDN TikTok заблокирован в вашей сети.\n"
            "Включите VPN или укажите рабочий PROXY в .env."
        )
    except BaseException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
