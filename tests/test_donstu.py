import json
from datetime import date

from app import donstu
from app.checker import Snapshot, find_conflicts
from app.db import Database


def rec(d, pair, subject, teacher, room, week_no, sub=0, tid=None):
    day = date.fromisoformat(d)
    return {"дата": f"{d}T00:00:00", "деньНедели": day.isoweekday(), "номерЗанятия": pair,
            "начало": "08:30", "конец": "10:05", "дисциплина": subject, "преподаватель": teacher,
            "фиоПреподавателя": teacher, "кодПреподавателя": tid or abs(hash(teacher)) % 10000,
            "аудитория": room, "типНедели": week_no, "номерПодгруппы": sub}


def write_cache(tmp_path, groups, schedules):
    (tmp_path / "groups.json").write_text(json.dumps(groups, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "teachers.json").write_text("[]", encoding="utf-8")
    for gid, rows in schedules.items():
        (tmp_path / f"g{gid}.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def test_parse_room_and_clean():
    assert donstu.parse_room("1-492") == ("1", 4)
    assert donstu.parse_room("10-101") == ("10", 1)
    assert donstu.clean_room("ДО-доц.Иванов И.И.") == ("", True)
    assert donstu.clean_room("+") == ("", False)
    assert donstu.clean_room(" 8-212 ") == ("8-212", False)
    assert donstu.split_subject("лек Физика") == ("lecture", "Физика")
    assert donstu.split_subject("лаб Химия") == ("lab", "Химия")
    assert donstu.split_subject("экз Химия")[0] is None


def test_colleges_are_skipped():
    assert "АТК" in donstu.SKIP_FACULTIES and "КЭУП" in donstu.SKIP_FACULTIES


def test_fortnight_template_week_parity_streams_and_parallel(tmp_path):
    groups = [{"id": 1, "name": "ВИ21", "kurs": 2, "facul": "ИиВТ"},
              {"id": 2, "name": "ВИ22", "kurs": 2, "facul": "ИиВТ"}]
    g1 = [
        # week 5 (odd → числитель) and week 6: the same lecture every week, shared with ВИ22
        rec("2026-09-28", 1, "лек Физика", "Петров П.П.", "1-101", 5),
        rec("2026-10-05", 1, "лек Физика", "Петров П.П.", "1-101", 6),
        # only in week 6 → знаменатель
        rec("2026-10-05", 2, "пр Химия", "Сидоров С.С.", "1-202", 6),
        # two language classes at the same time without subgroup numbers → parallel subgroups
        rec("2026-09-29", 3, "пр Английский язык", "Смит Д.", "8-301", 5),
        rec("2026-09-29", 3, "пр Английский язык", "Браун Э.", "8-302", 5),
        rec("2026-10-06", 3, "пр Английский язык", "Смит Д.", "8-301", 6),
        rec("2026-10-06", 3, "пр Английский язык", "Браун Э.", "8-302", 6),
        # online
        rec("2026-09-30", 1, "пр История", "Попова Ю.", "ДО-доц.Попова Ю.", 5),
        # a different subject in the same slot much later in the semester must not clash
        rec("2026-12-07", 1, "лек Другая дисциплина", "Иванов И.И.", "1-101", 15),
    ]
    g2 = [rec("2026-09-28", 1, "лек Физика", "Петров П.П.", "1-101", 5),
          rec("2026-10-05", 1, "лек Физика", "Петров П.П.", "1-101", 6)]
    write_cache(tmp_path, groups, {1: g1, 2: g2})

    data = donstu.build(tmp_path, today=date(2026, 9, 29))
    assert data["window"] == ["2026-09-28", "2026-10-05"]
    by_subject = {}
    for l in data["lessons"]:
        by_subject.setdefault(l["subject"], []).append(l)
    physics = by_subject["Физика"]
    assert len(physics) == 1 and physics[0]["week"] == "all" and physics[0]["groups"] == ["ВИ21", "ВИ22"]
    assert by_subject["Химия"][0]["week"] == "even"
    assert "Другая дисциплина" not in by_subject
    english = by_subject["Английский язык"]
    assert sorted(g for l in english for g in l["groups"]) == ["ВИ21/1", "ВИ21/2"]
    assert by_subject["История"][0]["online"] and by_subject["История"][0]["room"] is None

    db = Database(":memory:")
    donstu.load_into(db, data)
    snap = Snapshot(db)
    assert not [c for c in find_conflicts(snap) if c["severity"] == "error"]
    assert {g["faculty"] for g in snap.groups.values()} == {"ИиВТ"}
    room = next(r for r in snap.rooms.values() if r["name"] == "1-101")
    assert room["building"] == "1" and room["capacity"] >= 50  # the stream of two groups fits
    assert db.settings()["pairs"][0] == {"n": 1, "start": "08:30", "end": "10:05"}
