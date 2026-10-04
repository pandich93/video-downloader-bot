"""Кэш отправленных видео: Telegram позволяет переслать файл повторно по file_id — мгновенно."""
from __future__ import annotations

import logging
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

log = logging.getLogger(__name__)


def normalize_url(url: str) -> str:
    """Приводит разные варианты одной ссылки к одному ключу.

    youtu.be/ID, youtube.com/watch?v=ID, /shorts/ID → yt:ID
    tiktok.com/@user/video/ID → tt:ID;  instagram.com/reel/CODE → ig:CODE
    """
    p = urlparse(url.strip())
    host = (p.hostname or "").lower()
    for prefix in ("www.", "m."):
        host = host.removeprefix(prefix)
    path = p.path.rstrip("/")

    if host == "youtu.be":
        return f"yt:{path.lstrip('/').split('/')[0]}"
    if host.endswith("youtube.com"):
        v = parse_qs(p.query).get("v")
        if v:
            return f"yt:{v[0]}"
        m = re.match(r"/(?:shorts|live|embed)/([\w-]+)", path)
        if m:
            return f"yt:{m.group(1)}"
    if host.endswith("tiktok.com"):
        m = re.search(r"/video/(\d+)", path)
        if m:
            return f"tt:{m.group(1)}"
        return f"tt-short:{host}{path}"  # короткая ссылка vm.tiktok.com/XXXX
    if host.endswith("instagram.com"):
        m = re.search(r"/(?:reels?|p|tv)/([\w-]+)", path)
        if m:
            return f"ig:{m.group(1)}"
    return f"{host}{path}"


class VideoCache:
    def __init__(self, path: Path) -> None:
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS videos ("
            " key TEXT PRIMARY KEY, file_id TEXT NOT NULL, title TEXT, created REAL)"
        )
        self.db.commit()

    @staticmethod
    def key(url: str, mode: str = "original") -> str:
        """Ключ кэша по ссылке."""
        return f"{mode}|{normalize_url(url)}"

    @staticmethod
    def key_for(norm: str, mode: str = "original") -> str:
        """Ключ кэша по уже нормализованному id, например tt:7685980523839180054."""
        return f"{mode}|{norm}"

    def get(self, key: str) -> tuple[str, str] | None:
        row = self.db.execute("SELECT file_id, title FROM videos WHERE key = ?", (key,)).fetchone()
        return (row[0], row[1] or "") if row else None

    def set(self, key: str, file_id: str, title: str = "") -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO videos (key, file_id, title, created) VALUES (?, ?, ?, ?)",
            (key, file_id, title, time.time()),
        )
        self.db.commit()

    def delete(self, key: str) -> None:
        self.db.execute("DELETE FROM videos WHERE key = ?", (key,))
        self.db.commit()
