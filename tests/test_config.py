"""Разбор прокси, цвета и настроек из .env."""
from pathlib import Path

import pytest
from dotenv import dotenv_values

import bot.config as config
from bot.config import _color, load_settings, mask_proxy, normalize_proxy

ENV_EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"


@pytest.fixture
def env(monkeypatch, tmp_path):
    """load_settings без настоящего .env: только переменные теста, папки — во временном каталоге."""
    monkeypatch.setattr(config, "load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    for name in dotenv_values(ENV_EXAMPLE):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BOT_TOKEN", "123:test")
    monkeypatch.setenv("ADMIN_ID", "1")
    return monkeypatch


@pytest.mark.parametrize("value", [None, "", "   "])
def test_empty_download_dir_and_size_use_defaults(env, tmp_path, value):
    if value is not None:
        env.setenv("DOWNLOAD_DIR", value)
        env.setenv("MAX_FILE_MB", value)
    settings = load_settings()
    # пустой DOWNLOAD_DIR не должен превращаться в корень проекта — его бот очищает при запуске
    assert settings.download_dir == tmp_path / "downloads"
    assert settings.max_file_mb == 50


def test_explicit_download_dir_and_size(env, tmp_path):
    env.setenv("DOWNLOAD_DIR", "tmpdl")
    env.setenv("MAX_FILE_MB", " 20 ")
    settings = load_settings()
    assert settings.download_dir == tmp_path / "tmpdl"
    assert settings.download_dir.is_dir()
    assert settings.max_file_mb == 20


def test_env_example_copied_as_is_is_safe(env, tmp_path):
    """Первый запуск: .env.example скопирован без правок, вписаны только токен и ID."""
    for name, value in dotenv_values(ENV_EXAMPLE).items():
        if name not in ("BOT_TOKEN", "ADMIN_ID"):
            env.setenv(name, value or "")
    settings = load_settings()
    assert settings.download_dir != tmp_path
    assert settings.download_dir.is_relative_to(tmp_path)


@pytest.mark.parametrize("value", [".", "./", "..", "{root}", "{parent}"])
def test_download_dir_must_not_contain_project(env, tmp_path, value):
    """Папку загрузок бот очищает при запуске — корень проекта и папки выше него запрещены."""
    env.setenv("DOWNLOAD_DIR", value.format(root=tmp_path, parent=tmp_path.parent))
    with pytest.raises(SystemExit, match="DOWNLOAD_DIR"):
        load_settings()


def test_download_dir_inside_or_outside_project_is_allowed(env, tmp_path, tmp_path_factory):
    env.setenv("DOWNLOAD_DIR", "cache/dl")
    assert load_settings().download_dir == tmp_path / "cache" / "dl"

    elsewhere = tmp_path_factory.mktemp("elsewhere")
    env.setenv("DOWNLOAD_DIR", str(elsewhere))
    assert load_settings().download_dir == elsewhere


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
