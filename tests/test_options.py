"""Разбор фрагмента и хука, переключение настроек редактора."""
import pytest

from bot.editor.options import (EditOptions, apply_level, fmt_duration, fmt_time, parse_fragment,
                                preset, toggle, validate_hook)


@pytest.mark.parametrize("text, expected", [
    ("0:05-0:40", (5.0, 40.0)),
    ("5-40", (5.0, 40.0)),
    ("1:10-", (70.0, None)),
    ("-0:30", (0.0, 30.0)),
    ("15", (15.0, None)),                 # одно число — начало фрагмента
    ("1:00:00-1:00:10", (3600.0, 3610.0)),
    ("0:05 – 0:40", (5.0, 40.0)),         # тире и пробелы, как пишут с телефона
    ("1,5-3", (1.5, 3.0)),
    ("-", (0.0, None)),
    ("весь", (0.0, None)),
    ("", (0.0, None)),
])
def test_parse_fragment(text, expected):
    assert parse_fragment(text) == expected


@pytest.mark.parametrize("text", ["40-5", "0:05-0:05", "abc", "1:2:3:4", "1::2-5"])
def test_parse_fragment_rejects(text):
    with pytest.raises(ValueError):
        parse_fragment(text)


def test_validate_hook():
    assert validate_hook("  Как   я *заработал*  миллион ") == "Как я *заработал* миллион"
    assert validate_hook("-") == ""
    assert validate_hook("нет") == ""
    with pytest.raises(ValueError):
        validate_hook("**")
    with pytest.raises(ValueError):
        validate_hook("а" * 81)


def test_toggle_cycles_back():
    opts = EditOptions()
    seen = [opts.frame]
    for _ in range(4):
        opts = toggle(opts, "frame")
        seen.append(opts.frame)
    assert seen == ["auto", "crop", "blur", "original", "auto"]
    with pytest.raises(ValueError):
        toggle(opts, "unknown")


def test_preset_keeps_other_settings():
    opts = EditOptions(start=5, end=20, hook="Привет", speed=1.05)
    reels = preset(opts, "reels")
    assert reels.platform == "reels" and reels.max_duration == 180
    assert (reels.start, reels.end, reels.hook, reels.speed) == (5, 20, "Привет", 1.05)
    with pytest.raises(ValueError):
        preset(opts, "vk")


def test_apply_level():
    clean = apply_level(EditOptions(style="warm", logo=True), "clean", logo_available=True)
    assert (clean.style, clean.logo, clean.fade_in, clean.progress) == ("none", False, False, False)

    styled = apply_level(EditOptions(), "styled", logo_available=False)
    assert (styled.style, styled.logo, styled.fade_in) == ("contrast", False, True)

    authored = apply_level(EditOptions(style="cool"), "authored", logo_available=True, nick_available=True)
    assert (authored.style, authored.logo, authored.nick, authored.progress) == ("cool", True, True, True)


def test_time_formatting():
    assert fmt_time(65) == "1:05"
    assert fmt_time(3725) == "1:02:05"
    assert fmt_duration(42) == "42 с"
    assert fmt_duration(90) == "1:30"
    assert EditOptions().fragment_label == "целиком"
    assert EditOptions(start=5, end=40).fragment_label == "0:05–0:40"
