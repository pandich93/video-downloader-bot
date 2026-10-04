"""Временное хранилище ссылок: callback_data ограничена 64 байтами, поэтому в кнопку кладём короткий ключ."""
from __future__ import annotations

import secrets
import time

TTL_SECONDS = 30 * 60  # ссылка живёт 30 минут


class LinkStore:
    def __init__(self, ttl: int = TTL_SECONDS) -> None:
        self.ttl = ttl
        self._data: dict[str, tuple[str, float]] = {}

    def _cleanup(self) -> None:
        now = time.monotonic()
        for key in [k for k, (_, exp) in self._data.items() if exp < now]:
            del self._data[key]

    def put(self, url: str) -> str:
        self._cleanup()
        key = secrets.token_urlsafe(6)  # 8 символов
        self._data[key] = (url, time.monotonic() + self.ttl)
        return key

    def get(self, key: str) -> str | None:
        self._cleanup()
        item = self._data.get(key)
        return item[0] if item else None

    def pop(self, key: str) -> str | None:
        url = self.get(key)
        self._data.pop(key, None)
        return url


links = LinkStore()
