"""Сессии обработки: исходник и настройки живут 30 минут.

Скачанный исходник хранится в сессии — повторный вариант (для другого аккаунта)
делается без нового скачивания.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field

from bot.downloader import VideoFile
from bot.editor.options import EditOptions
from bot.editor.source import Source

TTL_SECONDS = 30 * 60
MAX_CACHED_SOURCES = 3   # больше исходников на диске не держим


@dataclass
class EditSession:
    key: str
    source: Source
    link_key: str | None = None          # ключ ссылки для кнопки «← Назад»
    options: EditOptions = field(default_factory=EditOptions)
    video: VideoFile | None = None
    level: str = "clean"                 # 🟢 / 🟡 / 🟣 — уровень оформления
    busy: bool = False
    expires: float = 0.0
    last_used: float = 0.0


class SessionStore:
    def __init__(self, ttl: int = TTL_SECONDS) -> None:
        self.ttl = ttl
        self._data: dict[str, EditSession] = {}

    def _drop(self, key: str) -> None:
        s = self._data.pop(key, None)
        if s and s.video:
            s.video.cleanup()

    def _cleanup(self) -> None:
        now = time.monotonic()
        for key, s in list(self._data.items()):
            if s.expires < now and not s.busy:
                self._drop(key)
        idle = sorted((s for s in self._data.values() if s.video and not s.busy),
                      key=lambda s: s.last_used)
        for s in idle[:-MAX_CACHED_SOURCES]:
            s.video.cleanup()
            s.video = None

    def create(self, source: Source, link_key: str | None = None) -> EditSession:
        self._cleanup()
        now = time.monotonic()
        s = EditSession(key=secrets.token_urlsafe(6), source=source, link_key=link_key,
                        expires=now + self.ttl, last_used=now)
        self._data[s.key] = s
        return s

    def get(self, key: str) -> EditSession | None:
        self._cleanup()
        s = self._data.get(key)
        if s:
            now = time.monotonic()
            s.expires, s.last_used = now + self.ttl, now
        return s

    def close(self, key: str) -> None:
        s = self._data.get(key)
        if s and not s.busy:
            self._drop(key)


sessions = SessionStore()
