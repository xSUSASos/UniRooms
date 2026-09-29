from fastapi.testclient import TestClient

from app import excel_io, solver
from app.api import create_app
from app.checker import Snapshot, find_conflicts
from app.db import Database
from app.seed import seed_demo


def make_db():
    db = Database(":memory:")
    db.insert("student_groups", dict(name="G1", size=25, home_building="A"))
    db.insert("student_groups", dict(name="G2", size=25, home_building="B"))
    db.insert("teachers", dict(name="T1", preferences=[{"kind": "building", "value": "B", "mode": "prefer", "weight": 10}]))
    db.insert("rooms", dict(name="A-1", building="A", capacity=30, kind="practice", equipment=["projector"]))
    db.insert("rooms", dict(name="B-1", building="B", capacity=30, kind="practice", equipment=[]))
    db.insert("rooms", dict(name="B-2", building="B", capacity=20, kind="practice", equipment=["projector"]))
    return db


def lesson(db, **kw):
    data = dict(subject="S", kind="practice", day=0, pair=1, week="all", required_equipment=[], group_ids=[1])
    data.update(kw)
    return db.save_lesson(data)


def run(db, mode="full"):
    res = solver.solve(db, mode, 5)
    solver.apply(db, res["changes"], "t")
    return res


def test_equipment_and_capacity_are_hard():
    db = make_db()
    lid = lesson(db, required_equipment=["projector"], group_ids=[1])
    run(db)
    # B-2 has a projector but only 20 seats, so A-1 is the only valid room
    assert db.lesson(lid)["room_id"] == 1


def test_no_double_booking_and_week_parity():
    db = make_db()
    a = lesson(db, week="odd")
    b = lesson(db, week="even")
    c = lesson(db, week="all", group_ids=[2])
    run(db)
    rooms = {i: db.lesson(i)["room_id"] for i in (a, b, c)}
    assert rooms[c] not in (rooms[a], rooms[b])
    assert not [x for x in find_conflicts(Snapshot(db)) if x["severity"] == "error"]


def test_teacher_preference_is_respected():
    db = make_db()
    lid = lesson(db, teacher_id=1, group_ids=[1])
    run(db)
    assert db.lesson(lid)["room_id"] in (2, 3)  # building B


def test_repair_moves_only_broken_lessons_and_undo():
    db = make_db()
    a = lesson(db, group_ids=[1], pair=1)
    b = lesson(db, group_ids=[2], pair=2)
    run(db)
    before_b = db.lesson(b)["room_id"]
    room_a = db.lesson(a)["room_id"]
    db.insert("room_blocks", dict(room_id=room_a, day=None, pair=None, reason="ремонт"))
    res = run(db, "repair")
    assert [c["lesson_id"] for c in res["changes"]] == [a]
    assert db.lesson(a)["room_id"] != room_a
    assert db.lesson(b)["room_id"] == before_b
    db.undo()
    assert db.lesson(a)["room_id"] == room_a


def test_locked_lesson_is_kept():
    db = make_db()
    lid = lesson(db, room_id=1, locked=True, teacher_id=1)
    run(db)
    assert db.lesson(lid)["room_id"] == 1


def test_unplaceable_lesson_is_explained():
    db = make_db()
    lesson(db, group_ids=[1, 2])  # 50 students, largest room has 30
    res = solver.solve(db, "full", 5)
    assert res["unassigned"] and "мало мест" in res["unassigned"][0]["reason"]


def test_demo_solves_and_excel_roundtrip():
    db = Database(":memory:")
    seed_demo(db)
    res = run(db)
    assert res["ok"] and not res["unassigned"]
    data = excel_io.export_data(db)
    db2 = Database(":memory:")
    counts = excel_io.import_data(db2, data)
    assert counts["lessons"] == len(db.lessons())
    assert [l["room_id"] is not None for l in db2.lessons()].count(True) == len(db.lessons())
    assert excel_io.export_schedule(db2)[:2] == b"PK"


def test_api_smoke():
    db = Database(":memory:")
    seed_demo(db)
    c = TestClient(create_app(db, static_dir=None))
    st = c.get("/api/state").json()
    lid = st["lessons"][0]["id"]
    assert c.get(f"/api/lessons/{lid}/suggest").status_code == 200
    grid = c.get(f"/api/lessons/{lid}/evaluate", params={"day": 0}).json()
    assert grid["cells"]
    res = c.post("/api/solve", json={"mode": "full", "time_limit": 5}).json()
    assert c.post("/api/apply", json={"changes": res["changes"]}).json()["changed"] == len(res["changes"])
    assert c.post(f"/api/lessons/{lid}/move", json={"pair": 6}).json()["changed"] == 1
    assert c.post("/api/undo").status_code == 200
    bad = c.post("/api/import", files={"file": ("x.xlsx", b"garbage")})
    assert bad.status_code == 422
