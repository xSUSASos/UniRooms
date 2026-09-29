import json

import pytest

from app import assistant
from app.checker import Snapshot
from app.db import Database
from app.seed import seed_demo


@pytest.fixture()
def db(monkeypatch):
    monkeypatch.setattr(assistant, "status", lambda settings: {"available": False, "models": [], "model": None, "url": ""})
    d = Database(":memory:")
    seed_demo(d)
    return d


def test_parse_day_and_pair():
    assert assistant.parse_day("закрой в среду") == 2
    assert assistant.parse_day("пт, 2 пара") == 4
    assert assistant.parse_pair("на третьей паре") == 3
    assert assistant.parse_pair("3-я пара") == 3
    assert assistant.parse_pair("пара 5") == 5


def test_fuzzy_names():
    rooms = {1: "А-202", 2: "Б-202", 3: "А-101"}
    assert assistant.fuzzy("a202", rooms) == [1]  # latin letter typed
    assert sorted(assistant.fuzzy("202", rooms)) == [1, 2]  # ambiguous
    teachers = {1: "Петрова А. С.", 2: "Иванов И. И."}
    assert assistant.fuzzy("Петровой", teachers) == [1]


def test_rule_based_block_room_executes(db):
    plan = assistant.interpret(db, "Закрой А-202 в среду на 3 паре, ремонт")
    assert plan["ok"] and not plan["llm"]
    act = plan["action"]
    assert (act["action"], act["day"], act["pair"], act["reason"]) == ("block_room", 2, 3, "ремонт")
    assistant.execute(db, act)
    snap = Snapshot(db)
    assert snap.blocked(act["room_id"], 2, 3) == "ремонт"


def test_solve_commands(db):
    assert assistant.interpret(db, "убери накладки")["action"]["solve_mode"] == "time-repair"
    assert assistant.interpret(db, "распредели аудитории")["action"]["solve_mode"] == "full"


def test_unknown_command_explains_how_to_enable_llm(db):
    plan = assistant.interpret(db, "сделай красиво")
    assert not plan["ok"] and "Ollama" in plan["message"]


def test_resolve_preferences_and_unavailability(db):
    snap = Snapshot(db)
    plan = assistant.resolve(snap, {"action": "add_preference", "teacher": "Петрова", "pref_kind": "building",
                                    "pref_value": "в", "pref_mode": "avoid", "weight": 7})
    assert plan["ok"], plan
    assistant.execute(db, plan["action"])
    t = db.get("teachers", plan["action"]["teacher_id"])
    assert {"kind": "building", "value": "В", "mode": "avoid", "weight": 7} in t["preferences"]

    plan = assistant.resolve(snap, {"action": "set_unavailable", "teacher": "Сидоров", "day": 4})
    assistant.execute(db, plan["action"])
    t = db.get("teachers", plan["action"]["teacher_id"])
    assert [4, 1] in t["unavailable"] and [4, 6] in t["unavailable"]


def test_move_lesson_needs_unique_match(db):
    snap = Snapshot(db)
    many = assistant.resolve(snap, {"action": "move_lesson", "subject": "Иностранный язык", "to_day": 3})
    assert not many["ok"] and "несколько" in many["message"]
    l = next(l for l in snap.lessons.values() if l["subject"] == "Химия")
    group = snap.groups[l["group_ids"][0]]["name"]
    plan = assistant.resolve(snap, {"action": "move_lesson", "subject": "химия", "group": group, "to_pair": 6})
    assert plan["ok"], plan
    assistant.execute(db, plan["action"])
    assert db.lesson(l["id"])["pair"] == 6


def test_llm_path_is_used_when_available(db, monkeypatch):
    monkeypatch.setattr(assistant, "status", lambda s: {"available": True, "models": ["m"], "model": "m", "url": "x"})
    calls = []

    def fake_chat(settings, messages, fmt=None, timeout=0):
        calls.append(fmt)
        return json.dumps({"action": "block_room", "room": "Б-101", "reason": "мероприятие"})

    monkeypatch.setattr(assistant, "chat", fake_chat)
    plan = assistant.interpret(db, "в Б-101 сегодня мероприятие, закрой её")
    assert plan["ok"] and plan["llm"] and calls[0] == assistant.SCHEMA
    assert plan["action"]["room_id"] == next(r["id"] for r in db.all("rooms") if r["name"] == "Б-101")


def test_explain_falls_back_to_facts_without_llm(db):
    lid = db.lessons()[0]["id"]
    text = assistant.explain(db, lid)
    assert "Занятие:" in text
