"""Room assignment with Google OR-Tools CP-SAT.

Two modes share one model:
  * "full"   — assign every unlocked lesson to the best room from scratch;
  * "repair" — keep valid assignments, moving a lesson costs `stability`, so only the
               lessons that are broken (closed room, clash, no room) get new rooms.
Locked lessons are never moved and occupy their rooms as constants."""
from __future__ import annotations

import time
from collections import Counter, defaultdict

from ortools.sat.python import cp_model

from .checker import Snapshot
from .db import Database

UNASSIGNED_COST = 100_000


def solve(db: Database, mode: str = "full", time_limit: float | None = None) -> dict:
    return solve_rooms(Snapshot(db), mode, time_limit)


def solve_rooms(snap: Snapshot, mode: str = "full", time_limit: float | None = None) -> dict:
    started = time.perf_counter()
    w = snap.weights
    time_limit = float(time_limit or snap.settings.get("time_limit", 20))

    model = cp_model.CpModel()
    x: dict[tuple[int, int], cp_model.IntVar] = {}
    unassigned: dict[int, cp_model.IntVar] = {}
    objective = []
    reasons: dict[int, str] = {}
    locked_room: dict[int, int] = {}
    # (room, day, pair) -> {"all"/"odd"/"even": [vars]} and locked counts
    buckets: dict[tuple, dict[str, list]] = defaultdict(lambda: {"all": [], "odd": [], "even": []})
    locked_load: dict[tuple, Counter] = defaultdict(Counter)

    for l in snap.lessons.values():
        key_tail = (l["day"], l["pair"])
        if l["locked"] and l["room_id"] in snap.rooms:
            locked_room[l["id"]] = l["room_id"]
            locked_load[(l["room_id"], *key_tail)][l["week"]] += 1
            continue
        candidates = []
        issue_counter: Counter = Counter()
        for room in snap.rooms.values():
            issues = snap.hard_issues(l, room)
            if issues:
                issue_counter.update(_bucket(i) for i in issues)
                continue
            candidates.append(room)
        if not candidates:
            common = ", ".join(f"{k} ({v})" for k, v in issue_counter.most_common(3))
            reasons[l["id"]] = f"ни одна аудитория не подходит: {common}" if common else "нет аудиторий"
        u = model.NewBoolVar(f"u{l['id']}")
        unassigned[l["id"]] = u
        objective.append(UNASSIGNED_COST * u)
        lvars = []
        for room in candidates:
            v = model.NewBoolVar(f"x{l['id']}_{room['id']}")
            x[(l["id"], room["id"])] = v
            lvars.append(v)
            cost, _, _ = snap.soft_cost(l, room)
            if mode == "repair" and l["room_id"] and room["id"] != l["room_id"]:
                cost += w["stability"]
            if cost:
                objective.append(cost * v)
            buckets[(room["id"], *key_tail)][l["week"]].append(v)
            if room["id"] == l["room_id"]:
                model.AddHint(v, 1)
        model.Add(sum(lvars) + u == 1)

    # one room — one lesson per slot, respecting odd/even weeks
    for key, weeks in buckets.items():
        load = locked_load.get(key, Counter())
        for half in ("odd", "even"):
            free = 1 - load["all"] - load[half]
            model.Add(sum(weeks["all"]) + sum(weeks[half]) <= max(0, free))

    # building changes between consecutive pairs of a group or teacher
    if w["move"] and len({r["building"] for r in snap.rooms.values()}) > 1:
        by_lesson: dict[int, dict[str, list]] = {}
        per_lesson_vars: dict[int, list] = defaultdict(list)
        for (l_id, r_id), v in x.items():
            per_lesson_vars[l_id].append((r_id, v))

        def expr(lid):
            if lid not in by_lesson:
                if lid in locked_room:
                    by_lesson[lid] = {snap.rooms[locked_room[lid]]["building"]: [1]}
                else:
                    d: dict[str, list] = defaultdict(list)
                    for r_id, v in per_lesson_vars.get(lid, ()):
                        d[snap.rooms[r_id]["building"]].append(v)
                    by_lesson[lid] = d
            return by_lesson[lid]

        for a, b in snap.consecutive_pairs():
            ea, eb = expr(a), expr(b)
            if not ea or not eb or (a in locked_room and b in locked_room):
                continue
            m = model.NewBoolVar(f"m{a}_{b}")
            for bld in set(ea) | set(eb):
                model.Add(m >= sum(ea.get(bld, [])) - sum(eb.get(bld, [])))
            objective.append(w["move"] * m)

    model.Minimize(sum(objective))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_workers = 8
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {
            "ok": False,
            "status": solver.StatusName(status),
            "message": "Солвер не нашёл решения за отведённое время. Увеличьте лимит в настройках.",
            "changes": [],
            "unassigned": [],
            "seconds": round(time.perf_counter() - started, 2),
        }

    chosen: dict[int, int | None] = {lid: None for lid in unassigned}
    for (lid, rid), v in x.items():
        if solver.Value(v):
            chosen[lid] = rid

    changes = []
    unplaced = []
    for lid, rid in chosen.items():
        l = snap.lessons[lid]
        if rid is None:
            unplaced.append(
                {
                    "lesson_id": lid,
                    "label": snap.label(l),
                    "reason": reasons.get(lid, "все подходящие аудитории заняты в это время"),
                }
            )
        if rid != l["room_id"]:
            old = snap.rooms.get(l["room_id"])
            new = snap.rooms.get(rid)
            changes.append(
                {
                    "lesson_id": lid,
                    "label": snap.label(l),
                    "day": l["day"],
                    "pair": l["pair"],
                    "to_day": l["day"],
                    "to_pair": l["pair"],
                    "from_room_id": l["room_id"],
                    "from": old["name"] if old else None,
                    "to_room_id": rid,
                    "to": new["name"] if new else None,
                }
            )
    changes.sort(key=lambda c: (c["day"], c["pair"], c["label"]))
    return {
        "ok": True,
        "status": solver.StatusName(status),
        "optimal": status == cp_model.OPTIMAL,
        "objective": int(solver.ObjectiveValue()),
        "changes": changes,
        "unassigned": unplaced,
        "lessons": len(snap.lessons),
        "seconds": round(time.perf_counter() - started, 2),
    }


def apply(db: Database, changes: list[dict], description: str) -> int:
    rooms = {r["id"] for r in db.all("rooms")}
    payload = {}
    for c in changes:
        item = {"room_id": c.get("to_room_id") if c.get("to_room_id") in rooms else None}
        if c.get("to_day") is not None and c.get("to_pair") is not None:
            item["day"], item["pair"] = int(c["to_day"]), int(c["to_pair"])
        payload[int(c["lesson_id"])] = item
    return db.apply_changes(description, payload)


def _bucket(issue: str) -> str:
    if issue.startswith("мест"):
        return "мало мест"
    if issue.startswith("ПК"):
        return "мало ПК"
    if issue.startswith("закрыта"):
        return "закрыта"
    return issue
