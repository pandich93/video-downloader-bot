"""Разбор прокси и цвета из .env."""
import pytest

from bot.config import _color, mask_proxy, normalize_proxy


@pytest.mark.parametrize("raw, scheme, expected", [
    ("", "http", None),
    ("   ", "http", None),
    ("http://user:pass@1.2.3.4:8080", "http", "http://user:pass@1.2.3.4:8080"),
    ("1.2.3.4:8080:user:pass", "http", "http://user:pass@1.2.3.4:8080"),
    ("127.0.0.1:1080", "socks5", "socks5://127.0.0.1:1080"),
])
def test_normalize_proxy(raw, scheme, expected):
    assert normalize_proxy(raw, scheme) == expected


def test_normalize_proxy_rejects_unknown_format():
    with pytest.raises(SystemExit):
        normalize_proxy("a:b:c")


def test_mask_proxy_hides_credentials():
    assert mask_proxy("http://user:secret@1.2.3.4:8080") == "http://***@1.2.3.4:8080"
    assert mask_proxy("socks5://127.0.0.1:1080") == "socks5://127.0.0.1:1080"


@pytest.mark.parametrize("raw, expected", [
    ("#ff4d00", "FF4D00"),
    ("00AAFF", "00AAFF"),
    ("", "FF4D00"),
    ("red", "FF4D00"),
])
def test_color(raw, expected):
    assert _color(raw) == expected
