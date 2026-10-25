"""Понятные тексты ошибок yt-dlp: сетевая блокировка не должна считаться неизвестной ошибкой."""
import pytest

from bot.downloader import GENERIC_ERROR, _humanize

# Реальный текст из лога: TikTok заблокирован, провайдер рвёт соединение (Windows, русская локаль)
TIKTOK_RESET = ("ERROR: [vm.tiktok] ZSg94ebv6: Unable to download webpage: ('Connection aborted.', "
                "ConnectionResetError(10054, 'Удаленный хост принудительно разорвал существующее подключение', "
                "None, 10054, None))")


@pytest.mark.parametrize("text", [
    TIKTOK_RESET,
    "Unable to download webpage: <urlopen error [Errno 101] Network is unreachable>",
    "Read timed out.",
])
def test_network_errors_are_recognized(text):
    assert "🌐" in _humanize(Exception(text))


def test_unknown_error_stays_generic():
    assert _humanize(Exception("something completely different")) == GENERIC_ERROR
