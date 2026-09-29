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

from .checker import Snapshot, is_shared
from .db import Database

UNASSIGNED_COST = 100_000


def solve(db: Database, mode: str = "full", time_limit: float | None = None) -> dict:
    return solve_rooms(Snapshot(db), mode, time_limit)


MAX_CANDIDATES = 30  # best rooms per lesson kept in the model
POOL = 90  # rooms scored per lesson before keeping the best ones


def solve_rooms(snap: Snapshot, mode: str = "full", time_limit: float | None = None) -> dict:
    """Assign rooms. Days are independent (clashes and building moves happen within a day),
    so every day is solved as its own model — this keeps a whole university tractable."""
    started = time.perf_counter()
    time_limit = float(time_limit or snap.settings.get("time_limit", 20))
    lessons = list(snap.lessons.values())

    if mode == "repair":
        broken = problem_lessons(snap)
        free = [l for l in lessons if l["id"] in broken]
    else:
        free = [l for l in lessons if not l["online"] and not is_shared(snap.rooms.get(l["room_id"]))
                and not (l["locked"] and l["room_id"] in snap.rooms)]
    free_ids = {l["id"] for l in free}
    by_day: dict[int, list[dict]] = defaultdict(list)
    for l in free:
        by_day[l["day"]].append(l)
    neighbours = snap.consecutive_pairs() if free else []

    finder = CandidateFinder(snap)
    chosen: dict[int, int | None] = {}
    reasons: dict[int, str] = {}
    statuses = []
    for day in sorted(by_day):
        day_free = by_day[day]
        day_fixed = [l for l in lessons if l["day"] == day and l["id"] not in free_ids and not l["online"]
                     and l["room_id"] in snap.rooms]
        day_pairs = [(a, b) for a, b in neighbours if snap.lessons[a]["day"] == day]
        budget = max(3.0, time_limit * len(day_free) / max(1, len(free)))
        status, day_chosen, day_reasons = _solve_day(snap, finder, day_free, day_fixed, day_pairs, mode, budget)
        statuses.append(status)
        if day_chosen is None:  # no solution for this day — keep what is there
            continue
        chosen.update(day_chosen)
        reasons.update(day_reasons)

    solved = [s for s in statuses if s in (cp_model.OPTIMAL, cp_model.FEASIBLE)]
    if statuses and not solved:
        return {
            "ok": False,
            "status": cp_model.CpSolver().StatusName(statuses[0]),
            "message": "Солвер не нашёл решения за отведённое время. Увеличьте лимит в настройках.",
            "changes": [],
            "unassigned": [],
            "seconds": round(time.perf_counter() - started, 2),
        }

    if mode == "full" and chosen:
        # clean up what the big model left behind (unplaced lessons, pairs that ran out of time)
        # with a focused repair pass on top of the new assignment
        remaining = max(3.0, time_limit - (time.perf_counter() - started))
        fix = solve_rooms(snap.with_rooms(chosen), "repair", remaining)
        if fix.get("ok"):
            for c in fix["changes"]:
                chosen[c["lesson_id"]] = c["to_room_id"]
            reasons.update({u["lesson_id"]: u["reason"] for u in fix["unassigned"]})
        # never worse than before: a lesson left without a room goes back to its old one if that is still free
        occ = snap.with_rooms(chosen).busy()
        for lid, rid in list(chosen.items()):
            l = snap.lessons[lid]
            old = snap.rooms.get(l["room_id"])
            if rid is None and old and not snap.hard_issues(l, old) \
                    and not occ.room_clash(l, old["id"], l["day"], l["pair"]):
                chosen[lid] = old["id"]
                occ = snap.with_rooms(chosen).busy()

    changes = []
    unplaced = []
    for lid, rid in chosen.items():
        l = snap.lessons[lid]
        if rid is None:
            unplaced.append({"lesson_id": lid, "label": snap.label(l),
                             "reason": reasons.get(lid, "все подходящие аудитории заняты в это время")})
        if rid != l["room_id"]:
            old, new = snap.rooms.get(l["room_id"]), snap.rooms.get(rid)
            changes.append({
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
            })
    changes.sort(key=lambda c: (c["day"], c["pair"], c["label"]))
    optimal = bool(statuses) and all(s == cp_model.OPTIMAL for s in statuses)
    return {
        "ok": True,
        "status": "OPTIMAL" if optimal or not statuses else "FEASIBLE",
        "optimal": optimal or not statuses,
        "changes": changes,
        "unassigned": unplaced,
        "lessons": len(snap.lessons),
        "considered": len(free),
        "seconds": round(time.perf_counter() - started, 2),
    }


def problem_lessons(snap: Snapshot) -> set[int]:
    """Lessons that lack a room, sit in an unsuitable room or share a room with another lesson.
    Only these move in "repair" mode; everything else keeps its room."""
    ids = set()
    occ = snap.busy()
    for l in snap.lessons.values():
        if l["locked"] or l["online"]:
            continue
        room = snap.rooms.get(l["room_id"])
        if room is None or snap.hard_issues(l, room):
            ids.add(l["id"])
            continue
        clash = occ.room_clash(l, room["id"], l["day"], l["pair"])
        if clash and not all(o["locked"] for o in clash):
            ids.add(l["id"])
    return ids


class CandidateFinder:
    """Suitable rooms for a lesson, cheapest first. Static checks are cached per lesson signature."""

    def __init__(self, snap: Snapshot):
        self.snap = snap
        # shared venues are never offered to other lessons
        self.rooms = sorted((r for r in snap.rooms.values() if r["active"] and not is_shared(r)),
                            key=lambda r: (r["capacity"], r["name"]))
        self._cache: dict[tuple, list[dict]] = {}
        self._ids: dict[tuple, frozenset] = {}

    def _key(self, l: dict) -> tuple:
        t = self.snap.teacher(l)
        return (self.snap.size(l), tuple(sorted(l["required_equipment"])), l["min_computers"],
                bool(t and t["needs_accessible"]))

    def static_ids(self, l: dict) -> frozenset:
        key = self._key(l)
        if key not in self._ids:
            self._ids[key] = frozenset(r["id"] for r in self.static(l))
        return self._ids[key]

    def static(self, l: dict) -> list[dict]:
        key = self._key(l)
        size, _, _, access = key
        if key not in self._cache:
            req = set(l["required_equipment"])
            self._cache[key] = [
                r for r in self.rooms
                if r["capacity"] >= size and r["computers"] >= l["min_computers"] and req <= set(r["equipment"])
                and (not access or r["accessible"])
            ]
        return self._cache[key]

    def find(self, l: dict, mode: str) -> tuple[list[tuple[dict, int]], str | None]:
        snap = self.snap
        suitable = [r for r in self.static(l) if not snap.blocked(r["id"], l["day"], l["pair"])]
        if not suitable:
            issues: Counter = Counter()
            for room in snap.rooms.values():
                issues.update(_bucket(i) for i in snap.hard_issues(l, room))
            common = ", ".join(f"{k} ({v})" for k, v in issues.most_common(3))
            return [], f"ни одна аудитория не подходит: {common}" if common else "нет аудиторий"
        current = snap.rooms.get(l["room_id"])
        current_ok = current is not None and any(r["id"] == current["id"] for r in suitable)
        pool = suitable[:POOL]  # the smallest rooms that fit — fewest empty seats
        rest = suitable[POOL:]
        extra = [r for r in rest if current and r["building"] == current["building"]][: POOL // 3]
        extra += [r for r in rest if _preferred(snap, l, r)][: POOL // 3]
        seen = set()
        scored = []
        for room in pool + extra + ([current] if current_ok else []):
            if room["id"] in seen:
                continue
            seen.add(room["id"])
            cost, _, _ = snap.soft_cost(l, room)
            if mode == "repair" and l["room_id"] and room["id"] != l["room_id"]:
                cost += snap.weights["stability"]
            scored.append((room, cost))
        scored.sort(key=lambda rc: rc[1])
        keep = scored[:MAX_CANDIDATES]
        if current_ok and all(r["id"] != current["id"] for r, _ in keep):
            keep.append(next(rc for rc in scored if rc[0]["id"] == current["id"]))
        return keep, None


def _preferred(snap: Snapshot, l: dict, room: dict) -> bool:
    t = snap.teacher(l)
    if t:
        for p in t["preferences"]:
            if p.get("mode", "prefer") == "prefer" and p.get("kind") in ("room", "building"):
                if (room["name"] if p["kind"] == "room" else room["building"]) == p.get("value"):
                    return True
    return any((snap.groups.get(g) or {}).get("home_building") == room["building"] for g in l["group_ids"])


SPLIT_BY_PAIR = 1200  # a day with more lessons to place is solved pair by pair


def _solve_day(snap: Snapshot, finder: CandidateFinder, free: list[dict], fixed: list[dict],
               neighbours: list[tuple[int, int]], mode: str, time_limit: float):
    if len(free) > SPLIT_BY_PAIR and len({l["pair"] for l in free}) > 1:
        # pair by pair, in order: rooms of earlier pairs are known, so building moves are still counted
        pair_list = sorted({l["pair"] for l in free})
        chosen: dict[int, int | None] = {}
        reasons: dict[int, str] = {}
        statuses = []
        placed = list(fixed)
        for p in pair_list:
            part = [l for l in free if l["pair"] == p]
            budget = max(2.0, time_limit * len(part) / len(free))
            status, part_chosen, part_reasons = _solve_day(snap, finder, part, placed, neighbours, mode, budget)
            statuses.append(status)
            if part_chosen is None:
                part_chosen = {l["id"]: l["room_id"] for l in part}
            chosen.update(part_chosen)
            reasons.update(part_reasons)
            placed += [dict(l, room_id=part_chosen[l["id"]]) for l in part if part_chosen.get(l["id"]) in snap.rooms]
        worst = cp_model.OPTIMAL if all(s == cp_model.OPTIMAL for s in statuses) else cp_model.FEASIBLE
        return worst, chosen, reasons

    w = snap.weights
    model = cp_model.CpModel()
    x: dict[tuple[int, int], cp_model.IntVar] = {}
    unassigned: dict[int, cp_model.IntVar] = {}
    objective = []
    reasons: dict[int, str] = {}
    fixed_room = {l["id"]: l["room_id"] for l in fixed}
    buckets: dict[tuple, dict[str, list]] = defaultdict(lambda: {"all": [], "odd": [], "even": []})
    fixed_load: dict[tuple, Counter] = defaultdict(Counter)
    for l in fixed:
        if not is_shared(snap.rooms.get(l["room_id"])):
            fixed_load[(l["room_id"], l["pair"])][l["week"]] += 1

    for l in free:
        candidates, reason = finder.find(l, mode)
        if reason:
            reasons[l["id"]] = reason
        u = model.NewBoolVar(f"u{l['id']}")
        unassigned[l["id"]] = u
        objective.append(UNASSIGNED_COST * u)
        lvars = []
        for room, cost in candidates:
            v = model.NewBoolVar(f"x{l['id']}_{room['id']}")
            x[(l["id"], room["id"])] = v
            lvars.append(v)
            if cost:
                objective.append(cost * v)
            buckets[(room["id"], l["pair"])][l["week"]].append(v)
            if room["id"] == l["room_id"]:
                model.AddHint(v, 1)
        model.Add(sum(lvars) + u == 1)

    # one room — one lesson per slot, respecting odd/even weeks (fixed lessons occupy their rooms)
    for key, weeks in buckets.items():
        load = fixed_load.get(key, Counter())
        for half in ("odd", "even"):
            places = 1 - load["all"] - load[half]
            model.Add(sum(weeks["all"]) + sum(weeks[half]) <= max(0, places))

    # building changes between consecutive pairs of a group or teacher
    if w["move"] and len({r["building"] for r in snap.rooms.values()}) > 1:
        per_lesson: dict[int, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        for (l_id, r_id), v in x.items():
            per_lesson[l_id][snap.rooms[r_id]["building"]].append(v)
        ids = {l["id"] for l in free}

        def expr(lid):
            if lid in fixed_room:
                return {snap.rooms[fixed_room[lid]]["building"]: [1]}
            return per_lesson.get(lid, {})

        for a, b in neighbours:
            if a not in ids and b not in ids:
                continue
            ea, eb = expr(a), expr(b)
            if not ea or not eb:
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
        return status, None, reasons
    chosen: dict[int, int | None] = {lid: None for lid in unassigned}
    for (lid, rid), v in x.items():
        if solver.Value(v):
            chosen[lid] = rid
    return status, chosen, reasons


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
