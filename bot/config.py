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


def _ids(name: str) -> list[int]:
    raw = os.getenv(name, "").replace(" ", "")
    try:
        return [int(x) for x in raw.split(",") if x]
    except ValueError:
        raise SystemExit(f"{name}: ожидаются числовые Telegram ID через запятую") from None


def _flag(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    bot_token: str
    allowed_user_ids: frozenset[int]  # кому можно, кроме админа; пусто — только админ
    cookies_file: str | None
    download_dir: Path
    max_file_mb: int
    proxy: str | None = None
    admin_id: int = 0                 # кому слать уведомления
    auto_update: bool = True          # автообновление yt-dlp
    update_interval_hours: float = 24
    notify_on_start: bool = True      # сообщать о каждом (пере)запуске
    api_id: int = 0                   # MTProto для файлов больше 20/50 МБ (my.telegram.org)
    api_hash: str = ""
    video_encoder: str = "auto"       # auto | qsv | cpu — кодирование при обработке видео
    brand_color: str = "FF4D00"       # фирменный цвет (полоса прогресса), RRGGBB
    nick: str = ""                    # ник на видео (уровень «Авторский»)
    blocked_user_ids: frozenset[int] = frozenset()
    daily_limit: int = 20             # задач в сутки на пользователя (0 — без лимита; админу — всегда без)
    public_max_file_mb: int = 500     # своё видео файлом для обычных пользователей (админу — до 2 ГБ)
    notify_new_users: bool = True     # сообщать админу о новых пользователях
    public_mode: bool = False         # PUBLIC_MODE=true — бот открыт для всех
    openrouter_api_key: str = ""      # тексты ИИ для публикации (openrouter.ai/keys)
    openrouter_models: tuple[str, ...] = ()   # бесплатные модели по порядку; пусто — список из bot/llm.py
    llm_public: bool = False          # тексты ИИ всем в публичном режиме (иначе — админ и ALLOWED_USER_IDS)

    @property
    def is_public(self) -> bool:
        return self.public_mode

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openrouter_api_key)
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


def _color(value: str) -> str:
    """#FF4D00 / FF4D00 → FF4D00; пусто или ошибка — оранжевый по умолчанию."""
    v = value.strip().lstrip("#").upper()
    if len(v) == 6 and all(c in "0123456789ABCDEF" for c in v):
        return v
    if v:
        log.warning("BRAND_COLOR=%s — ожидается цвет вида #FF4D00, беру оранжевый", value)
    return "FF4D00"


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

    # По умолчанию бот приватный: админ и ALLOWED_USER_IDS. Открыть для всех — только явно, PUBLIC_MODE=true
    public_mode = _flag("PUBLIC_MODE", False)
    id_list = _ids("ALLOWED_USER_IDS")
    if public_mode and id_list:
        log.warning("PUBLIC_MODE=true — ALLOWED_USER_IDS не ограничивает доступ, бот открыт для всех")
    ids = frozenset(id_list)
    admin_raw = os.getenv("ADMIN_ID", "").strip()
    if not admin_raw and not id_list:
        raise SystemExit("ADMIN_ID не задан в .env — укажите свой Telegram ID (узнать: @userinfobot)")
    # По умолчанию администратор — первый ID из ALLOWED_USER_IDS
    admin_id = int(admin_raw) if admin_raw else id_list[0]

    # cookies нужны для Instagram и иногда для YouTube ("подтвердите, что вы не бот")
    cookies = os.getenv("COOKIES_FILE", "").strip() or None
    if cookies:
        cookies = str(_path(cookies))
        if not Path(cookies).is_file():
            log.warning("COOKIES_FILE=%s не найден — работаем без cookies", cookies)
            cookies = None

    # Пустое значение — по умолчанию: иначе папкой загрузок стал бы корень проекта,
    # а её содержимое удаляется при каждом запуске
    download_dir = _path(os.getenv("DOWNLOAD_DIR", "").strip() or "downloads")
    if BASE_DIR.resolve().is_relative_to(download_dir.resolve()):
        raise SystemExit(f"DOWNLOAD_DIR={download_dir}: это папка бота или папка выше неё — "
                         "при запуске её содержимое удаляется. Укажите отдельную папку, например downloads")
    download_dir.mkdir(parents=True, exist_ok=True)

    return Settings(
        bot_token=token,
        allowed_user_ids=ids,
        cookies_file=cookies,
        download_dir=download_dir,
        max_file_mb=int(os.getenv("MAX_FILE_MB", "").strip() or 50),
        # Прокси для заблокированных сайтов (например, TikTok в Узбекистане)
        proxy=normalize_proxy(os.getenv("PROXY", ""),
                              os.getenv("PROXY_TYPE", "http").strip() or "http"),
        admin_id=admin_id,
        auto_update=_flag("AUTO_UPDATE", True),
        update_interval_hours=float(os.getenv("UPDATE_INTERVAL_HOURS", "24")),
        notify_on_start=_flag("NOTIFY_ON_START", True),
        api_id=int(os.getenv("API_ID", "").strip() or 0),
        api_hash=os.getenv("API_HASH", "").strip(),
        video_encoder=(os.getenv("VIDEO_ENCODER", "auto").strip().lower() or "auto"),
        brand_color=_color(os.getenv("BRAND_COLOR", "")),
        nick=os.getenv("NICK", "").strip()[:40],
        blocked_user_ids=frozenset(_ids("BLOCKED_USER_IDS")),
        daily_limit=int(os.getenv("DAILY_LIMIT", "20").strip() or 0),
        public_max_file_mb=int(os.getenv("PUBLIC_MAX_FILE_MB", "500").strip() or 500),
        notify_new_users=_flag("NOTIFY_NEW_USERS", True),
        public_mode=public_mode,
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", "").strip(),
        openrouter_models=tuple(m.strip() for m in os.getenv("OPENROUTER_MODELS", "").split(",") if m.strip()),
        llm_public=_flag("LLM_PUBLIC", False),
    )
