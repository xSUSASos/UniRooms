"""Domain rules: hard constraints, soft costs, conflict detection and room evaluation.

Everything here is pure computation over a `Snapshot` of the database, so the solver,
the API and the tests all share exactly the same rules."""
from __future__ import annotations

import copy
from collections import defaultdict
from itertools import combinations

from .db import DAY_SHORT, LESSON_KINDS, ROOM_KINDS, Database

# How badly a room type fits a lesson type: 0 = fits, 1 = mismatch.
KIND_MISMATCH = {
    "lecture": {"lecture": 0, "practice": 1, "lab": 1, "computer": 1, "shared": 0},
    "practice": {"lecture": 1, "practice": 0, "lab": 1, "computer": 1, "shared": 0},
    "lab": {"lecture": 1, "practice": 1, "lab": 0, "computer": 0, "shared": 0},
}


def is_shared(room: dict | None) -> bool:
    """A venue that hosts several groups at once (sports hall, enterprise) — no room clashes there."""
    return bool(room) and room.get("kind") == "shared"

PREF_KINDS = {
    "building": "корпус",
    "room": "аудитория",
    "equipment": "оборудование",
    "max_floor": "этаж не выше",
    "day": "день",
    "pair": "пара",
}
ROOM_PREFS = {"building", "room", "equipment", "max_floor"}
TIME_PREFS = {"day", "pair"}


def weeks_overlap(a: str, b: str) -> bool:
    return a == "all" or b == "all" or a == b


class Snapshot:
    """Immutable view of all data needed for checking and solving."""

    def __init__(self, db: Database):
        self.settings = db.settings()
        self.weights: dict[str, int] = self.settings["weights"]
        self.rooms = {r["id"]: r for r in db.all("rooms", "building, name")}
        self.teachers = {t["id"]: t for t in db.all("teachers")}
        self.groups = {g["id"]: g for g in db.all("student_groups")}
        self.lessons = {l["id"]: l for l in db.lessons()}
        self.equipment_names = {e["code"]: e["name"] for e in db.equipment()}
        self.pairs = [p["n"] for p in self.settings["pairs"]]
        self.blocks: dict[int, list[dict]] = defaultdict(list)
        for b in db.all("room_blocks"):
            self.blocks[b["room_id"]].append(b)

    def with_times(self, times: dict[int, tuple[int, int]]) -> "Snapshot":
        """Copy of the snapshot with some lessons moved to other (day, pair) slots."""
        snap = copy.copy(self)
        snap.lessons = {lid: dict(l) for lid, l in self.lessons.items()}
        for lid, (day, pair) in times.items():
            snap.lessons[lid]["day"], snap.lessons[lid]["pair"] = day, pair
        return snap

    def with_rooms(self, rooms: dict[int, int | None]) -> "Snapshot":
        """Copy of the snapshot with some lessons placed into other rooms."""
        snap = copy.copy(self)
        snap.lessons = {lid: dict(l) for lid, l in self.lessons.items()}
        for lid, rid in rooms.items():
            snap.lessons[lid]["room_id"] = rid
        return snap

    # ---------- basic facts ----------
    def size(self, lesson: dict) -> int:
        return sum(self.groups[g]["size"] for g in lesson["group_ids"] if g in self.groups)

    def label(self, lesson: dict) -> str:
        groups = ", ".join(self.groups[g]["name"] for g in lesson["group_ids"] if g in self.groups)
        return f"{lesson['subject']} ({groups})" if groups else lesson["subject"]

    def teacher(self, lesson: dict) -> dict | None:
        return self.teachers.get(lesson.get("teacher_id"))

    def blocked(self, room_id: int, day: int, pair: int) -> str | None:
        for b in self.blocks.get(room_id, ()):
            if (b["day"] is None or b["day"] == day) and (b["pair"] is None or b["pair"] == pair):
                return b["reason"] or "закрыта"
        return None

    def eq_name(self, code: str) -> str:
        return self.equipment_names.get(code, code)

    # ---------- hard rules for (lesson, room) ----------
    def hard_issues(
        self, lesson: dict, room: dict, day: int | None = None, pair: int | None = None, check_block: bool = True
    ) -> list[str]:
        day = lesson["day"] if day is None else day
        pair = lesson["pair"] if pair is None else pair
        issues = []
        if not room["active"]:
            issues.append("аудитория выключена")
        size = self.size(lesson)
        if room["capacity"] < size:
            issues.append(f"мест {room['capacity']}, нужно {size}")
        missing = [self.eq_name(e) for e in lesson["required_equipment"] if e not in room["equipment"]]
        if missing:
            issues.append("нет: " + ", ".join(missing))
        if room["computers"] < lesson["min_computers"]:
            issues.append(f"ПК {room['computers']}, нужно {lesson['min_computers']}")
        t = self.teacher(lesson)
        if t and t["needs_accessible"] and not room["accessible"]:
            issues.append("нет доступной среды для преподавателя")
        reason = self.blocked(room["id"], day, pair) if check_block else None
        if reason:
            issues.append(f"закрыта: {reason}")
        return issues

    # ---------- soft costs for (lesson, room) ----------
    def soft_cost(self, lesson: dict, room: dict) -> tuple[int, list[str], list[str]]:
        """Return (cost, pros, cons). Lower cost is better."""
        w = self.weights
        cost = 0
        pros: list[str] = []
        cons: list[str] = []

        size = self.size(lesson)
        if size and room["capacity"] >= size:
            empty = (room["capacity"] - size) / room["capacity"]
            cost += w["waste"] * round(empty * 10)
            if empty > 0.5:
                cons.append(f"много пустых мест ({size} из {room['capacity']})")
            else:
                pros.append(f"{room['capacity']} мест на {size} чел.")

        mismatch = KIND_MISMATCH.get(lesson["kind"], {}).get(room["kind"], 0)
        if mismatch:
            cost += w["kind"] * mismatch
            cons.append(
                f"{ROOM_KINDS.get(room['kind'], room['kind']).lower()} для "
                f"{LESSON_KINDS.get(lesson['kind'], lesson['kind']).lower()}"
            )

        for g in lesson["group_ids"]:
            grp = self.groups.get(g)
            if grp and grp["home_building"] and room["building"] and grp["home_building"] != room["building"]:
                cost += w["home"]
                cons.append(f"{grp['name']} не в своём корпусе ({grp['home_building']})")

        t = self.teacher(lesson)
        if t:
            for p in t["preferences"]:
                if p.get("kind") not in ROOM_PREFS:
                    continue
                matched = pref_matches(p, room)
                weight = int(p.get("weight", 5))
                text = pref_text(p, self)
                good = matched if p.get("mode", "prefer") == "prefer" else not matched
                if p.get("kind") == "max_floor":
                    good = matched
                if good:
                    pros.append(f"пожелание: {text}")
                else:
                    cost += w["preference"] * weight
                    cons.append(f"не выполнено пожелание: {text}")
        return cost, pros, cons

    def cost_between(self, room_a: dict | None, room_b: dict | None) -> int:
        if room_a and room_b and room_a["building"] != room_b["building"]:
            return self.weights["move"]
        return 0

    # ---------- neighbourhood (consecutive pairs of one group/teacher) ----------
    def consecutive_pairs(self) -> list[tuple[int, int]]:
        """Lesson id pairs that follow each other for the same group or teacher."""
        by_owner: dict[tuple, list[dict]] = defaultdict(list)
        for l in self.lessons.values():
            if l["teacher_id"]:
                by_owner[("t", l["teacher_id"], l["day"])].append(l)
            for g in l["group_ids"]:
                by_owner[("g", g, l["day"])].append(l)
        result = set()
        for items in by_owner.values():
            for a, b in combinations(items, 2):
                if abs(a["pair"] - b["pair"]) == 1 and weeks_overlap(a["week"], b["week"]):
                    first, second = (a, b) if a["pair"] < b["pair"] else (b, a)
                    result.add((first["id"], second["id"]))
        return sorted(result)

    # ---------- occupancy ----------
    def busy(self) -> "Occupancy":
        return Occupancy(self)


class Occupancy:
    def __init__(self, snap: Snapshot):
        self.snap = snap
        self.room = defaultdict(list)
        self.teacher = defaultdict(list)
        self.group = defaultdict(list)
        for l in snap.lessons.values():
            key = (l["day"], l["pair"])
            if l["room_id"] and not l["online"] and not is_shared(snap.rooms.get(l["room_id"])):
                self.room[(l["room_id"], *key)].append(l)
            if l["teacher_id"]:
                self.teacher[(l["teacher_id"], *key)].append(l)
            for g in l["group_ids"]:
                self.group[(g, *key)].append(l)

    @staticmethod
    def _others(items, lesson):
        return [o for o in items if o["id"] != lesson["id"] and weeks_overlap(o["week"], lesson["week"])]

    def room_clash(self, lesson, room_id, day, pair):
        if is_shared(self.snap.rooms.get(room_id)):
            return []
        return self._others(self.room.get((room_id, day, pair), ()), lesson)

    def people_clash(self, lesson, day, pair) -> list[str]:
        """Reasons why the lesson's teacher/groups cannot be at (day, pair)."""
        s = self.snap
        reasons = []
        t = s.teacher(lesson)
        if t:
            if [day, pair] in t["unavailable"]:
                reasons.append(f"{t['name']} недоступен(а) в это время")
            for o in self._others(self.teacher.get((t["id"], day, pair), ()), lesson):
                reasons.append(f"{t['name']} уже ведёт «{o['subject']}»")
        for g in lesson["group_ids"]:
            for o in self._others(self.group.get((g, day, pair), ()), lesson):
                reasons.append(f"{s.groups[g]['name']} уже на «{o['subject']}»")
        return reasons


# ---------- preferences ----------
def pref_matches(p: dict, room: dict) -> bool:
    kind, value = p.get("kind"), p.get("value")
    if kind == "building":
        return room["building"] == value
    if kind == "room":
        return room["name"] == value
    if kind == "equipment":
        return value == "computers" and room["computers"] > 0 or value in room["equipment"]
    if kind == "max_floor":
        try:
            return room["floor"] <= int(value)
        except (TypeError, ValueError):
            return True
    return True


def pref_text(p: dict, snap: Snapshot | None = None) -> str:
    kind, value = p.get("kind"), p.get("value")
    if kind == "equipment" and snap:
        value = "компьютеры" if value == "computers" else snap.eq_name(value)
    if kind == "day":
        try:
            value = DAY_SHORT[int(value)]
        except (TypeError, ValueError, IndexError):
            pass
    head = PREF_KINDS.get(kind, kind)
    if kind == "max_floor":
        return f"{head} {value}"
    verb = "избегать" if p.get("mode") == "avoid" else ""
    return f"{verb} {head} {value}".strip()


# ---------- conflicts ----------
def find_conflicts(snap: Snapshot) -> list[dict]:
    out: list[dict] = []
    occ = snap.busy()
    days = snap.settings.get("days", 6)

    def add(kind, severity, message, ids):
        out.append({"kind": kind, "severity": severity, "message": message, "lesson_ids": sorted(set(ids))})

    def clashes(index, what, name_of):
        for key, items in index.items():
            if len(items) < 2:
                continue
            for a, b in combinations(items, 2):
                if weeks_overlap(a["week"], b["week"]):
                    add(
                        what,
                        "error",
                        f"{name_of(key[0])}: «{a['subject']}» и «{b['subject']}» одновременно",
                        [a["id"], b["id"]],
                    )

    clashes(occ.room, "room", lambda r: f"Аудитория {snap.rooms[r]['name']}")
    clashes(occ.teacher, "teacher", lambda t: snap.teachers[t]["name"])
    clashes(occ.group, "group", lambda g: f"Группа {snap.groups[g]['name']}")

    for l in snap.lessons.values():
        if not (0 <= l["day"] < days) or l["pair"] not in snap.pairs:
            add("slot", "error", f"«{snap.label(l)}»: неверный день или пара", [l["id"]])
        if not l["group_ids"]:
            add("data", "warning", f"«{l['subject']}»: не указаны группы", [l["id"]])
        t = snap.teacher(l)
        if t and [l["day"], l["pair"]] in t["unavailable"]:
            add("teacher", "error", f"{t['name']} недоступен(а) во время «{snap.label(l)}»", [l["id"]])
        room = snap.rooms.get(l["room_id"])
        if l["online"]:
            continue
        if room is None:
            add("unassigned", "warning", f"«{snap.label(l)}» без аудитории", [l["id"]])
        else:
            issues = snap.hard_issues(l, room)
            if issues:
                add("room_unfit", "error", f"«{snap.label(l)}» в {room['name']}: " + "; ".join(issues), [l["id"]])
    limit = snap.settings.get("max_per_day") or 0
    if limit:
        per_day: dict[tuple, list[dict]] = defaultdict(list)
        for l in snap.lessons.values():
            for g in l["group_ids"]:
                per_day[(g, l["day"])].append(l)
        for (g, day), items in per_day.items():
            for half in ("odd", "even"):
                count = len({l["pair"] for l in items if l["week"] in ("all", half)})
                if count > limit and g in snap.groups:
                    add("overload", "warning",
                        f"Группа {snap.groups[g]['name']}: {count} пар в {DAY_SHORT[day]} (лимит {limit})",
                        [l["id"] for l in items])
                    break
    order = {"error": 0, "warning": 1}
    out.sort(key=lambda c: (order[c["severity"]], c["kind"], c["message"]))
    return out


# ---------- evaluation for UI ----------
def evaluate_room(snap: Snapshot, occ: Occupancy, lesson: dict, room: dict, day: int, pair: int) -> dict:
    issues = snap.hard_issues(lesson, room, day, pair)
    for o in occ.room_clash(lesson, room["id"], day, pair):
        issues.append(f"занята: {snap.label(o)}")
    cost, pros, cons = snap.soft_cost(lesson, room)
    status = "bad" if issues else ("warn" if cons else "ok")
    return {"status": status, "cost": cost, "issues": issues, "pros": pros, "cons": cons}


def suggest_rooms(snap: Snapshot, lesson_id: int, limit: int = 12) -> list[dict]:
    lesson = snap.lessons[lesson_id]
    occ = snap.busy()
    rows = []
    for room in snap.rooms.values():
        ev = evaluate_room(snap, occ, lesson, room, lesson["day"], lesson["pair"])
        rows.append({"room_id": room["id"], "room": room["name"], "building": room["building"], **ev})
    rank = {"ok": 0, "warn": 1, "bad": 2}
    rows.sort(key=lambda r: (rank[r["status"]], r["cost"], r["room"]))
    good = [r for r in rows if r["status"] != "bad"]
    bad = [r for r in rows if r["status"] == "bad"]
    return good[:limit] + bad[: max(0, limit - len(good[:limit])) or 3]


def evaluate_grid(snap: Snapshot, lesson_id: int, day: int) -> dict:
    """Status of every (room, pair) cell and every pair (for people) on the given day."""
    lesson = snap.lessons[lesson_id]
    occ = snap.busy()
    people = {p: occ.people_clash(lesson, day, p) for p in snap.pairs}
    cells: dict[int, dict[int, dict]] = {}
    for room in snap.rooms.values():
        row = {}
        for p in snap.pairs:
            ev = evaluate_room(snap, occ, lesson, room, day, p)
            if people[p]:
                ev["issues"] = people[p] + ev["issues"]
                ev["status"] = "bad"
            row[p] = {"s": ev["status"], "r": ev["issues"] or ev["cons"]}
        cells[room["id"]] = row
    return {"cells": cells, "pairs": {p: {"s": "bad" if r else "ok", "r": r} for p, r in people.items()}}
