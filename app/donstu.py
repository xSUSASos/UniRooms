"""Import of the public schedule of DSTU / ДГТУ (Rostov-on-Don) from edu.donstu.ru.

The university publishes the schedule of every group through an open JSON API:
  /api/raspGrouplist?year=…   — all groups with faculties
  /api/raspTeacherlist?year=… — teachers with full names
  /api/Rasp?idGroup=…         — the whole semester of one group, lesson by lesson

A semester is turned into a weekly template: the same (day, pair, week type, subject,
teacher, room) repeated on many dates becomes one lesson; the same lecture of several
groups becomes one stream lesson. Colleges (АТК, КЭУП) and applicants are skipped.

What is not published — room capacity and equipment, group size — is estimated and
marked, so it can be corrected later through the Excel import."""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from .checker import weeks_overlap
from .db import Database

BASE = "https://edu.donstu.ru/api"
SKIP_FACULTIES = {"АТК", "КЭУП", "Абитуриенты", None, ""}  # colleges and applicants — not the university
KIND_PREFIX = {"лек": "lecture", "пр": "practice", "лаб": "lab"}
SKIP_PREFIX = {"экз", "зач", "конс", "кр", "кп", "зчО", "зачО", "экзамен", "зачет", "консультация"}
WEEK_TYPE = {0: "all", 1: "odd", 2: "even"}  # верхняя неделя = числитель, нижняя = знаменатель
ONLINE = re.compile(r"(?i)дот|онлайн|online|дистан|вебинар|moodle|teams|zoom|skillspace")

SHARED = re.compile(r"(?i)манеж|спорт|бассейн|стадион|тир\b|корт|\(пд\)")

Progress = Callable[[str, int, int], None]


def current_year(today: time.struct_time | None = None) -> str:
    t = today or time.localtime()
    start = t.tm_year if t.tm_mon >= 8 else t.tm_year - 1
    return f"{start}-{start + 1}"


def _get(url: str, retries: int = 5, timeout: float = 40) -> dict:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "UniRooms/0.3 (schedule import)"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"не удалось загрузить {url}: {last}")


def university_groups(year: str) -> list[dict]:
    groups = _get(f"{BASE}/raspGrouplist?year={year}")["data"]
    return [g for g in groups if g.get("facul") not in SKIP_FACULTIES and g.get("id")]


def download(year: str, cache: Path, progress: Progress | None = None, workers: int = 6) -> dict:
    """Fetch the group list, teachers and every group's semester into `cache` (resumable)."""
    cache.mkdir(parents=True, exist_ok=True)
    groups = university_groups(year)
    (cache / "groups.json").write_text(json.dumps(groups, ensure_ascii=False), encoding="utf-8")
    try:
        teachers = _get(f"{BASE}/raspTeacherlist?year={year}")["data"]
    except RuntimeError:
        teachers = []
    (cache / "teachers.json").write_text(json.dumps(teachers, ensure_ascii=False), encoding="utf-8")

    todo = [g for g in groups if not (cache / f"g{g['id']}.json").exists()]
    done = len(groups) - len(todo)
    failed: list[str] = []

    def fetch(g):
        data = _get(f"{BASE}/Rasp?idGroup={g['id']}")
        (cache / f"g{g['id']}.json").write_text(json.dumps(data.get("data", {}).get("rasp", []), ensure_ascii=False),
                                                encoding="utf-8")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch, g): g for g in todo}
        for f in as_completed(futures):
            done += 1
            try:
                f.result()
            except RuntimeError:
                failed.append(futures[f]["name"])
            if progress:
                progress("Загружаю расписание групп", done, len(groups))
    return {"groups": len(groups), "failed": failed}


# ---------- building the weekly template ----------
def split_subject(text: str) -> tuple[str | None, str]:
    text = (text or "").strip()
    m = re.match(r"^(\S+)\s+(.*)$", text)
    if m:
        prefix = m.group(1).lower().rstrip(".")
        if prefix in KIND_PREFIX:
            return KIND_PREFIX[prefix], m.group(2).strip()
        if prefix in SKIP_PREFIX:
            return None, m.group(2).strip()
    return "practice", text


def parse_room(name: str) -> tuple[str, int]:
    """«1-492» → corpus «1», floor 4; «10-101» → «10», 1."""
    m = re.match(r"^\s*(\d+[а-яА-Яa-zA-Z]?)\s*-\s*(\d)(\d*)", name)
    if m:
        return m.group(1), int(m.group(2)) if m.group(3) else 1
    m = re.match(r"^\s*([А-Яа-яA-Za-z]+)\s*-?\s*(\d)", name)
    if m:
        return m.group(1).upper(), int(m.group(2))
    return "", 1


def estimate_group_size(group: dict) -> int:
    name, facul = group["name"], group.get("facul") or ""
    if facul == "Асп" or name.startswith("Асп"):
        return 3
    if facul.startswith("Маг") or re.match(r"^(M|М)[A-ZА-Я]", name):
        return 15
    if re.match(r"^[А-ЯA-Z]{0,2}З", name):  # заочные группы: ВЗИС, ДЗПО, ЛЗИ …
        return 20
    return 25


def _monday(date_text: str) -> date | None:
    try:
        d = datetime.fromisoformat(str(date_text)[:10]).date()
    except ValueError:
        return None
    return d - timedelta(days=d.weekday())


def pick_window(mondays: Counter, today: date | None = None) -> tuple[date, date] | None:
    """The upper + lower week pair with the most lessons (ties → closest to today).

    The published schedule is tied to dates: subjects change during the semester, so the
    semester cannot simply be folded into one week — a real fortnight is used instead."""
    if not mondays:
        return None
    today = today or date.today()
    best = max(
        mondays,
        key=lambda m: (mondays[m] + mondays.get(m + timedelta(days=7), 0), -abs((m - today).days)),
    )
    return best, best + timedelta(days=7)


def clean_room(room: str) -> tuple[str, bool]:
    """(room name or "", is online)."""
    room = re.sub(r"\s+", " ", room or "").strip()
    if ONLINE.search(room) or re.match(r"(?i)^до[-\s]", room):
        return "", True
    if not re.search(r"[0-9А-Яа-яA-Za-z]{2,}", room) or re.fullmatch(r"\d+-", room):
        return "", False  # «+», «8-» and similar placeholders
    return room, False


def build(cache: Path, today: date | None = None) -> dict:
    """Turn cached semester schedules into rooms, teachers, groups and weekly lessons."""
    groups = json.loads((cache / "groups.json").read_text(encoding="utf-8"))
    teacher_list = json.loads((cache / "teachers.json").read_text(encoding="utf-8")) \
        if (cache / "teachers.json").exists() else []
    full_names = {t["id"]: t["name"].strip() for t in teacher_list if t.get("name")}

    records: list[tuple[dict, dict]] = []
    mondays: Counter = Counter()
    for g in groups:
        path = cache / f"g{g['id']}.json"
        if not path.exists():
            continue
        for r in json.loads(path.read_text(encoding="utf-8")):
            m = _monday(r.get("дата"))
            if m:
                mondays[m] += 1
            records.append((g, r))
    window = pick_window(mondays, today)

    # which of the two weeks is upper (числитель, 1) and which is lower (знаменатель, 2).
    # «типНедели» holds the week number of the semester: odd numbers are upper weeks.
    week_type: dict[date, int] = {}
    if window:
        numbers = Counter(int(r.get("типНедели") or 0) for _, r in records if _monday(r.get("дата")) == window[0])
        numbers.pop(0, None)
        first_upper = not numbers or numbers.most_common(1)[0][0] % 2 == 1
        week_type = {window[0]: 1 if first_upper else 2, window[1]: 2 if first_upper else 1}

    pair_times: dict[int, Counter] = defaultdict(Counter)
    occurrences: dict[tuple, set[int]] = defaultdict(set)  # lesson key -> week types seen (1, 2)
    key_groups: dict[tuple, set[str]] = defaultdict(set)
    teachers: dict[int | str, str] = {}
    rooms: set[str] = set()
    group_names: dict[str, dict] = {}
    skipped = Counter()

    for g, r in records:
        m = _monday(r.get("дата"))
        if window and m not in week_type:
            skipped["вне выбранных двух недель"] += 1
            continue
        kind, subject = split_subject(r.get("дисциплина", ""))
        if kind is None:
            skipped["экзамены и консультации"] += 1
            continue
        subject = re.sub(r",?\s*п/г\s*\d+\s*$", "", subject).strip()
        day = int(r.get("деньНедели") or 0) - 1
        pair = int(r.get("номерЗанятия") or 0)
        if not (0 <= day <= 6) or pair <= 0 or not subject:
            skipped["без дня или пары"] += 1
            continue
        pair_times[pair][(r.get("начало"), r.get("конец"))] += 1
        room, online = clean_room(r.get("аудитория") or "")
        online = online or bool(ONLINE.search(subject))
        if room:
            rooms.add(room)
        tid = r.get("кодПреподавателя") or (r.get("преподаватель") or "").strip() or None
        if tid is not None:
            teachers.setdefault(tid, full_names.get(tid)
                                or (r.get("фиоПреподавателя") or r.get("преподаватель") or "").strip())
        sub = int(r.get("номерПодгруппы") or 0)
        gname = g["name"] if not sub else f"{g['name']}/{sub}"
        if gname not in group_names:
            base = estimate_group_size(g)
            group_names[gname] = {"name": gname, "course": g.get("kurs") or 1,
                                  "size": base if not sub else max(2, base // 2), "facul": g.get("facul") or ""}
        key = (day, pair, kind, subject, tid, room, online)
        occurrences[key].add(week_type.get(m, int(r.get("типНедели") or 0)))
        key_groups[key].add(gname)

    lessons = []
    for key, weeks in occurrences.items():
        week = "all" if 0 in weeks or {1, 2} <= weeks else WEEK_TYPE.get(next(iter(weeks)), "all")
        day, pair, kind, subject, tid, room, online = key
        lessons.append({"day": day, "pair": pair, "kind": kind, "subject": subject, "teacher": tid,
                        "room": room or None, "week": week, "online": online, "groups": sorted(key_groups[key])})

    split_parallel(lessons, group_names)

    pairs = []
    for n in sorted(pair_times):
        (start, end), _ = pair_times[n].most_common(1)[0]
        if start and end:
            pairs.append({"n": n, "start": start, "end": end})
    days_used = max((l["day"] for l in lessons), default=5) + 1
    return {"groups": group_names, "teachers": teachers, "rooms": rooms, "lessons": lessons,
            "pairs": pairs, "days": max(6, days_used), "skipped": dict(skipped),
            "window": [d.isoformat() for d in window] if window else None}


def split_parallel(lessons: list[dict], group_names: dict[str, dict]) -> int:
    """Lessons that one group has at the same time (languages by level, electives) are parallel
    classes for parts of the group — the published schedule does not number these subgroups.
    Give each of them its own subgroup «Группа/N» so they are not reported as clashes."""
    at: dict[tuple, list[dict]] = defaultdict(list)
    for l in lessons:
        for g in l["groups"]:
            at[(g, l["day"], l["pair"])].append(l)
    renamed = 0
    for (g, _, _), items in at.items():
        if len(items) < 2 or "/" in g:
            continue
        items.sort(key=lambda l: (l["week"] != "all", l["subject"]))
        index: dict[int, int] = {}
        for l in items:
            used = {index[id(o)] for o in items if id(o) in index and weeks_overlap(o["week"], l["week"])}
            index[id(l)] = min(set(range(1, len(items) + 1)) - used)
        parts = max(index.values())
        if parts == 1:
            continue
        base = group_names[g]
        for l in items:
            name = f"{g}/{index[id(l)]}"
            if name not in group_names:
                group_names[name] = {**base, "name": name, "size": max(2, base["size"] // parts)}
            l["groups"] = sorted(name if x == g else x for x in l["groups"])
            renamed += 1
    return renamed


def estimate_rooms(data: dict) -> dict[str, dict]:
    """Capacity ≈ the largest audience the room already hosts; type from what is taught there."""
    size = {n: g["size"] for n, g in data["groups"].items()}
    audience: dict[str, int] = defaultdict(int)
    kinds: dict[str, Counter] = defaultdict(Counter)
    for l in data["lessons"]:
        if l["room"]:
            audience[l["room"]] = max(audience[l["room"]], sum(size[g] for g in l["groups"]))
            kinds[l["room"]][l["kind"]] += 1
    out = {}
    for name in sorted(data["rooms"]):
        building, floor = parse_room(name)
        need = audience.get(name, 20)
        capacity = max(30, -(-int(need * 1.2) // 10) * 10)  # +20% headroom, rounded up to 10
        k = kinds.get(name, Counter())
        total = sum(k.values()) or 1
        if SHARED.search(name) or not re.match(r"^\s*\d+[а-яА-Яa-zA-Z]?\s*-\s*\d", name):
            kind = "shared"  # sports venues, enterprises, project spaces: many groups at once
        elif k["lab"] / total > 0.5:
            kind = "lab"
        elif k["lecture"] / total > 0.5 and capacity >= 50:
            kind = "lecture"
        else:
            kind = "practice"
        out[name] = {"name": name, "building": building, "floor": floor, "capacity": capacity, "kind": kind,
                     "notes": "ДГТУ: вместимость оценена по расписанию"}
    return out


def load_into(db: Database, data: dict) -> dict:
    """Replace everything in the database with the DSTU template."""
    rooms = estimate_rooms(data)
    db.clear()
    db.save_settings({"pairs": data["pairs"] or db.settings()["pairs"], "days": min(7, data["days"]),
                      "max_per_day": 5, "time_limit": max(60, db.settings().get("time_limit", 20))})
    with db.tx() as c:
        room_ids = {name: db.insert("rooms", r, conn=c) for name, r in rooms.items()}
        teacher_ids = {}
        seen_names: Counter = Counter()
        for tid, name in sorted(data["teachers"].items(), key=lambda x: x[1]):
            seen_names[name] += 1
            display = name if seen_names[name] == 1 else f"{name} ({seen_names[name]})"
            teacher_ids[tid] = db.insert("teachers", {"name": display or "Без имени"}, conn=c)
        group_ids = {}
        for name, g in sorted(data["groups"].items()):
            building = ""
            group_ids[name] = db.insert("student_groups", {"name": name, "course": g["course"], "size": g["size"],
                                                           "home_building": building, "faculty": g["facul"]}, conn=c)
        links = []
        for l in data["lessons"]:
            lid = db.insert("lessons", {
                "subject": l["subject"][:200], "kind": l["kind"], "teacher_id": teacher_ids.get(l["teacher"]),
                "day": l["day"], "pair": l["pair"], "week": l["week"], "room_id": room_ids.get(l["room"]),
                "online": l["online"],
            }, conn=c)
            links += [(lid, group_ids[g]) for g in l["groups"]]
        c.executemany("INSERT OR IGNORE INTO lesson_groups VALUES(?, ?)", links)
    return {"rooms": len(rooms), "teachers": len(data["teachers"]), "groups": len(data["groups"]),
            "lessons": len(data["lessons"]), "skipped": data["skipped"]}


def import_donstu(db: Database, cache: Path, year: str | None = None, progress: Progress | None = None,
                  refresh: bool = False) -> dict:
    year = year or current_year()
    cache = cache / year
    if refresh and cache.exists():
        for f in cache.glob("g*.json"):
            f.unlink()
    info = download(year, cache, progress)
    if progress:
        progress("Собираю недельное расписание", 0, 1)
    data = build(cache)
    result = load_into(db, data)
    result.update(year=year, failed=info["failed"], window=data["window"])
    return result


if __name__ == "__main__":  # python -m app.donstu [путь к базе]
    import sys

    target = Database(sys.argv[1] if len(sys.argv) > 1 else None)
    cache_dir = Path(target.path).resolve().parent / "donstu_cache"
    res = import_donstu(target, cache_dir, progress=lambda s, a, b: print(f"\r{s}: {a}/{b}", end="", flush=True))
    print("\n", res)
