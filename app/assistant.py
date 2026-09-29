"""Assistant: Russian free-text commands → a structured action the user confirms.

A local LLM served by Ollama (http://127.0.0.1:11434) does the understanding; the result is
always resolved against the real data (fuzzy names → ids) and shown for confirmation before
anything changes. Without Ollama a small rule-based parser still handles common commands."""
from __future__ import annotations

import difflib
import json
import re
import threading
import urllib.error
import urllib.request

from .checker import Snapshot, find_conflicts, pref_text, suggest_rooms
from .db import DAY_SHORT, DAYS, Database

ACTIONS = [
    "block_room", "unblock_room", "move_lesson", "lock_lesson", "add_preference",
    "set_unavailable", "solve", "explain", "answer",
]
PREF_KINDS = ["building", "room", "equipment", "max_floor", "day", "pair"]
SOLVE_MODES = ["full", "repair", "time-repair", "time-full"]
SOLVE_TITLES = {
    "full": "распределить аудитории заново",
    "repair": "исправить проблемные аудитории",
    "time-repair": "убрать накладки по времени",
    "time-full": "составить время заново",
}

SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ACTIONS},
        "room": {"type": "string"},
        "teacher": {"type": "string"},
        "group": {"type": "string"},
        "subject": {"type": "string"},
        "day": {"type": "integer"},
        "pair": {"type": "integer"},
        "to_day": {"type": "integer"},
        "to_pair": {"type": "integer"},
        "to_room": {"type": "string"},
        "reason": {"type": "string"},
        "pref_kind": {"type": "string", "enum": PREF_KINDS},
        "pref_value": {"type": "string"},
        "pref_mode": {"type": "string", "enum": ["prefer", "avoid"]},
        "weight": {"type": "integer"},
        "solve_mode": {"type": "string", "enum": SOLVE_MODES},
        "text": {"type": "string"},
    },
    "required": ["action"],
}

SYSTEM_PROMPT = """Ты — помощник диспетчера учебного отдела в программе распределения аудиторий UniRooms.
Преобразуй сообщение пользователя в ОДНО действие в формате JSON. Поля, которых нет в сообщении, не заполняй.

Дни недели — числа: 0=Пн, 1=Вт, 2=Ср, 3=Чт, 4=Пт, 5=Сб. Пары — номера 1..{pairs}.

Действия:
- block_room — закрыть аудиторию (ремонт, мероприятие): room, day?, pair?, reason?
- unblock_room — снова открыть аудиторию: room
- move_lesson — перенести занятие: subject?, group?, teacher?, day?, pair? (где оно сейчас) и to_day?, to_pair?, to_room? (куда)
- lock_lesson — закрепить занятие, чтобы автоматика его не двигала: subject?, group?, teacher?, day?, pair?
- add_preference — пожелание преподавателя: teacher, pref_kind (building=корпус, room=аудитория,
  equipment=оборудование, max_floor=этаж не выше, day=день недели, pair=номер пары), pref_value,
  pref_mode (prefer=хочет/любит, avoid=не хочет/не любит), weight 1..10 (важность, по умолчанию 5)
- set_unavailable — преподаватель не может вести занятия: teacher, day, pair? (без pair — весь день)
- solve — запустить автоматику: solve_mode (full=распределить аудитории, repair=исправить аудитории,
  time-repair=убрать накладки по времени, time-full=составить расписание/время заново)
- explain — объяснить, почему занятие стоит в этой аудитории/что с ним не так: subject?, group?, teacher?, day?, pair?
- answer — если это вопрос о программе или непонятная просьба: text (короткий ответ по-русски)

Названия пиши так, как они есть в данных, если можешь их узнать. Отвечай только по-русски.
Для оборудования в pref_value пиши КОД из списка ниже (например projector), для компьютеров — computers.
Группу (например ИВТ-21) всегда клади в поле group, дисциплину — в subject.

Справка о программе (для action=answer, отвечай только по ней):
- Импорт/экспорт: Настройки → «Экспорт данных (Excel)» даёт шаблон со всеми листами; заполненный файл загружается
  кнопкой «Импорт из Excel» там же. Расписание в Excel — кнопка «⬇ Excel» на странице «Расписание».
- «Распределить всё» подбирает аудитории всем незакреплённым занятиям; «Исправить» — только проблемным.
- «Время» → «Убрать накладки» или «Составить заново» подбирает день и пару.
- «Закрыть аудиторию» — ремонт/мероприятие; снять закрытие — в карточке аудитории.
- Замок («Закрепить») — занятие не двигается совсем; булавка — не меняется время. Ctrl+Z — отменить последнее изменение.
- Пожелания и недоступное время преподавателя — в разделе «Преподаватели».
- Доступ по сети и страница /view для студентов — Настройки → «Доступ по сети».
Аудитории: {rooms}
Преподаватели: {teachers}
Группы: {groups}
Дисциплины: {subjects}
Оборудование (код=название): {equipment}

Примеры:
«закрой А-202 в среду на третьей паре, там ремонт» → {{"action":"block_room","room":"А-202","day":2,"pair":3,"reason":"ремонт"}}
«Петрова не любит корпус В» → {{"action":"add_preference","teacher":"Петрова","pref_kind":"building","pref_value":"В","pref_mode":"avoid","weight":7}}
«перенеси матанализ у ИВТ-11 с понедельника на четверг 2 пару» → {{"action":"move_lesson","subject":"Математический анализ","group":"ИВТ-11","day":0,"to_day":3,"to_pair":2}}
«Сидоров в пятницу не может» → {{"action":"set_unavailable","teacher":"Сидоров","day":4}}
«убери накладки» → {{"action":"solve","solve_mode":"time-repair"}}
«почему у ПИ-21 информатика в Б-303?» → {{"action":"explain","group":"ПИ-21","subject":"Информатика"}}
"""

DAY_WORDS = [
    ("понедельн", 0), ("пн", 0), ("вторник", 1), ("вт", 1), ("сред", 2), ("ср", 2),
    ("четверг", 3), ("чт", 3), ("пятниц", 4), ("пт", 4), ("суббот", 5), ("сб", 5),
]
ORDINALS = {"перв": 1, "втор": 2, "трет": 3, "четв": 4, "пят": 5, "шест": 6, "седьм": 7, "восьм": 8}
LATIN_TO_CYR = str.maketrans("ABCEHKMOPTXaceopxy", "АВСЕНКМОРТХасеорху")


# ---------- Ollama client ----------
def _http(url: str, payload: dict | None = None, timeout: float = 120) -> dict:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def warm_up(settings: dict) -> None:
    """Load the model into memory in the background so the first command is fast."""
    st = status(settings)
    if not st["available"]:
        return

    def run():
        try:
            _http(f"{st['url']}/api/generate", {"model": st["model"], "prompt": "", "keep_alive": "30m"}, timeout=300)
        except (urllib.error.URLError, OSError, ValueError):
            pass

    threading.Thread(target=run, daemon=True).start()


def status(settings: dict) -> dict:
    llm = settings.get("llm", {})
    url = llm.get("url", "http://127.0.0.1:11434").rstrip("/")
    try:
        models = [m["name"] for m in _http(f"{url}/api/tags", timeout=3).get("models", [])]
    except (urllib.error.URLError, OSError, ValueError):
        return {"available": False, "models": [], "model": None, "url": url}
    model = llm.get("model") if llm.get("model") in models else (models[0] if models else None)
    return {"available": bool(model), "models": models, "model": model, "url": url}


def chat(settings: dict, messages: list[dict], fmt: dict | None = None, timeout: float = 180) -> str:
    st = status(settings)
    if not st["available"]:
        raise RuntimeError("Ollama недоступна")
    payload = {"model": st["model"], "messages": messages, "stream": False, "options": {"temperature": 0}}
    if fmt:
        payload["format"] = fmt
    return _http(f"{st['url']}/api/chat", payload, timeout=timeout)["message"]["content"]


# ---------- text helpers ----------
def norm(s: str) -> str:
    return re.sub(r"[\s\-–—_.,]", "", str(s).translate(LATIN_TO_CYR).lower().replace("ё", "е"))


def fuzzy(query: str | None, options: dict[int, str], cutoff: float = 0.6) -> list[int]:
    """Ids whose name matches the query best (several when ambiguous)."""
    q = norm(query or "")
    if not q:
        return []
    normed = {i: norm(n) for i, n in options.items()}
    for test in (lambda n: n == q, lambda n: n.startswith(q), lambda n: q in n):
        found = [i for i, n in normed.items() if test(n)]
        if found:
            return found
    if len(q) >= 5:  # another grammatical case: «Петровой» → «Петрова»
        found = [i for i, n in normed.items() if n.startswith(q[:-2])]
        if found:
            return found
    close = set(difflib.get_close_matches(q, list(normed.values()), n=3, cutoff=cutoff))
    return [i for i, n in normed.items() if n in close]


def parse_day(text: str) -> int | None:
    t = text.lower()
    for word, day in DAY_WORDS:
        if re.search(rf"(?<![а-яё]){word}", t):
            return day
    return None


def parse_pair(text: str) -> int | None:
    t = text.lower()
    m = re.search(r"(\d)\s*(?:-?(?:й|я|ю|ей|ой))?\s*пар", t) or re.search(r"пар[аеуы]?\s*(?:№\s*)?(\d)", t)
    if m:
        return int(m.group(1))
    for stem, n in ORDINALS.items():
        if re.search(rf"{stem}\w*\s+пар", t):
            return n
    return None


def rule_based(text: str) -> dict | None:
    """Tiny fallback parser for when no LLM is available."""
    t = text.lower()
    room = re.search(r"([a-zа-я]{1,3}\s*-?\s*\d{2,4})", t)
    if re.search(r"закр|ремонт|недоступн\w* аудитор", t) and room:
        reason = "ремонт" if "ремонт" in t else ("мероприятие" if "мероприят" in t else "")
        return {"action": "block_room", "room": room.group(1), "day": parse_day(t), "pair": parse_pair(t), "reason": reason}
    if re.search(r"откр", t) and room:
        return {"action": "unblock_room", "room": room.group(1)}
    if "накладк" in t:
        return {"action": "solve", "solve_mode": "time-repair"}
    if re.search(r"состав\w*.*(врем|расписан)", t):
        return {"action": "solve", "solve_mode": "time-full"}
    if "исправ" in t:
        return {"action": "solve", "solve_mode": "repair"}
    if "распредел" in t:
        return {"action": "solve", "solve_mode": "full"}
    return None


# ---------- interpretation ----------
def _context(snap: Snapshot, cap: int = 150) -> dict:
    def names(items, key="name"):
        values = sorted({str(i[key]) for i in items})
        extra = f" … и ещё {len(values) - cap}" if len(values) > cap else ""
        return ", ".join(values[:cap]) + extra

    return {
        "pairs": len(snap.pairs),
        "rooms": names(snap.rooms.values()),
        "teachers": names(snap.teachers.values()),
        "groups": names(snap.groups.values()),
        "subjects": names(snap.lessons.values(), "subject"),
        "equipment": ", ".join(f"{k}={v}" for k, v in snap.equipment_names.items()),
    }


def interpret(db: Database, text: str) -> dict:
    snap = Snapshot(db)
    st = status(snap.settings)
    raw = None
    used_llm = False
    if st["available"]:
        try:
            content = chat(snap.settings, [
                {"role": "system", "content": SYSTEM_PROMPT.format(**_context(snap))},
                {"role": "user", "content": text},
            ], fmt=SCHEMA)
            raw = json.loads(content)
            used_llm = True
        except (RuntimeError, urllib.error.URLError, OSError, ValueError, KeyError):
            raw = None
    if raw is None:
        raw = rule_based(text)
    if raw is None:
        hint = ("" if st["available"] else
                " Для свободных команд установите Ollama (ollama.com) и модель: ollama pull qwen2.5:7b")
        return {"ok": False, "message": "Не понял команду. Попробуйте: «закрой А-202 в среду», "
                                        "«убери накладки», «распредели аудитории»." + hint}
    fill_from_text(snap, raw, text)
    plan = resolve(snap, raw)
    plan["raw"] = raw
    plan["llm"] = used_llm
    return plan


def _found_in_text(text: str, names: list[str]) -> list[str]:
    t = norm(text)
    hits = [n for n in names if len(norm(n)) >= 3 and norm(n) in t]
    # «А-202» also matches inside «А-2021»-like strings; prefer the longest names
    return [n for n in hits if not any(n != m and norm(n) in norm(m) for m in hits)]


def fill_from_text(snap: Snapshot, raw: dict, text: str) -> None:
    """The model sometimes drops or garbles names and days — recover them from the text itself."""
    action = raw.get("action")
    if action in ("block_room", "set_unavailable", "lock_lesson", "explain") and raw.get("day") is None:
        raw["day"] = parse_day(text)
    if action == "move_lesson" and not any(raw.get(k) is not None for k in ("to_day", "to_pair", "to_room")):
        # «перенеси … на пятую пару / на четверг»: what follows «на» is the target, not the source
        m = re.search(r"(?<![а-яё])на\s+(.+)$", text.lower())
        if m:
            target_pair, target_day = parse_pair(m.group(1)), parse_day(m.group(1))
            if target_pair:
                raw["to_pair"] = target_pair
                if raw.get("pair") == target_pair:
                    raw.pop("pair")
            if target_day is not None:
                raw["to_day"] = target_day
                if raw.get("day") == target_day:
                    raw.pop("day")
    if action in ("move_lesson", "lock_lesson", "explain") and not raw.get("group"):
        groups = _found_in_text(text, [g["name"] for g in snap.groups.values()])
        if len(groups) == 1:
            raw["group"] = groups[0]
    if action in ("block_room", "unblock_room") and not raw.get("room"):
        rooms = _found_in_text(text, [r["name"] for r in snap.rooms.values()])
        if len(rooms) == 1:
            raw["room"] = rooms[0]
    if action == "add_preference" and raw.get("pref_kind") == "equipment":
        value = str(raw.get("pref_value") or "")
        known = set(snap.equipment_names) | {"computers"}
        if value not in known and not fuzzy(value, dict(enumerate(snap.equipment_names.values()))):
            t = norm(text)
            stems = {code: norm(name)[:6] for code, name in snap.equipment_names.items()}
            stems["computers"] = "компьют"
            hits = [code for code, stem in stems.items() if stem and stem in t]
            if "пк" in re.findall(r"[а-яa-z]+", text.lower()):
                hits.append("computers")
            if len(set(hits)) == 1:
                raw["pref_value"] = hits[0]


def _one(kind: str, ids: list[int], options: dict[int, str], query: str | None) -> tuple[int | None, str | None]:
    if not ids:
        return None, f"не нашёл {kind} «{query}»" if query else f"не указан(а) {kind}"
    if len(ids) > 1:
        return None, f"{kind} «{query}»: подходит несколько — " + ", ".join(options[i] for i in ids[:5])
    return ids[0], None


def _day_ok(day) -> int | None:
    try:
        d = int(day)
    except (TypeError, ValueError):
        return None
    return d if 0 <= d <= 6 else None


def find_lessons(snap: Snapshot, raw: dict) -> list[dict]:
    items = list(snap.lessons.values())
    if raw.get("subject"):
        subjects = dict(enumerate(sorted({l["subject"] for l in items})))
        names = {subjects[i] for i in fuzzy(raw["subject"], subjects)}
        items = [l for l in items if l["subject"] in names]
    if raw.get("group"):
        ids = set(fuzzy(raw["group"], {g["id"]: g["name"] for g in snap.groups.values()}))
        items = [l for l in items if ids & set(l["group_ids"])]
    if raw.get("teacher"):
        ids = set(fuzzy(raw["teacher"], {t["id"]: t["name"] for t in snap.teachers.values()}))
        items = [l for l in items if l["teacher_id"] in ids]
    if _day_ok(raw.get("day")) is not None:
        items = [l for l in items if l["day"] == int(raw["day"])]
    if raw.get("pair"):
        items = [l for l in items if l["pair"] == int(raw["pair"])]
    return items


def resolve(snap: Snapshot, raw: dict) -> dict:
    action = raw.get("action")
    rooms = {r["id"]: r["name"] for r in snap.rooms.values()}
    teachers = {t["id"]: t["name"] for t in snap.teachers.values()}
    day = _day_ok(raw.get("day"))
    pair = int(raw["pair"]) if raw.get("pair") else None
    when = (DAY_SHORT[day] if day is not None else "все дни") + ", " + (f"{pair} пара" if pair else "все пары")

    if action == "answer":
        return {"ok": True, "reply": raw.get("text") or "Не знаю, что ответить.", "action": None}

    if action == "solve":
        mode = raw.get("solve_mode") if raw.get("solve_mode") in SOLVE_MODES else "repair"
        return {"ok": True, "action": {"action": "solve", "solve_mode": mode},
                "summary": f"Запустить: {SOLVE_TITLES[mode]} (перед применением покажу изменения)"}

    if action in ("block_room", "unblock_room"):
        rid, err = _one("аудиторию", fuzzy(raw.get("room"), rooms), rooms, raw.get("room"))
        if err:
            return {"ok": False, "message": err.capitalize()}
        if action == "unblock_room":
            blocks = snap.blocks.get(rid, [])
            if not blocks:
                return {"ok": False, "message": f"Аудитория {rooms[rid]} и так открыта"}
            return {"ok": True, "action": {"action": "unblock_room", "room_id": rid},
                    "summary": f"Открыть аудиторию {rooms[rid]} (снять закрытий: {len(blocks)})"}
        affected = [l for l in snap.lessons.values() if l["room_id"] == rid
                    and (day is None or l["day"] == day) and (pair is None or l["pair"] == pair)]
        reason = raw.get("reason") or ""
        return {"ok": True,
                "action": {"action": "block_room", "room_id": rid, "day": day, "pair": pair, "reason": reason},
                "summary": f"Закрыть аудиторию {rooms[rid]}: {when}" + (f" ({reason})" if reason else "")
                           + f". Затронуто занятий: {len(affected)}"}

    if action in ("move_lesson", "lock_lesson", "explain"):
        chosen = snap.lessons.get(int(raw["lesson_id"])) if raw.get("lesson_id") else None
        found = [chosen] if chosen else find_lessons(snap, raw)
        if not found:
            return {"ok": False, "message": "Не нашёл такое занятие — уточните дисциплину, группу или день."}
        if len(found) > 1:
            found.sort(key=lambda l: (l["day"], l["pair"]))
            return {
                "ok": False,
                "message": f"Подходит несколько занятий ({len(found)}). Какое именно?",
                "choices": [
                    {"lesson_id": l["id"], "label": f"{snap.label(l)} — {DAY_SHORT[l['day']]} {l['pair']} пара"}
                    for l in found[:8]
                ],
                "raw": raw,
            }
        l = found[0]
        where = f"{snap.label(l)} ({DAY_SHORT[l['day']]} {l['pair']} пара)"
        if action == "lock_lesson":
            return {"ok": True, "action": {"action": "lock_lesson", "lesson_id": l["id"]},
                    "summary": f"Закрепить {where}"}
        if action == "explain":
            return {"ok": True, "action": {"action": "explain", "lesson_id": l["id"]},
                    "summary": f"Объяснить: {where}", "auto": True}
        to_day = _day_ok(raw.get("to_day"))
        to_pair = int(raw["to_pair"]) if raw.get("to_pair") else None
        to_room = None
        if raw.get("to_room"):
            to_room, err = _one("аудиторию", fuzzy(raw["to_room"], rooms), rooms, raw["to_room"])
            if err:
                return {"ok": False, "message": err.capitalize()}
        if to_day is None and to_pair is None and to_room is None:
            return {"ok": False, "message": f"Нашёл {where}, но не понял, куда перенести."}
        target = []
        if to_day is not None or to_pair is not None:
            target.append(f"{DAY_SHORT[to_day if to_day is not None else l['day']]} "
                          f"{to_pair or l['pair']} пара")
        if to_room:
            target.append(rooms[to_room])
        return {"ok": True,
                "action": {"action": "move_lesson", "lesson_id": l["id"], "day": to_day, "pair": to_pair,
                           "room_id": to_room},
                "summary": f"Перенести {where} → " + ", ".join(target)}

    if action in ("add_preference", "set_unavailable"):
        tid, err = _one("преподавателя", fuzzy(raw.get("teacher"), teachers), teachers, raw.get("teacher"))
        if err:
            return {"ok": False, "message": err.capitalize()}
        if action == "set_unavailable":
            if day is None:
                return {"ok": False, "message": "Не понял, в какой день преподаватель недоступен."}
            return {"ok": True, "action": {"action": "set_unavailable", "teacher_id": tid, "day": day, "pair": pair},
                    "summary": f"{teachers[tid]} не может вести занятия: {when}"}
        kind = raw.get("pref_kind")
        if kind not in PREF_KINDS:
            return {"ok": False, "message": "Не понял, какое это пожелание (корпус, аудитория, оборудование, день, пара)."}
        value = raw.get("pref_value")
        if kind in ("max_floor", "pair"):
            try:
                value = int(re.sub(r"\D", "", str(value)))
            except ValueError:
                return {"ok": False, "message": "Не понял номер этажа или пары."}
        elif kind == "day":
            value = _day_ok(value) if str(value).isdigit() else parse_day(str(value))
            if value is None:
                return {"ok": False, "message": "Не понял день недели."}
        elif kind == "building":
            buildings = sorted({r["building"] for r in snap.rooms.values() if r["building"]})
            opts = dict(enumerate(buildings))
            ids = fuzzy(str(value), opts, cutoff=0.8)
            if len(ids) != 1:
                return {"ok": False, "message": f"Нет корпуса «{value}». Есть: {', '.join(buildings)}"}
            value = buildings[ids[0]]
        elif kind == "room":
            rid, err = _one("аудиторию", fuzzy(str(value), rooms), rooms, str(value))
            if err:
                return {"ok": False, "message": err.capitalize()}
            value = rooms[rid]
        elif kind == "equipment":
            eq = dict(snap.equipment_names) | {"computers": "компьютеры"}
            codes = {i: c for i, c in enumerate(eq)}
            ids = fuzzy(str(value), {i: eq[c] for i, c in codes.items()}) or fuzzy(str(value), codes)
            if len(ids) != 1:
                return {"ok": False, "message": f"Не нашёл оборудование «{value}»"}
            value = codes[ids[0]]
        weight = max(1, min(10, int(raw.get("weight") or 5)))
        pref = {"kind": kind, "value": value, "mode": raw.get("pref_mode") or "prefer", "weight": weight}
        return {"ok": True, "action": {"action": "add_preference", "teacher_id": tid, "preference": pref},
                "summary": f"{teachers[tid]}: {pref_text(pref, snap)} (важность {weight})"}

    return {"ok": False, "message": "Не понял, что сделать."}


# ---------- execution ----------
def execute(db: Database, action: dict) -> dict:
    kind = action.get("action")
    if kind == "block_room":
        db.insert("room_blocks", {k: action.get(k) for k in ("room_id", "day", "pair", "reason")})
        snap = Snapshot(db)
        affected = [l["id"] for l in snap.lessons.values() if l["room_id"] == action["room_id"]
                    and snap.blocked(action["room_id"], l["day"], l["pair"])]
        return {"message": f"Аудитория закрыта. Затронуто занятий: {len(affected)}", "affected": len(affected)}
    if kind == "unblock_room":
        for b in [b for b in db.all("room_blocks") if b["room_id"] == action["room_id"]]:
            db.delete("room_blocks", b["id"])
        return {"message": "Аудитория снова открыта"}
    if kind == "lock_lesson":
        db.apply_changes("Закреплено помощником", {int(action["lesson_id"]): {"locked": True}})
        return {"message": "Занятие закреплено"}
    if kind == "move_lesson":
        change = {k: action[k] for k in ("day", "pair", "room_id") if action.get(k) is not None}
        n = db.apply_changes("Перенос помощником", {int(action["lesson_id"]): change})
        snap = Snapshot(db)
        mine = [c["message"] for c in find_conflicts(snap) if action["lesson_id"] in c["lesson_ids"]]
        msg = "Занятие перенесено" if n else "Занятие уже там"
        if mine:
            msg += ". Внимание: " + "; ".join(mine[:3])
        return {"message": msg, "affected": len(mine)}
    if kind == "set_unavailable":
        t = db.get("teachers", action["teacher_id"])
        pairs = [action["pair"]] if action.get("pair") else [p["n"] for p in db.settings()["pairs"]]
        slots = {tuple(s) for s in t["unavailable"]} | {(action["day"], p) for p in pairs}
        db.update("teachers", t["id"], {"unavailable": sorted([list(s) for s in slots])})
        busy = [l for l in db.lessons() if l["teacher_id"] == t["id"] and (l["day"], l["pair"]) in slots]
        return {"message": f"Сохранено. Занятий в это время: {len(busy)}"
                           + (" — нажмите «Убрать накладки», чтобы перенести их" if busy else ""),
                "affected": len(busy)}
    if kind == "add_preference":
        t = db.get("teachers", action["teacher_id"])
        db.update("teachers", t["id"], {"preferences": t["preferences"] + [action["preference"]]})
        return {"message": "Пожелание добавлено. Оно учтётся при следующем распределении."}
    if kind == "explain":
        return {"message": explain(db, int(action["lesson_id"]))}
    raise ValueError("Неизвестное действие")


def explain(db: Database, lesson_id: int) -> str:
    snap = Snapshot(db)
    l = snap.lessons[lesson_id]
    rows = suggest_rooms(snap, lesson_id, limit=4)
    room = snap.rooms.get(l["room_id"])
    current = next((r for r in rows if r["room_id"] == l["room_id"]), None)
    problems = [c["message"] for c in find_conflicts(snap) if lesson_id in c["lesson_ids"]]
    alternatives = [r for r in rows if r["room_id"] != l["room_id"] and r["status"] != "bad"][:3]

    facts = [f"Занятие: {snap.label(l)}, {DAYS[l['day']]}, {l['pair']} пара, {snap.size(l)} студентов."]
    if room:
        facts.append(f"Сейчас аудитория {room['name']} (корпус {room['building']}, {room['capacity']} мест).")
        if current:
            facts += [f"Плюс: {p}" for p in current["pros"]] + [f"Минус: {c}" for c in current["cons"]]
            facts += [f"Нарушение: {i}" for i in current["issues"]]
    else:
        facts.append("Аудитория не назначена.")
    facts += [f"Проблема: {p}" for p in problems]
    for a in alternatives:
        facts.append(f"Альтернатива {a['room']}: " + ", ".join(a["pros"][:2] + [f"минус: {c}" for c in a["cons"][:2]]))
    text = "\n".join(facts)
    try:
        return chat(snap.settings, [
            {"role": "system", "content": "Ты помощник диспетчера. Кратко (2–4 предложения, по-русски) объясни "
                                          "выбор аудитории, опираясь ТОЛЬКО на факты. Не выдумывай."},
            {"role": "user", "content": text},
        ], timeout=120).strip()
    except (RuntimeError, urllib.error.URLError, OSError, ValueError, KeyError):
        return text
