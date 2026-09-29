"""SQLite storage: schema, settings and plain data access helpers."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS equipment(
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rooms(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    building TEXT NOT NULL DEFAULT '',
    floor INTEGER NOT NULL DEFAULT 1,
    capacity INTEGER NOT NULL DEFAULT 30,
    kind TEXT NOT NULL DEFAULT 'practice',
    computers INTEGER NOT NULL DEFAULT 0,
    equipment TEXT NOT NULL DEFAULT '[]',
    accessible INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS room_blocks(
    id INTEGER PRIMARY KEY,
    room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
    day INTEGER,
    pair INTEGER,
    reason TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS teachers(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    department TEXT NOT NULL DEFAULT '',
    needs_accessible INTEGER NOT NULL DEFAULT 0,
    unavailable TEXT NOT NULL DEFAULT '[]',
    preferences TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS student_groups(
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    course INTEGER NOT NULL DEFAULT 1,
    size INTEGER NOT NULL DEFAULT 25,
    home_building TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS lessons(
    id INTEGER PRIMARY KEY,
    subject TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'practice',
    teacher_id INTEGER REFERENCES teachers(id) ON DELETE SET NULL,
    day INTEGER NOT NULL DEFAULT 0,
    pair INTEGER NOT NULL DEFAULT 1,
    week TEXT NOT NULL DEFAULT 'all',
    required_equipment TEXT NOT NULL DEFAULT '[]',
    min_computers INTEGER NOT NULL DEFAULT 0,
    room_id INTEGER REFERENCES rooms(id) ON DELETE SET NULL,
    locked INTEGER NOT NULL DEFAULT 0,
    fixed_time INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS lesson_groups(
    lesson_id INTEGER NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL REFERENCES student_groups(id) ON DELETE CASCADE,
    PRIMARY KEY(lesson_id, group_id)
);
CREATE TABLE IF NOT EXISTS settings(
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history(
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    description TEXT NOT NULL,
    changes TEXT NOT NULL
);
"""

# columns added after v0.1 — applied to existing databases on start
MIGRATIONS = [
    ("lessons", "fixed_time", "INTEGER NOT NULL DEFAULT 0"),
]

ROOM_KINDS = {
    "lecture": "Лекционная",
    "practice": "Практическая",
    "lab": "Лаборатория",
    "computer": "Компьютерный класс",
}
LESSON_KINDS = {"lecture": "Лекция", "practice": "Практика", "lab": "Лабораторная"}
WEEKS = {"all": "Каждую неделю", "odd": "Числитель", "even": "Знаменатель"}
DAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
DAY_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

DEFAULT_EQUIPMENT = [
    ("chalkboard", "Меловая доска"),
    ("whiteboard", "Маркерная доска"),
    ("smartboard", "Интерактивная доска"),
    ("projector", "Проектор"),
    ("sound", "Звукоусиление"),
    ("lab_bench", "Лабораторные столы"),
]

DEFAULT_SETTINGS = {
    "pairs": [
        {"n": 1, "start": "08:30", "end": "10:00"},
        {"n": 2, "start": "10:10", "end": "11:40"},
        {"n": 3, "start": "12:10", "end": "13:40"},
        {"n": 4, "start": "13:50", "end": "15:20"},
        {"n": 5, "start": "15:30", "end": "17:00"},
        {"n": 6, "start": "17:10", "end": "18:40"},
    ],
    "days": 6,
    "weights": {
        "preference": 10,  # multiplied by preference weight 1..10
        "waste": 4,  # empty seats share, per 10%
        "kind": 15,  # room type does not match lesson type
        "home": 6,  # group outside its home building
        "move": 25,  # building change between consecutive pairs
        "stability": 60,  # moving an already valid lesson in "repair" mode
        # time scheduling
        "gap": 30,  # a "window" in a group's day
        "teacher_gap": 10,  # a "window" in a teacher's day
        "late": 5,  # per lesson on late pairs (5+) and on Saturday
        "spread": 20,  # same subject for the same groups twice on one day
        "time_stability": 40,  # moving a lesson in time when only fixing clashes
    },
    "time_limit": 20,
    "max_per_day": 4,  # max pairs per day for a group (0 = no limit)
    "llm": {"url": "http://127.0.0.1:11434", "model": ""},
    "network": {"enabled": False, "port": 8765, "password_hash": "", "salt": ""},
}

JSON_COLUMNS = {
    "rooms": ("equipment",),
    "teachers": ("unavailable", "preferences"),
    "lessons": ("required_equipment",),
}
BOOL_COLUMNS = {
    "rooms": ("accessible", "active"),
    "teachers": ("needs_accessible",),
    "lessons": ("locked", "fixed_time"),
}


def default_db_path() -> Path:
    base = os.environ.get("UNIROOMS_DB")
    if base:
        return Path(base)
    root = Path(os.environ.get("APPDATA") or Path.home()) / "UniRooms"
    root.mkdir(parents=True, exist_ok=True)
    return root / "unirooms.db"


class Database:
    def __init__(self, path: str | Path | None = None):
        self.path = str(path or default_db_path())
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)
        for table, column, ddl in MIGRATIONS:
            cols = {r[1] for r in self._conn.execute(f"PRAGMA table_info({table})")}
            if column not in cols:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        self.version = 0  # bumped on every write, lets clients notice changes made by others
        if not self._conn.execute("SELECT 1 FROM equipment LIMIT 1").fetchone():
            self._conn.executemany("INSERT INTO equipment VALUES(?, ?)", DEFAULT_EQUIPMENT)
        self._conn.commit()

    @contextmanager
    def tx(self):
        """Serialized transaction: commit on success, rollback on error."""
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
                self.version += 1
            except Exception:
                self._conn.rollback()
                raise

    # ---------- generic helpers ----------
    @staticmethod
    def _decode(table: str, row: sqlite3.Row) -> dict:
        d = dict(row)
        for col in JSON_COLUMNS.get(table, ()):
            d[col] = json.loads(d[col] or "[]")
        for col in BOOL_COLUMNS.get(table, ()):
            d[col] = bool(d[col])
        return d

    @staticmethod
    def _encode(table: str, data: dict) -> dict:
        d = dict(data)
        for col in JSON_COLUMNS.get(table, ()):
            if col in d:
                d[col] = json.dumps(d[col], ensure_ascii=False)
        for col in BOOL_COLUMNS.get(table, ()):
            if col in d:
                d[col] = int(bool(d[col]))
        return d

    def all(self, table: str, order: str = "id") -> list[dict]:
        with self._lock:
            rows = self._conn.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()
        return [self._decode(table, r) for r in rows]

    def get(self, table: str, id_: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(f"SELECT * FROM {table} WHERE id = ?", (id_,)).fetchone()
        return self._decode(table, row) if row else None

    def insert(self, table: str, data: dict, conn: sqlite3.Connection | None = None) -> int:
        d = self._encode(table, {k: v for k, v in data.items() if k != "id"})
        cols = ", ".join(d)
        marks = ", ".join("?" for _ in d)
        with self.tx() if conn is None else _noop(conn) as c:
            cur = c.execute(f"INSERT INTO {table}({cols}) VALUES({marks})", tuple(d.values()))
            return cur.lastrowid

    def update(self, table: str, id_: int, data: dict, conn: sqlite3.Connection | None = None) -> None:
        d = self._encode(table, {k: v for k, v in data.items() if k != "id"})
        if not d:
            return
        sets = ", ".join(f"{k} = ?" for k in d)
        with self.tx() if conn is None else _noop(conn) as c:
            c.execute(f"UPDATE {table} SET {sets} WHERE id = ?", (*d.values(), id_))

    def delete(self, table: str, id_: int) -> None:
        with self.tx() as c:
            c.execute(f"DELETE FROM {table} WHERE id = ?", (id_,))

    # ---------- equipment ----------
    def equipment(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute("SELECT * FROM equipment ORDER BY name")]

    def upsert_equipment(self, code: str, name: str) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO equipment VALUES(?, ?) ON CONFLICT(code) DO UPDATE SET name = excluded.name",
                (code, name),
            )

    def delete_equipment(self, code: str) -> None:
        with self.tx() as c:
            c.execute("DELETE FROM equipment WHERE code = ?", (code,))

    # ---------- lessons (with groups) ----------
    def lessons(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM lessons ORDER BY day, pair, id").fetchall()
            links = self._conn.execute("SELECT lesson_id, group_id FROM lesson_groups").fetchall()
        groups: dict[int, list[int]] = {}
        for lid, gid in links:
            groups.setdefault(lid, []).append(gid)
        out = []
        for r in rows:
            d = self._decode("lessons", r)
            d["group_ids"] = sorted(groups.get(d["id"], []))
            out.append(d)
        return out

    def lesson(self, id_: int) -> dict | None:
        d = self.get("lessons", id_)
        if d:
            with self._lock:
                d["group_ids"] = [
                    r[0]
                    for r in self._conn.execute(
                        "SELECT group_id FROM lesson_groups WHERE lesson_id = ? ORDER BY group_id", (id_,)
                    )
                ]
        return d

    def save_lesson(self, data: dict, id_: int | None = None) -> int:
        group_ids = data.pop("group_ids", None)
        with self.tx() as c:
            if id_ is None:
                id_ = self.insert("lessons", data, conn=c)
            else:
                self.update("lessons", id_, data, conn=c)
            if group_ids is not None:
                c.execute("DELETE FROM lesson_groups WHERE lesson_id = ?", (id_,))
                c.executemany(
                    "INSERT INTO lesson_groups VALUES(?, ?)", [(id_, int(g)) for g in dict.fromkeys(group_ids)]
                )
        return id_

    # ---------- settings ----------
    def settings(self) -> dict:
        with self._lock:
            stored = {k: json.loads(v) for k, v in self._conn.execute("SELECT key, value FROM settings")}
        result = json.loads(json.dumps(DEFAULT_SETTINGS))
        for k, v in stored.items():
            if isinstance(v, dict) and isinstance(result.get(k), dict):
                result[k].update(v)
            else:
                result[k] = v
        return result

    def save_settings(self, data: dict) -> None:
        with self.tx() as c:
            for k, v in data.items():
                if k in DEFAULT_SETTINGS:
                    c.execute(
                        "INSERT INTO settings VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (k, json.dumps(v, ensure_ascii=False)),
                    )

    # ---------- schedule changes with history ----------
    ASSIGN_FIELDS = ("room_id", "day", "pair", "locked")

    def apply_changes(self, description: str, changes: dict[int, dict]) -> int:
        """Apply {lesson_id: {field: value}} for schedule fields and record one undo step.

        Returns the number of lessons actually changed."""
        record = []
        with self.tx() as c:
            for lid, new in changes.items():
                row = c.execute(
                    "SELECT room_id, day, pair, locked FROM lessons WHERE id = ?", (lid,)
                ).fetchone()
                if not row:
                    continue
                before = {k: row[k] for k in self.ASSIGN_FIELDS}
                after = dict(before)
                after.update({k: (int(v) if k == "locked" else v) for k, v in new.items() if k in self.ASSIGN_FIELDS})
                if after == before:
                    continue
                c.execute(
                    "UPDATE lessons SET room_id = ?, day = ?, pair = ?, locked = ? WHERE id = ?",
                    (after["room_id"], after["day"], after["pair"], after["locked"], lid),
                )
                record.append({"lesson_id": lid, "before": before, "after": after})
            if record:
                c.execute(
                    "INSERT INTO history(ts, description, changes) VALUES(?, ?, ?)",
                    (datetime.now().isoformat(timespec="seconds"), description, json.dumps(record)),
                )
        return len(record)

    def history(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, description, changes FROM history ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            {"id": r["id"], "ts": r["ts"], "description": r["description"], "count": len(json.loads(r["changes"]))}
            for r in rows
        ]

    def undo(self) -> dict | None:
        with self.tx() as c:
            row = c.execute("SELECT * FROM history ORDER BY id DESC LIMIT 1").fetchone()
            if not row:
                return None
            for ch in json.loads(row["changes"]):
                b = ch["before"]
                # a room deleted meanwhile must not resurrect a dangling reference
                room = b["room_id"]
                if room is not None and not c.execute("SELECT 1 FROM rooms WHERE id = ?", (room,)).fetchone():
                    room = None
                c.execute(
                    "UPDATE lessons SET room_id = ?, day = ?, pair = ?, locked = ? WHERE id = ?",
                    (room, b["day"], b["pair"], b["locked"], ch["lesson_id"]),
                )
            c.execute("DELETE FROM history WHERE id = ?", (row["id"],))
            return {"description": row["description"]}

    # ---------- whole-db operations ----------
    def clear(self, keep_equipment: bool = True) -> None:
        with self.tx() as c:
            for t in ("lesson_groups", "lessons", "room_blocks", "rooms", "teachers", "student_groups", "history"):
                c.execute(f"DELETE FROM {t}")
            if not keep_equipment:
                c.execute("DELETE FROM equipment")

    def is_empty(self) -> bool:
        with self._lock:
            return not self._conn.execute("SELECT 1 FROM rooms LIMIT 1").fetchone()


@contextmanager
def _noop(conn):
    yield conn
