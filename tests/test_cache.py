"""Нормализация ссылок и кэш file_id."""
import pytest

from bot.cache import VideoCache, normalize_url


@pytest.mark.parametrize("url, key", [
    ("https://youtu.be/dQw4w9WgXcQ", "yt:dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ?si=abc", "yt:dQw4w9WgXcQ"),
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42", "yt:dQw4w9WgXcQ"),
    ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "yt:dQw4w9WgXcQ"),
    ("https://www.youtube.com/shorts/abc_DEF-123", "yt:abc_DEF-123"),
    ("https://youtube.com/live/abc123/", "yt:abc123"),
    ("https://www.tiktok.com/@user/video/7685980523839180054?lang=en", "tt:7685980523839180054"),
    ("https://vm.tiktok.com/ZMabc123/", "tt-short:vm.tiktok.com/ZMabc123"),
    ("https://www.instagram.com/reel/C0dE_xyz/", "ig:C0dE_xyz"),
    ("https://www.instagram.com/reels/C0dE_xyz/", "ig:C0dE_xyz"),
    ("https://instagram.com/p/C0dE_xyz/?img_index=1", "ig:C0dE_xyz"),
])
def test_normalize_url(url, key):
    assert normalize_url(url) == key


def test_same_video_same_cache_key():
    assert VideoCache.key("https://youtu.be/abc") == VideoCache.key("https://www.youtube.com/watch?v=abc")
    assert VideoCache.key("https://youtu.be/abc") == "original|yt:abc"
    assert VideoCache.key_for("tt:1") == "original|tt:1"


def test_cache_roundtrip(tmp_path):
    cache = VideoCache(tmp_path / "cache.db")
    key = VideoCache.key("https://youtu.be/abc")
    assert cache.get(key) is None

    cache.set(key, "file-id-1", "Title", "Description #tag")
    assert cache.get(key) == ("file-id-1", "Title", "Description #tag")
    assert cache.get(key).description == "Description #tag"

    cache.set(key, "file-id-2")          # повторная запись заменяет старую
    assert cache.get(key) == ("file-id-2", "", "")

    cache.delete(key)
    assert cache.get(key) is None


def test_cache_from_old_version_keeps_records(tmp_path):
    """База без колонки description (прошлые версии) — записи сохраняются, описание пустое."""
    import sqlite3

    path = tmp_path / "cache.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE videos (key TEXT PRIMARY KEY, file_id TEXT NOT NULL, title TEXT, created REAL)")
    db.execute("INSERT INTO videos VALUES ('original|yt:abc', 'old-file-id', 'Old title', 0)")
    db.commit()
    db.close()

    cache = VideoCache(path)
    assert cache.get("original|yt:abc") == ("old-file-id", "Old title", "")
    cache.set("original|yt:new", "new-id", "New", "Desc")
    assert cache.get("original|yt:new").description == "Desc"
    VideoCache(path)                     # повторное открытие — миграция не падает
