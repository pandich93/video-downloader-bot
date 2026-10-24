"""Пользователи публичного бота: учёт, блокировки, дневные лимиты, статистика.

Хранится в той же SQLite-базе, что и кэш (cache.db).
Сутки считаются по часам компьютера, на котором работает бот.
"""
from __future__ import annotations

import contextlib
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


class LimitError(Exception):
    """Текст можно показать пользователю."""


@dataclass(frozen=True)
class Stats:
    users_total: int
    users_new_today: int
    users_active_today: int
    jobs_today: int
    jobs_failed_today: int
    jobs_total: int
    blocked: int
    top_today: list[tuple[int, str, int]]   # (id, имя, задач)


def _today() -> str:
    return time.strftime("%Y-%m-%d")


class Users:
    def __init__(self, path: Path, admin_id: int, daily_limit: int,
                 blocked_ids: frozenset[int] = frozenset()) -> None:
        self.db = sqlite3.connect(path)
        self.admin_id = admin_id
        self.daily_limit = daily_limit          # 0 — без лимита
        self.env_blocked = blocked_ids          # BLOCKED_USER_IDS из .env
        self._active: set[int] = set()          # у кого сейчас идёт задача
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS users ("
            " id INTEGER PRIMARY KEY, username TEXT, name TEXT,"
            " first_seen REAL, last_seen REAL, last_day TEXT, blocked INTEGER DEFAULT 0);"
            "CREATE TABLE IF NOT EXISTS jobs ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, kind TEXT, day TEXT,"
            " ts REAL, ok INTEGER);"
            "CREATE INDEX IF NOT EXISTS jobs_user_day ON jobs(user_id, day);"
        )
        self.db.commit()

    # ---------- учёт ----------

    def is_admin(self, uid: int) -> bool:
        return uid == self.admin_id

    def touch(self, uid: int, username: str | None, name: str) -> bool:
        """Отмечает визит. True — пользователь новый."""
        now, day = time.time(), _today()
        cur = self.db.execute(
            "UPDATE users SET username = ?, name = ?, last_seen = ?, last_day = ? WHERE id = ?",
            (username, name, now, day, uid))
        new = cur.rowcount == 0
        if new:
            self.db.execute(
                "INSERT INTO users (id, username, name, first_seen, last_seen, last_day)"
                " VALUES (?, ?, ?, ?, ?, ?)", (uid, username, name, now, now, day))
        self.db.commit()
        return new

    def is_blocked(self, uid: int) -> bool:
        if self.is_admin(uid):
            return False
        if uid in self.env_blocked:
            return True
        row = self.db.execute("SELECT blocked FROM users WHERE id = ?", (uid,)).fetchone()
        return bool(row and row[0])

    def set_blocked(self, uid: int, blocked: bool) -> None:
        self.db.execute(
            "INSERT INTO users (id, first_seen, last_seen, blocked) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET blocked = excluded.blocked",
            (uid, time.time(), time.time(), int(blocked)))
        self.db.commit()

    def jobs_today(self, uid: int) -> int:
        row = self.db.execute("SELECT COUNT(*) FROM jobs WHERE user_id = ? AND day = ?",
                              (uid, _today())).fetchone()
        return row[0]

    def left_today(self, uid: int) -> int | None:
        """Сколько задач осталось на сегодня. None — без лимита."""
        if self.is_admin(uid) or not self.daily_limit:
            return None
        return max(0, self.daily_limit - self.jobs_today(uid))

    # ---------- задачи ----------

    @contextlib.contextmanager
    def job(self, uid: int, kind: str, count: int = 1):
        """Проверяет лимиты и учитывает задачу. Внутри блока — сама работа.

        Одна активная задача на пользователя; админ — без ограничений.
        count — сколько задач списать (например, 3 для «Все 3 платформы»).
        """
        admin = self.is_admin(uid)
        if not admin:
            if uid in self._active:
                raise LimitError("⏳ У вас уже идёт задача — дождитесь, пока она закончится.")
            left = self.left_today(uid)
            if left is not None and left < count:
                extra = f" Осталось {left}, а нужно {count}." if left else ""
                raise LimitError(f"📅 Лимит на сегодня — {self.daily_limit} задач — исчерпан.{extra}\n"
                                 "Он обновится в 00:00.")
        day, now = _today(), time.time()
        ids = []
        for _ in range(count):
            ids.append(self.db.execute(
                "INSERT INTO jobs (user_id, kind, day, ts) VALUES (?, ?, ?, ?)",
                (uid, kind, day, now)).lastrowid)
        self.db.commit()
        self._active.add(uid)
        ok = False
        try:
            yield
            ok = True
        finally:
            self._active.discard(uid)
            self.db.executemany("UPDATE jobs SET ok = ? WHERE id = ?", [(int(ok), i) for i in ids])
            self.db.commit()

    # ---------- статистика ----------

    def stats(self) -> Stats:
        day = _today()
        start_of_day = time.mktime(time.strptime(day, "%Y-%m-%d"))
        q = lambda sql, *a: self.db.execute(sql, a).fetchone()[0]  # noqa: E731
        top = self.db.execute(
            "SELECT j.user_id, COALESCE(u.username, u.name, ''), COUNT(*) FROM jobs j"
            " LEFT JOIN users u ON u.id = j.user_id WHERE j.day = ?"
            " GROUP BY j.user_id ORDER BY COUNT(*) DESC LIMIT 5", (day,)).fetchall()
        return Stats(
            users_total=q("SELECT COUNT(*) FROM users"),
            users_new_today=q("SELECT COUNT(*) FROM users WHERE first_seen >= ?", start_of_day),
            users_active_today=q("SELECT COUNT(*) FROM users WHERE last_day = ?", day),
            jobs_today=q("SELECT COUNT(*) FROM jobs WHERE day = ?", day),
            jobs_failed_today=q("SELECT COUNT(*) FROM jobs WHERE day = ? AND ok = 0", day),
            jobs_total=q("SELECT COUNT(*) FROM jobs"),
            blocked=q("SELECT COUNT(*) FROM users WHERE blocked = 1") + len(self.env_blocked),
            top_today=[(r[0], r[1] or "", r[2]) for r in top],
        )
