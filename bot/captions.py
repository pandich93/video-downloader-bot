"""Подпись к видео: название и описание оригинала с учётом лимитов Telegram.

Telegram считает длину в UTF-16 (эмодзи — 2 единицы): подпись — до 1024, сообщение — до 4096.
Текст отправляется без parse_mode — символы < > & * _ из оригинала показываются как есть.
"""
from __future__ import annotations

CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096


def tg_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _cut(text: str, limit: int) -> str:
    """Самое длинное начало text, которое укладывается в limit единиц UTF-16."""
    if tg_len(text) <= limit:
        return text
    units = 0
    for i, ch in enumerate(text):
        units += 2 if ord(ch) > 0xFFFF else 1
        if units > limit:
            return text[:i]
    return text


def original_text(title: str, description: str = "") -> str:
    """Название и описание через пустую строку. Повторы убираются: у TikTok и Instagram
    название — часто начало описания или просто его копия."""
    title, description = (title or "").strip(), (description or "").strip()
    if not description:
        return title
    head = title.rstrip(".… ")
    if not title or description.startswith(head) or title == description:
        return description
    return f"{title}\n\n{description}"


def split_message(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Длинный текст — на части по границам строк или слов, каждая не длиннее limit."""
    parts: list[str] = []
    text = text.strip()
    while tg_len(text) > limit:
        chunk = _cut(text, limit)
        for sep in ("\n", " "):
            pos = chunk.rfind(sep)
            if pos > len(chunk) // 2:
                chunk = chunk[:pos]
                break
        parts.append(chunk.rstrip())
        text = text[len(chunk):].strip()
    if text:
        parts.append(text)
    return parts


def build_caption(text: str, footer: str = "") -> tuple[str | None, list[str]]:
    """Подпись к видео и сообщения, которые нужно отправить следом.

    Всё влезло — подпись целиком и пустой список. Не влезло — в подписи укороченный текст
    с «…» и footer, а полный текст — следующими сообщениями.
    """
    text, footer = text.strip(), footer.strip()
    full = f"{text}\n\n{footer}" if text and footer else text or footer
    if tg_len(full) <= CAPTION_LIMIT:
        return full or None, []
    tail = f"\n\n{footer}" if footer else ""
    room = CAPTION_LIMIT - tg_len(tail) - 1
    short = _cut(text, max(0, room)).rstrip()
    caption = (f"{short}…" if short else "") + tail
    return caption.strip() or None, split_message(text)
