"""Очистка папки загрузок при запуске: только временные папки бота, чужие файлы не трогаем."""
import re
from pathlib import Path

from bot.editor.source import _workdir
from main import TEMP_PREFIXES, clean_downloads

PROJECT_DIR = Path(__file__).resolve().parent.parent


def test_removes_only_bot_temp_dirs(tmp_path):
    for name in ("vid_abc123", "tt_xyz", "ed_q1w2"):
        (tmp_path / name / "nested").mkdir(parents=True)
        (tmp_path / name / "nested" / "part.mp4").write_bytes(b"0")

    # то, что бот не создавал, — даже с похожими именами
    (tmp_path / "notes.txt").write_text("мои заметки", encoding="utf-8")
    (tmp_path / "vid_report.txt").write_text("файл, а не папка бота", encoding="utf-8")
    (tmp_path / "video_final").mkdir()
    (tmp_path / "photos").mkdir()
    (tmp_path / "photos" / "cat.jpg").write_bytes(b"0")

    clean_downloads(tmp_path)

    assert sorted(p.name for p in tmp_path.iterdir()) == ["notes.txt", "photos", "vid_report.txt", "video_final"]
    assert (tmp_path / "photos" / "cat.jpg").is_file()


def test_empty_folder_is_fine(tmp_path):
    clean_downloads(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_real_editor_workdir_is_removed(tmp_path):
    workdir = _workdir(tmp_path)
    (workdir / "source.mp4").write_bytes(b"0")
    clean_downloads(tmp_path)
    assert not workdir.exists()


def test_prefixes_match_code():
    """Новый mkdtemp(prefix=...) в bot/ без правки TEMP_PREFIXES оставлял бы мусор после перезапуска."""
    found = set()
    for path in (PROJECT_DIR / "bot").rglob("*.py"):
        found |= set(re.findall(r"mkdtemp\(prefix=\"([^\"]+)\"", path.read_text(encoding="utf-8")))
    assert found == set(TEMP_PREFIXES)
