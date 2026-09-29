"""Automatic time scheduling: CP-SAT picks (day, pair) for lessons, then rooms are assigned.

Phase 1 — time. Hard: no teacher/group clashes (odd/even weeks aware), teacher availability,
max pairs per day for a group, and a room-capacity relaxation: for every distinct set S of
suitable rooms, the lessons that fit *only* into S cannot outnumber the open rooms of S in a slot.
Soft: windows in the day of groups and teachers, late pairs, teachers' day/pair wishes,
the same subject twice a day, and moving away from the current time.

Phase 2 — rooms. The regular room solver in "repair" mode runs on the moved schedule, so
lessons keep their rooms whenever those are still free and suitable.

Modes: "repair" moves only lessons involved in clashes (and as few of them as possible),
       "full" rebuilds the time of every lesson that is not locked / time-fixed — optionally
       only for one faculty, which keeps a whole university tractable."""
from __future__ import annotations

import time
from collections import Counter, defaultdict
from itertools import combinations

from ortools.sat.python import cp_model

from .checker import Snapshot, find_conflicts, is_shared, weeks_overlap
from .db import Database
from .solver import CandidateFinder, solve_rooms

UNPLACED_COST = 1_000_000
HALVES = ("odd", "even")
FULL_LIMIT = 6000  # lessons that "full" mode may move at once
PEOPLE_CONFLICTS = {"teacher", "group", "overload", "slot"}


def solve_timetable(db: Database, mode: str = "repair", time_limit: float | None = None,
                    faculty: str | None = None) -> dict:
    started = time.perf_counter()
    snap = Snapshot(db)
    w = snap.weights
    total_limit = float(time_limit or snap.settings.get("time_limit", 20))
    days = range(int(snap.settings.get("days", 6)))
    pairs = snap.pairs
    slots = [(d, p) for d in days for p in pairs]
    late_pair = 5

    lessons = list(snap.lessons.values())
    can_move = [l for l in lessons if not l["locked"] and not l["fixed_time"]]
    if mode == "repair":
        involved = {lid for c in find_conflicts(snap) if c["kind"] in PEOPLE_CONFLICTS for lid in c["lesson_ids"]}
        # lessons that cannot get a room at their current time have to move as well
        involved |= {u["lesson_id"] for u in solve_rooms(snap, "repair", total_limit * 0.3)["unassigned"]}
        movable = [l for l in can_move if l["id"] in involved]
    else:
        if faculty:
            movable = [l for l in can_move if l["group_ids"]
                       and all((snap.groups.get(g) or {}).get("faculty") == faculty for g in l["group_ids"])]
        else:
            movable = can_move
        if len(movable) > FULL_LIMIT:
            return {"ok": False, "status": "TOO_BIG", "changes": [], "unassigned": [],
                    "message": f"Слишком много занятий для составления заново ({len(movable)}). "
                               f"Выберите факультет — время составится только для его групп.",
                    "seconds": 0}
    if not movable:
        return {"ok": True, "status": "OPTIMAL", "optimal": True, "changes": [], "moved_in_time": 0,
                "unassigned": [], "lessons": len(lessons), "seconds": round(time.perf_counter() - started, 2)}
    movable_ids = {l["id"] for l in movable}

    finder = CandidateFinder(snap)
    cand = {l["id"]: frozenset() if l["online"] or is_shared(snap.rooms.get(l["room_id"])) else finder.static_ids(l)
            for l in movable}

    model = cp_model.CpModel()
    y: dict[tuple[int, int, int], cp_model.IntVar] = {}
    unplaced: dict[int, cp_model.IntVar] = {}
    objective: list = []

    for l in movable:
        t = snap.teacher(l)
        banned = {tuple(s) for s in t["unavailable"]} if t else set()
        current = (l["day"], l["pair"])
        lvars = []
        for d, p in slots:
            if (d, p) in banned:
                continue
            v = model.NewBoolVar(f"y{l['id']}_{d}_{p}")
            y[(l["id"], d, p)] = v
            lvars.append(v)
            cost = 0
            if (d, p) != current:
                cost += w["time_stability"] if mode == "repair" else 1
            if p >= late_pair or d == 5:
                cost += w["late"]
            if t:
                cost += _time_pref_cost(t, d, p, w["preference"])
            if cost:
                objective.append(cost * v)
            if (d, p) == current:
                model.AddHint(v, 1)
        u = model.NewBoolVar(f"u{l['id']}")
        unplaced[l["id"]] = u
        objective.append(UNPLACED_COST * u)
        model.Add(sum(lvars) + u == 1)

    def at(l: dict, d: int, p: int):
        """1 if lesson l is at (d, p): a model variable for movable lessons, a constant otherwise."""
        if l["id"] in movable_ids:
            return y.get((l["id"], d, p), 0)
        return 1 if (l["day"], l["pair"]) == (d, p) else 0

    def halves(items: list[dict], d: int, p: int, half: str) -> list:
        return [at(l, d, p) for l in items if l["week"] in ("all", half)]

    # ---- people: no clashes, day limits, windows (only owners that have something movable) ----
    by_teacher: dict[int, list[dict]] = defaultdict(list)
    by_group: dict[int, list[dict]] = defaultdict(list)
    for l in lessons:
        if l["teacher_id"]:
            by_teacher[l["teacher_id"]].append(l)
        for g in l["group_ids"]:
            by_group[g].append(l)
    touched_teachers = {l["teacher_id"] for l in movable if l["teacher_id"]}
    touched_groups = {g for l in movable for g in l["group_ids"]}

    limit = int(snap.settings.get("max_per_day") or 0)
    for owner_kind, index, owners, gap_weight in (
        ("t", by_teacher, touched_teachers, w["teacher_gap"]),
        ("g", by_group, touched_groups, w["gap"]),
    ):
        for owner in owners:
            items = index[owner]
            for d in days:
                busy_prev = 0
                for p in pairs:
                    for half in HALVES:
                        terms = halves(items, d, p, half)
                        if len(terms) > 1:
                            _at_most(model, terms, 1)
                    anyone = [at(l, d, p) for l in items]
                    if gap_weight and any(not isinstance(t, int) for t in anyone):
                        busy = model.NewBoolVar(f"b{owner_kind}{owner}_{d}_{p}")
                        for term in anyone:
                            model.Add(busy >= term)
                        model.Add(busy <= sum(anyone))
                        start = model.NewBoolVar(f"s{owner_kind}{owner}_{d}_{p}")
                        model.Add(start >= busy - busy_prev)
                        objective.append(gap_weight * start)
                        busy_prev = busy
                    else:
                        busy_prev = 1 if any(isinstance(t, int) and t for t in anyone) else 0
                if owner_kind == "g" and limit:
                    for half in HALVES:
                        terms = [t for p in pairs for t in halves(items, d, p, half)]
                        if any(not isinstance(t, int) for t in terms):
                            _at_most(model, terms, limit)

    # ---- rooms: capacity relaxation per set of suitable rooms ----
    staying = [l for l in lessons if l["id"] not in movable_ids and not l["online"]]
    for sig in {c for c in cand.values() if c}:
        members = [l for l in movable if cand[l["id"]] and cand[l["id"]] <= sig]
        occupied: Counter = Counter()  # fixed lessons already sitting in rooms of this set
        for l in staying:
            # a staying lesson occupies its room, or — without a valid room yet — one of the rooms it fits
            fits = finder.static_ids(l)
            if l["room_id"] in sig if l["room_id"] in snap.rooms else bool(fits) and fits <= sig:
                for half in HALVES:
                    if l["week"] in ("all", half):
                        occupied[(l["day"], l["pair"], half)] += 1
        for d, p in slots:
            open_rooms = sum(1 for r in sig if not snap.blocked(r, d, p))
            for half in HALVES:
                terms = [v for l in members if l["week"] in ("all", half) and (v := y.get((l["id"], d, p))) is not None]
                room_left = open_rooms - occupied[(d, p, half)]
                if len(terms) > room_left:
                    model.Add(sum(terms) <= max(0, room_left))

    # ---- the same subject for the same groups twice a day ----
    if w["spread"]:
        same: dict[tuple, list[dict]] = defaultdict(list)
        for l in lessons:
            same[(l["subject"], l["kind"], tuple(l["group_ids"]))].append(l)
        for items in same.values():
            if len(items) < 2 or not any(l["id"] in movable_ids for l in items):
                continue
            for a, b in combinations(items, 2):
                if a["id"] not in movable_ids and b["id"] not in movable_ids:
                    continue
                if not weeks_overlap(a["week"], b["week"]):
                    continue
                for d in days:
                    da = sum(at(a, d, p) for p in pairs)
                    db_ = sum(at(b, d, p) for p in pairs)
                    if isinstance(da, int) and isinstance(db_, int):
                        continue
                    z = model.NewBoolVar(f"z{a['id']}_{b['id']}_{d}")
                    model.Add(z >= da + db_ - 1)
                    objective.append(w["spread"] * z)

    model.Minimize(sum(objective))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(1.0, total_limit * 0.7)
    solver.parameters.num_workers = 8
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "ok": False,
            "status": solver.StatusName(status),
            "message": "Не удалось составить время за отведённый срок. Увеличьте лимит времени в настройках.",
            "changes": [],
            "unassigned": [],
            "seconds": round(time.perf_counter() - started, 2),
        }

    new_times: dict[int, tuple[int, int]] = {}
    not_placed = []
    for l in movable:
        if solver.Value(unplaced[l["id"]]):
            not_placed.append({"lesson_id": l["id"], "label": snap.label(l),
                               "reason": "не нашлось времени без накладок (преподаватель, группы или аудитории заняты)"})
            continue
        for d, p in slots:
            v = y.get((l["id"], d, p))
            if v is not None and solver.Value(v) and (d, p) != (l["day"], l["pair"]):
                new_times[l["id"]] = (d, p)

    # ---- phase 2: rooms on the moved schedule ----
    remaining = max(3.0, total_limit - (time.perf_counter() - started))
    rooms = solve_rooms(snap.with_times(new_times), "repair", remaining)
    room_changes = {c["lesson_id"]: c for c in rooms.get("changes", [])}

    changes = []
    for lid in sorted(set(new_times) | set(room_changes)):
        l = snap.lessons[lid]
        to_day, to_pair = new_times.get(lid, (l["day"], l["pair"]))
        rc = room_changes.get(lid)
        to_room = rc["to_room_id"] if rc else l["room_id"]
        old, new = snap.rooms.get(l["room_id"]), snap.rooms.get(to_room)
        changes.append({
            "lesson_id": lid,
            "label": snap.label(l),
            "day": l["day"],
            "pair": l["pair"],
            "to_day": to_day,
            "to_pair": to_pair,
            "from_room_id": l["room_id"],
            "from": old["name"] if old else None,
            "to_room_id": to_room,
            "to": new["name"] if new else None,
        })
    changes.sort(key=lambda c: (c["to_day"], c["to_pair"], c["label"]))
    return {
        "ok": True,
        "status": solver.StatusName(status),
        "optimal": status == cp_model.OPTIMAL and rooms.get("optimal", False),
        "changes": changes,
        "moved_in_time": len(new_times),
        "considered": len(movable),
        "unassigned": not_placed + rooms.get("unassigned", []),
        "lessons": len(lessons),
        "seconds": round(time.perf_counter() - started, 2),
    }


def _at_most(model: cp_model.CpModel, terms: list, bound: int) -> None:
    constant = sum(t for t in terms if isinstance(t, int))
    variables = [t for t in terms if not isinstance(t, int)]
    if variables:
        model.Add(sum(variables) <= max(0, bound - constant))


def _time_pref_cost(teacher: dict, day: int, pair: int, unit: int) -> int:
    cost = 0
    for p in teacher["preferences"]:
        kind = p.get("kind")
        if kind not in ("day", "pair"):
            continue
        try:
            value = int(p.get("value"))
        except (TypeError, ValueError):
            continue
        hit = (day if kind == "day" else pair) == value
        wanted = p.get("mode", "prefer") == "prefer"
        if hit != wanted:
            cost += unit * int(p.get("weight", 5))
    return cost
