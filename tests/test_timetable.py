from app import solver
from app.checker import Snapshot, find_conflicts
from app.db import Database
from app.seed import seed_demo
from app.timetable import solve_timetable


def make_db(max_per_day=4):
    db = Database(":memory:")
    db.save_settings({"days": 2, "max_per_day": max_per_day})
    db.insert("student_groups", dict(name="G1", size=20))
    db.insert("student_groups", dict(name="G2", size=20))
    db.insert("teachers", dict(name="T1"))
    db.insert("teachers", dict(name="T2", unavailable=[[0, 2], [0, 3]]))
    db.insert("rooms", dict(name="R1", capacity=30, kind="practice"))
    db.insert("rooms", dict(name="PC", capacity=30, kind="computer", computers=25))
    return db


def lesson(db, **kw):
    data = dict(subject="S", kind="practice", day=0, pair=1, week="all", required_equipment=[], group_ids=[1])
    data.update(kw)
    return db.save_lesson(data)


def apply(db, res):
    solver.apply(db, res["changes"], "t")


def errors(db):
    return [c for c in find_conflicts(Snapshot(db)) if c["severity"] == "error"]


def test_repair_moves_only_one_of_two_clashing_lessons():
    db = make_db()
    a = lesson(db, teacher_id=1, subject="A")
    b = lesson(db, teacher_id=1, subject="B", group_ids=[2])
    c = lesson(db, teacher_id=2, subject="C", group_ids=[2], pair=4)
    res = solve_timetable(db, "repair", 10)
    assert res["ok"] and res["moved_in_time"] == 1
    apply(db, res)
    assert not errors(db)
    assert db.lesson(c)["pair"] == 4
    assert {db.lesson(a)["pair"], db.lesson(b)["pair"]} != {1}


def test_teacher_unavailability_is_respected():
    db = make_db()
    lid = lesson(db, teacher_id=2, pair=2)  # T2 cannot teach on Mon 2–3
    res = solve_timetable(db, "repair", 10)
    apply(db, res)
    l = db.lesson(lid)
    assert (l["day"], l["pair"]) not in ((0, 2), (0, 3))


def test_single_computer_room_forces_different_times():
    db = make_db()
    a = lesson(db, subject="Lab1", kind="lab", min_computers=20, group_ids=[1])
    b = lesson(db, subject="Lab2", kind="lab", min_computers=20, group_ids=[2], teacher_id=1)
    res = solve_timetable(db, "repair", 10)
    apply(db, res)
    la, lb = db.lesson(a), db.lesson(b)
    assert (la["day"], la["pair"]) != (lb["day"], lb["pair"])
    assert la["room_id"] == lb["room_id"] == 2
    assert not errors(db)


def test_day_limit_and_locked_time():
    db = make_db(max_per_day=2)
    ids = [lesson(db, subject=f"S{i}", pair=i + 1) for i in range(3)]
    db.save_lesson({"fixed_time": True}, ids[0])
    res = solve_timetable(db, "repair", 10)
    apply(db, res)
    days = [db.lesson(i)["day"] for i in ids]
    assert days.count(0) <= 2
    assert (db.lesson(ids[0])["day"], db.lesson(ids[0])["pair"]) == (0, 1)


def test_demo_full_rebuild_has_no_errors_and_undo_restores():
    db = Database(":memory:")
    seed_demo(db)
    apply(db, solver.solve(db, "full", 10))
    before = {l["id"]: (l["day"], l["pair"], l["room_id"]) for l in db.lessons()}
    res = solve_timetable(db, "full", 20)
    assert res["ok"]
    apply(db, res)
    assert not errors(db)
    db.undo()
    assert {l["id"]: (l["day"], l["pair"], l["room_id"]) for l in db.lessons()} == before
