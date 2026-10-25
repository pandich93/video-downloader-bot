"""Подпись к видео: название и описание оригинала, лимиты Telegram."""
from bot.captions import CAPTION_LIMIT, MESSAGE_LIMIT, build_caption, original_text, split_message, tg_len


def test_original_text_joins_title_and_description():
    assert original_text("Как я заработал", "Полная история #бизнес") == "Как я заработал\n\nПолная история #бизнес"
    assert original_text("  Название ", "") == "Название"
    assert original_text("", "Только описание") == "Только описание"
    assert original_text("", "") == ""


def test_original_text_drops_duplicates():
    # TikTok через yt-dlp: название — обрезанное начало описания
    assert original_text("Мой первый день на работе…", "Мой первый день на работе в Ташкенте #fyp") \
        == "Мой первый день на работе в Ташкенте #fyp"
    # Instagram и tikwm: название и описание совпадают
    assert original_text("Текст поста", "Текст поста") == "Текст поста"


def test_short_text_fits_caption():
    caption, extra = build_caption("Название\n\nОписание", footer="TikTok · 1080×1920")
    assert caption == "Название\n\nОписание\n\nTikTok · 1080×1920"
    assert extra == []


def test_empty_caption_is_none():
    assert build_caption("") == (None, [])
    assert build_caption("", footer="TikTok") == ("TikTok", [])


def test_long_text_is_cut_and_sent_in_full():
    text = "Название\n\n" + "очень длинное описание " * 100
    footer = "Изменено: кадр 9:16 · метаданные удалены"
    caption, extra = build_caption(text, footer=footer)
    assert tg_len(caption) <= CAPTION_LIMIT
    assert caption.endswith("…\n\n" + footer) and caption.startswith("Название")
    assert extra == [text.strip()]       # полный текст — одним сообщением, ничего не потеряно


def test_very_long_text_split_into_messages():
    text = "слово " * 2000                 # 12 000 символов — больше одного сообщения
    _, extra = build_caption(text)
    assert len(extra) == 3
    assert all(tg_len(p) <= MESSAGE_LIMIT for p in extra)
    assert " ".join(extra).split() == text.split()


def test_emoji_counted_as_two_units():
    text = "🔥" * 600                      # 600 символов, но 1200 единиц UTF-16
    caption, extra = build_caption(text)
    assert tg_len(caption) <= CAPTION_LIMIT
    assert extra == [text]
    assert "\ud83d" not in caption          # эмодзи не разрезано пополам


def test_split_message_on_line_boundaries():
    lines = [f"строка {i} " + "x" * 50 for i in range(200)]
    parts = split_message("\n".join(lines), limit=1000)
    assert len(parts) > 1
    assert all(tg_len(p) <= 1000 for p in parts)
    assert all(p.startswith("строка") for p in parts)   # части начинаются с новой строки
    assert "\n".join(parts) == "\n".join(lines)


def test_split_message_without_spaces():
    parts = split_message("a" * 2500, limit=1000)
    assert [len(p) for p in parts] == [1000, 1000, 500]


def test_special_characters_kept_as_is():
    text = "<b>не тег</b> & **не жирный** __и__ [ссылка](x)"
    assert build_caption(text) == (text, [])
