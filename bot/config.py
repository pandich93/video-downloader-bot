"""Загрузка настроек из .env."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

log = logging.getLogger(__name__)

# Корень проекта: относительные пути из .env считаем от него (важно при автозапуске через launchd)
BASE_DIR = Path(__file__).resolve().parent.parent


def _path(value: str) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else BASE_DIR / p


def _flag(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    bot_token: str
    allowed_user_ids: frozenset[int]
    cookies_file: str | None
    download_dir: Path
    max_file_mb: int
    proxy: str | None = None
    admin_id: int = 0                 # кому слать уведомления
    auto_update: bool = True          # автообновление yt-dlp
    update_interval_hours: float = 24
    notify_on_start: bool = True      # сообщать о каждом (пере)запуске
    base_dir: Path = BASE_DIR

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024


def normalize_proxy(raw: str, scheme: str = "http") -> str | None:
    """Приводит прокси к виду, понятному yt-dlp: scheme://user:pass@host:port.

    Принимает также формат продавцов прокси: host:port:user:pass или host:port.
    """
    raw = raw.strip()
    if not raw:
        return None
    if "://" in raw:
        return raw
    parts = raw.split(":")
    if len(parts) == 4:
        host, port, user, password = parts
        return f"{scheme}://{user}:{password}@{host}:{port}"
    if len(parts) == 2:
        return f"{scheme}://{raw}"
    raise SystemExit("PROXY: неизвестный формат. Ожидается host:port:user:pass "
                     "или http://user:pass@host:port")


def mask_proxy(proxy: str) -> str:
    """Скрывает логин и пароль для логов."""
    if "@" not in proxy:
        return proxy
    scheme, rest = proxy.split("://", 1)
    return f"{scheme}://***@{rest.rsplit('@', 1)[1]}"


def load_settings() -> Settings:
    load_dotenv(BASE_DIR / ".env")

    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN не задан в .env")

    raw_ids = os.getenv("ALLOWED_USER_IDS", "").replace(" ", "")
    id_list = [int(x) for x in raw_ids.split(",") if x]
    ids = frozenset(id_list)
    if not ids:
        raise SystemExit("ALLOWED_USER_IDS пуст — укажите свой Telegram ID")

    # cookies нужны для Instagram и иногда для YouTube ("подтвердите, что вы не бот")
    cookies = os.getenv("COOKIES_FILE", "").strip() or None
    if cookies:
        cookies = str(_path(cookies))
        if not Path(cookies).is_file():
            log.warning("COOKIES_FILE=%s не найден — работаем без cookies", cookies)
            cookies = None

    download_dir = _path(os.getenv("DOWNLOAD_DIR", "downloads"))
    download_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        bot_token=token,
        allowed_user_ids=ids,
        cookies_file=cookies,
        download_dir=download_dir,
        max_file_mb=int(os.getenv("MAX_FILE_MB", "50")),
        # Прокси для заблокированных сайтов (например, TikTok в Узбекистане)
        proxy=normalize_proxy(os.getenv("PROXY", ""),
                              os.getenv("PROXY_TYPE", "http").strip() or "http"),
        # По умолчанию администратор — первый ID из ALLOWED_USER_IDS
        admin_id=int(os.getenv("ADMIN_ID", "").strip() or id_list[0]),
        auto_update=_flag("AUTO_UPDATE", True),
        update_interval_hours=float(os.getenv("UPDATE_INTERVAL_HOURS", "24")),
        notify_on_start=_flag("NOTIFY_ON_START", True),
    )
