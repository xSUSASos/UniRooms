"""Deterministic demo data: 3 buildings, ~30 rooms, 16 teachers, 12 groups, ~150 lessons."""
from __future__ import annotations

import random

from .db import Database

BUILDINGS = ["А", "Б", "В"]

TEACHERS = [
    ("Иванов И. И.", "Высшая математика"),
    ("Петрова А. С.", "Высшая математика"),
    ("Сидоров П. К.", "Информатика"),
    ("Кузнецова Е. В.", "Информатика"),
    ("Смирнов Д. А.", "Программирование"),
    ("Волкова Н. Г.", "Программирование"),
    ("Морозов С. Н.", "Физика"),
    ("Лебедева О. П.", "Физика"),
    ("Козлов А. В.", "Химия"),
    ("Новикова Т. М.", "Иностранные языки"),
    ("Соколов В. Р.", "Иностранные языки"),
    ("Попова Ю. Д.", "История"),
    ("Фёдоров М. И.", "Экономика"),
    ("Егорова Л. А.", "Философия"),
    ("Николаев Г. Е.", "Базы данных"),
    ("Орлова И. Б.", "Сети"),
]

# subject, lesson kind, teacher indices, required equipment, min computers, lessons per week
SUBJECTS = [
    ("Математический анализ", "lecture", [0, 1], ["projector"], 0, 1),
    ("Математический анализ", "practice", [0, 1], ["chalkboard"], 0, 1),
    ("Информатика", "lab", [2, 3], [], 12, 1),
    ("Программирование", "lecture", [4, 5], ["projector"], 0, 1),
    ("Программирование", "lab", [4, 5], [], 12, 1),
    ("Физика", "lecture", [6, 7], ["projector"], 0, 1),
    ("Физика", "lab", [6, 7], ["lab_bench"], 0, 1),
    ("Химия", "lab", [8], ["lab_bench"], 0, 1),
    ("Иностранный язык", "practice", [9, 10], ["whiteboard"], 0, 2),
    ("История", "lecture", [11], ["projector"], 0, 1),
    ("Экономика", "practice", [12], [], 0, 1),
    ("Философия", "lecture", [13], [], 0, 1),
    ("Базы данных", "lab", [14], [], 12, 1),
    ("Компьютерные сети", "lab", [15], [], 12, 1),
]


def seed_demo(db: Database) -> dict:
    rnd = random.Random(42)
    db.clear()

    with db.tx() as c:
        rooms = []
        for b_idx, b in enumerate(BUILDINGS):
            # big lecture halls
            rooms.append(dict(name=f"{b}-101", building=b, floor=1, capacity=120, kind="lecture",
                              equipment=["projector", "sound", "chalkboard"], accessible=True))
            rooms.append(dict(name=f"{b}-102", building=b, floor=1, capacity=80, kind="lecture",
                              equipment=["projector", "whiteboard"], accessible=True))
            for n in range(201, 206):
                eq = rnd.sample(["chalkboard", "whiteboard", "smartboard", "projector"], k=rnd.randint(1, 3))
                rooms.append(dict(name=f"{b}-{n}", building=b, floor=2, capacity=rnd.choice([25, 30, 30, 35, 40]),
                                  kind="practice", equipment=eq, accessible=False))
            for n in range(301, 304):
                rooms.append(dict(name=f"{b}-{n}", building=b, floor=3, capacity=rnd.choice([28, 30, 32]),
                                  kind="computer", computers=rnd.choice([15, 20, 30]),
                                  equipment=["projector", "whiteboard"], accessible=False))
            if b_idx < 2:
                rooms.append(dict(name=f"{b}-310", building=b, floor=3, capacity=30, kind="lab",
                                  equipment=["lab_bench", "chalkboard"], accessible=False))
        room_ids = [db.insert("rooms", r, conn=c) for r in rooms]

        teacher_ids = []
        for i, (name, dept) in enumerate(TEACHERS):
            prefs = []
            if i % 3 == 0:
                prefs.append({"kind": "building", "value": BUILDINGS[i % 3], "mode": "prefer", "weight": 6})
            if i % 4 == 1:
                prefs.append({"kind": "equipment", "value": "smartboard", "mode": "prefer", "weight": 4})
            if i % 5 == 2:
                prefs.append({"kind": "max_floor", "value": 2, "mode": "prefer", "weight": 5})
            if i % 7 == 3:
                prefs.append({"kind": "building", "value": "В", "mode": "avoid", "weight": 8})
            teacher_ids.append(db.insert("teachers", dict(
                name=name, department=dept, needs_accessible=(i == 11),
                unavailable=[[5, p] for p in range(1, 7)] if i % 2 else [], preferences=prefs), conn=c))

        groups = []
        for course in (1, 2, 3):
            for spec, home in (("ИВТ", "А"), ("ПИ", "Б"), ("ЭК", "В"), ("ФИЗ", "Б")):
                groups.append(dict(name=f"{spec}-{course}1", course=course, size=rnd.randint(18, 28), home_building=home))
        group_ids = [db.insert("student_groups", g, conn=c) for g in groups]

    # lessons: place per course, lectures shared by the whole course (stream)
    busy_t: set[tuple] = set()
    busy_g: set[tuple] = set()
    slots = [(d, p) for d in range(5) for p in range(1, 6)]
    count = 0
    for course in (1, 2, 3):
        cgroups = group_ids[(course - 1) * 4: course * 4]
        for subject, kind, t_opts, eq, pcs, per_week in SUBJECTS:
            if (course == 1 and subject in ("Базы данных", "Компьютерные сети")) or \
               (course == 3 and subject in ("Физика", "Химия", "История")):
                continue
            units = [cgroups] if kind == "lecture" else [[g] for g in cgroups]
            for gs in units:
                for rep in range(per_week):
                    teacher = teacher_ids[rnd.choice(t_opts)]
                    week = "all" if rep == 0 or rnd.random() < 0.5 else rnd.choice(["odd", "even"])
                    rnd.shuffle(slots)
                    for d, p in slots:
                        if (teacher, d, p) in busy_t or any((g, d, p) in busy_g for g in gs):
                            continue
                        busy_t.add((teacher, d, p))
                        busy_g.update((g, d, p) for g in gs)
                        db.save_lesson(dict(subject=subject, kind=kind, teacher_id=teacher, day=d, pair=p,
                                            week=week, required_equipment=eq, min_computers=pcs,
                                            group_ids=list(gs)))
                        count += 1
                        break
    # one closed room to demonstrate blocks
    db.insert("room_blocks", dict(room_id=room_ids[3], day=None, pair=None, reason="ремонт"))
    return {"rooms": len(room_ids), "teachers": len(teacher_ids), "groups": len(group_ids), "lessons": count}
