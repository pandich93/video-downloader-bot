"""Графика поверх видео через Pillow: текст-хук, ник, логотип-плашка.

FFmpeg-ский drawtext не умеет нормальных шрифтовых эффектов, поэтому графика
рисуется в PNG с прозрачностью и накладывается на видео (с анимацией — в ffmpeg.py).
Стиль хука: белый жирный текст с чёрной обводкой и мягкой тенью,
слово в *звёздочках* — акцентным цветом.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # Pillow импортируется при первом использовании: без него бот всё равно запустится
    from PIL import ImageDraw

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
FONT_CANDIDATES = [
    PROJECT_DIR / "assets" / "font.ttf",                                  # свой шрифт — положите сюда
    PROJECT_DIR / "assets" / "fonts" / "Montserrat-ExtraBold.ttf",        # по умолчанию (OFL)
]
ACCENT = (255, 214, 10, 255)
WHITE = (255, 255, 255, 255)
MAX_LINES = 3


class OverlayError(Exception):
    pass


@dataclass(frozen=True)
class Placed:
    """PNG и его положение в кадре."""
    path: Path
    x: int
    y: int
    width: int
    height: int


def find_font() -> Path:
    for f in FONT_CANDIDATES:
        if f.is_file():
            return f
    raise OverlayError("🔤 Не найден шрифт: нет файла assets/fonts/Montserrat-ExtraBold.ttf.")


def parse_accent(text: str) -> list[tuple[str, bool]]:
    """«Как я *заработал* миллион» → [(Как, False), (я, False), (заработал, True), (миллион, False)]."""
    words: list[tuple[str, bool]] = []
    for part in re.split(r"(\*[^*]+\*)", text):
        accent = len(part) > 2 and part.startswith("*") and part.endswith("*")
        for w in (part[1:-1] if accent else part.replace("*", "")).split():
            words.append((w, accent))
    return words


def plain_text(text: str) -> str:
    return " ".join(w for w, _ in parse_accent(text))


def _wrap(words, font, max_w: float, draw: "ImageDraw.ImageDraw") -> list[list[tuple[str, bool]]]:
    lines, cur = [], []
    for w in words:
        trial = " ".join(x for x, _ in cur + [w])
        if cur and draw.textlength(trial, font=font) > max_w:
            lines.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        lines.append(cur)
    return lines


def render_hook(text: str, frame_w: int, frame_h: int, out: Path, y_frac: float = 0.15) -> Placed:
    """Хук — отдельной картинкой по размеру текста, по центру кадра по горизонтали."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    words = parse_accent(text)
    if not words:
        raise OverlayError("пустой текст")
    font_path = find_font()
    base = min(frame_w, frame_h)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    size = int(base * 0.085)
    while True:  # автоподбор кегля: не больше 3 строк в 84% ширины кадра
        font = ImageFont.truetype(str(font_path), size)
        lines = _wrap(words, font, frame_w * 0.84, probe)
        if len(lines) <= MAX_LINES or size <= base * 0.045:
            break
        size -= 3

    asc, desc = font.getmetrics()
    line_h = int((asc + desc) * 1.1)
    stroke = max(3, int(size * 0.09))
    pad = stroke + int(size * 0.25)            # место под обводку и тень
    widths = [probe.textlength(" ".join(w for w, _ in line), font=font) for line in lines]
    W = int(max(widths)) + pad * 2
    H = line_h * len(lines) + pad * 2

    text_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    td, sd = ImageDraw.Draw(text_layer), ImageDraw.Draw(shadow)
    space = probe.textlength(" ", font=font)
    y = pad
    for line, lw in zip(lines, widths):
        x = (W - lw) / 2
        for word, accent in line:
            sd.text((x + size * 0.04, y + size * 0.06), word, font=font, fill=(0, 0, 0, 150),
                    stroke_width=stroke, stroke_fill=(0, 0, 0, 150))
            td.text((x, y), word, font=font, fill=ACCENT if accent else WHITE,
                    stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
            x += probe.textlength(word, font=font) + space
        y += line_h
    img = shadow.filter(ImageFilter.GaussianBlur(size * 0.08))
    img.alpha_composite(text_layer)
    img.save(out)
    return Placed(out, (frame_w - W) // 2, int(frame_h * y_frac), W, H)


def render_nick(nick: str, frame_w: int, frame_h: int, out: Path) -> Placed:
    """Ник на полупрозрачной скруглённой плашке, сверху слева."""
    from PIL import Image, ImageDraw, ImageFont

    font_path = find_font()
    size = max(14, int(min(frame_w, frame_h) * 0.032))
    font = ImageFont.truetype(str(font_path), size)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    tw = probe.textlength(nick, font=font)
    asc, desc = font.getmetrics()
    px, py = int(size * 0.55), int(size * 0.3)
    W, H = int(tw) + px * 2, asc + desc + py * 2
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, W - 1, H - 1), radius=H // 2, fill=(0, 0, 0, 115))
    d.text((px, py), nick, font=font, fill=(255, 255, 255, 240))
    img.save(out)
    return Placed(out, int(frame_w * 0.05), int(frame_h * 0.055), W, H)
