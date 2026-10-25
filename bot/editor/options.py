"""Настройки обработки и пресеты платформ."""
from __future__ import annotations

from dataclasses import dataclass, replace

# ключ: (название, максимальная длительность в секундах)
PLATFORMS: dict[str, tuple[str, int]] = {
    "tiktok": ("TikTok", 600),
    "reels": ("Reels", 180),
    "shorts": ("Shorts", 180),
}
FRAMES = {
    "auto": "авто",
    "crop": "9:16, обрезка",
    "blur": "9:16, размытый фон",
    "original": "как в оригинале",
}
SPEEDS = (1.0, 1.05, 1.1)
VARIATIONS = {
    "medium": "средняя",
    "light": "слабая",
    "off": "выкл",
}
AUDIOS = {
    "norm": "выровнять громкость",
    "orig": "как есть",
    "mute": "без звука",
}
STYLES = {
    "none": "нет",
    "warm": "тёплый",
    "cool": "холодный",
    "contrast": "контраст",
}
LEVELS = {
    "clean": "🟢 Чистый",
    "styled": "🟡 Оформленный",
    "authored": "🟣 Авторский",
}
HOOK_MAX_CHARS = 80
HOOK_SECONDS = 3


@dataclass(frozen=True)
class EditOptions:
    platform: str = "tiktok"
    frame: str = "auto"         # auto: вертикальное видео — обрезка, горизонтальное — размытый фон
    start: float = 0.0          # фрагмент: начало, секунды
    end: float | None = None    # фрагмент: конец (None — до конца видео)
    speed: float = 1.0
    variation: str = "medium"   # лёгкий случайный зум и цвет: каждый экспорт немного другой
    audio: str = "norm"
    hook: str = ""              # текст поверх первых секунд
    logo: bool = False          # свой логотип из assets/logo.png
    style: str = "none"         # цветовой стиль
    fade_in: bool = False       # мягкое появление из чёрного в начале
    nick: bool = False          # ник (NICK из .env) на плашке сверху слева
    progress: bool = False      # полоса прогресса фирменного цвета внизу
    ai_text: bool = True        # тексты ИИ под платформу (работает, только если задан OPENROUTER_API_KEY)

    @property
    def platform_name(self) -> str:
        return PLATFORMS[self.platform][0]

    @property
    def max_duration(self) -> int:
        return PLATFORMS[self.platform][1]

    @property
    def fragment_label(self) -> str:
        if not self.start and self.end is None:
            return "целиком"
        end = fmt_time(self.end) if self.end is not None else "конец"
        return f"{fmt_time(self.start)}–{end}"


def preset(opts: EditOptions, platform: str) -> EditOptions:
    """Пресет меняет только платформу — фрагмент, хук и логотип сохраняются."""
    if platform not in PLATFORMS:
        raise ValueError(platform)
    return replace(opts, platform=platform)


def _next(items, current):
    items = list(items)
    i = items.index(current) if current in items else -1
    return items[(i + 1) % len(items)]


def toggle(opts: EditOptions, field: str) -> EditOptions:
    """Переключает настройку на следующее значение по кругу."""
    if field == "platform":
        return replace(opts, platform=_next(PLATFORMS, opts.platform))
    if field == "frame":
        return replace(opts, frame=_next(FRAMES, opts.frame))
    if field == "speed":
        return replace(opts, speed=_next(SPEEDS, opts.speed))
    if field == "var":
        return replace(opts, variation=_next(VARIATIONS, opts.variation))
    if field == "audio":
        return replace(opts, audio=_next(AUDIOS, opts.audio))
    if field == "logo":
        return replace(opts, logo=not opts.logo)
    if field == "style":
        return replace(opts, style=_next(STYLES, opts.style))
    if field == "fade":
        return replace(opts, fade_in=not opts.fade_in)
    if field == "nick":
        return replace(opts, nick=not opts.nick)
    if field == "progress":
        return replace(opts, progress=not opts.progress)
    if field == "ai":
        return replace(opts, ai_text=not opts.ai_text)
    raise ValueError(field)


def apply_level(opts: EditOptions, level: str, logo_available: bool,
                nick_available: bool = False) -> EditOptions:
    """Уровень оформления одной кнопкой. Платформа, фрагмент, скорость и хук сохраняются."""
    base = replace(opts, style="none", logo=False, fade_in=False, nick=False, progress=False)
    if level == "clean":
        return base
    styled = replace(base, style=opts.style if opts.style != "none" else "contrast",
                     logo=logo_available, fade_in=True)
    if level == "styled":
        return styled
    if level == "authored":
        return replace(styled, nick=nick_available, progress=True)
    raise ValueError(level)


def fmt_time(seconds: float) -> str:
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    return fmt_time(seconds) if seconds >= 60 else f"{seconds} с"


def _parse_time(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if not 1 <= len(parts) <= 3 or any(p == "" for p in parts):
        raise ValueError(value)
    total = 0.0
    for p in parts:
        total = total * 60 + float(p)
    if total < 0:
        raise ValueError(value)
    return total


def parse_fragment(text: str) -> tuple[float, float | None]:
    """«0:05-0:40», «5-40», «1:10-» (до конца), «-30» (с начала), «-» или «весь» — целиком."""
    t = text.strip().lower().replace(" ", "").replace("–", "-").replace("—", "-")
    if t in ("", "-", "0", "весь", "все", "всё", "целиком"):
        return 0.0, None
    a, sep, b = t.partition("-")
    start = _parse_time(a) if a else 0.0
    end = _parse_time(b) if b else None
    if not sep:            # одно число — начало фрагмента
        end = None
    if end is not None and end <= start + 0.5:
        raise ValueError(text)
    return start, end


def validate_hook(text: str) -> str:
    """Слово в *звёздочках* выделяется цветом; «-» — убрать текст."""
    text = " ".join(text.split())
    if text in ("-", "нет", "убрать"):
        return ""
    if not text.replace("*", "").strip() or len(text.replace("*", "")) > HOOK_MAX_CHARS:
        raise ValueError(text)
    return text
