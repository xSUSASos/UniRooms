"""REST API consumed by the React frontend."""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import assistant, excel_io, network, solver, timetable
from .checker import Snapshot, evaluate_grid, find_conflicts, suggest_rooms
from .db import DAY_SHORT, DAYS, LESSON_KINDS, ROOM_KINDS, WEEKS, Database
from .seed import seed_demo

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


# ---------- input models ----------
class RoomIn(BaseModel):
    name: str = Field(min_length=1)
    building: str = ""
    floor: int = 1
    capacity: int = Field(ge=0)
    kind: Literal["lecture", "practice", "lab", "computer"] = "practice"
    computers: int = Field(0, ge=0)
    equipment: list[str] = []
    accessible: bool = False
    active: bool = True
    notes: str = ""


class Preference(BaseModel):
    kind: Literal["building", "room", "equipment", "max_floor", "day", "pair"]
    value: str | int
    mode: Literal["prefer", "avoid"] = "prefer"
    weight: int = Field(5, ge=1, le=10)


class TeacherIn(BaseModel):
    name: str = Field(min_length=1)
    department: str = ""
    needs_accessible: bool = False
    unavailable: list[tuple[int, int]] = []
    preferences: list[Preference] = []


class GroupIn(BaseModel):
    name: str = Field(min_length=1)
    course: int = 1
    size: int = Field(ge=0)
    home_building: str = ""


class LessonIn(BaseModel):
    subject: str = Field(min_length=1)
    kind: Literal["lecture", "practice", "lab"] = "practice"
    teacher_id: int | None = None
    group_ids: list[int] = []
    day: int = Field(ge=0, le=6)
    pair: int = Field(ge=1)
    week: Literal["all", "odd", "even"] = "all"
    required_equipment: list[str] = []
    min_computers: int = Field(0, ge=0)
    room_id: int | None = None
    locked: bool = False
    fixed_time: bool = False


class BlockIn(BaseModel):
    room_id: int
    day: int | None = None
    pair: int | None = None
    reason: str = ""


class EquipmentIn(BaseModel):
    code: str = Field(min_length=1, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1)


class MoveIn(BaseModel):
    day: int | None = None
    pair: int | None = None
    room_id: int | None = None
    clear_room: bool = False


class LockIn(BaseModel):
    locked: bool


class SolveIn(BaseModel):
    mode: Literal["full", "repair"] = "full"
    time_limit: float | None = None


class TimetableIn(BaseModel):
    mode: Literal["full", "repair"] = "repair"
    time_limit: float | None = None


class AskIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class ExecIn(BaseModel):
    action: dict


class ApplyIn(BaseModel):
    changes: list[dict]
    description: str = "Автораспределение"


class LoginIn(BaseModel):
    password: str = Field(max_length=200)


class NetworkIn(BaseModel):
    enabled: bool
    port: int = Field(8765, ge=1024, le=65535)
    password: str | None = Field(None, max_length=200)


def public_settings(settings: dict) -> dict:
    """Settings without secrets."""
    net = dict(settings.get("network", {}))
    net["password_set"] = bool(net.pop("password_hash", ""))
    net.pop("salt", None)
    return {**settings, "network": net}


def create_app(db: Database, static_dir: Path | None = None, lan: network.LanServer | None = None) -> FastAPI:
    app = FastAPI(title="UniRooms", docs_url="/api/docs", openapi_url="/api/openapi.json")
    api = APIRouter(prefix="/api")
    sessions = network.Sessions()
    lan = lan or network.LanServer()
    lan.app = app

    def is_local(request: Request) -> bool:
        return (request.client.host if request.client else "127.0.0.1") in network.LOCAL_HOSTS

    @app.middleware("http")
    async def access_control(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/") and not is_local(request):
            open_paths = path.startswith("/api/public/") or path in ("/api/session", "/api/login")
            if not open_paths and not sessions.valid(request.cookies.get(network.COOKIE)):
                return JSONResponse({"detail": "Нужен вход: введите пароль редактора"}, status_code=401)
        return await call_next(request)

    def need(table, id_):
        row = db.get(table, id_)
        if not row:
            raise HTTPException(404, "Запись не найдена")
        return row

    def unique_error(e: Exception):
        if "UNIQUE" in str(e):
            raise HTTPException(409, "Такое название уже есть")
        raise e

    # ---------- state ----------
    @api.get("/state")
    def state():
        return {
            "settings": public_settings(db.settings()),
            "version": db.version,
            "equipment": db.equipment(),
            "rooms": db.all("rooms", "building, name"),
            "blocks": db.all("room_blocks"),
            "teachers": db.all("teachers", "name"),
            "groups": db.all("student_groups", "course, name"),
            "lessons": db.lessons(),
            "dicts": {"room_kinds": ROOM_KINDS, "lesson_kinds": LESSON_KINDS, "weeks": WEEKS, "days": DAYS},
            "history": db.history(20),
            "db_path": db.path,
        }

    @api.put("/settings")
    def save_settings(data: dict):
        data.pop("network", None)  # changed only through /api/network, from this computer
        db.save_settings(data)
        return public_settings(db.settings())

    @api.get("/version")
    def version():
        return {"version": db.version}

    # ---------- session & network ----------
    @api.get("/session")
    def session(request: Request):
        net = db.settings()["network"]
        local = is_local(request)
        return {
            "local": local,
            "editor": local or sessions.valid(request.cookies.get(network.COOKIE)),
            "password_set": bool(net.get("password_hash")),
        }

    @api.post("/login")
    def login(body: LoginIn, response: Response):
        net = db.settings()["network"]
        if not network.check_password(body.password, net.get("password_hash", ""), net.get("salt", "")):
            raise HTTPException(403, "Неверный пароль")
        response.set_cookie(network.COOKIE, sessions.issue(), httponly=True, samesite="lax", max_age=30 * 86400)
        return {"ok": True}

    @api.post("/logout")
    def logout(request: Request, response: Response):
        sessions.revoke(request.cookies.get(network.COOKIE))
        response.delete_cookie(network.COOKIE)
        return {"ok": True}

    def network_info() -> dict:
        net = db.settings()["network"]
        port = lan.port or net.get("port", 8765)
        return {
            "enabled": bool(net.get("enabled")),
            "running": lan.running,
            "error": lan.error,
            "port": net.get("port", 8765),
            "password_set": bool(net.get("password_hash")),
            "urls": [f"http://{ip}:{port}/" for ip in network.local_ips()],
        }

    @api.get("/network")
    def get_network():
        return network_info()

    @api.put("/network")
    def set_network(body: NetworkIn, request: Request):
        if not is_local(request):
            raise HTTPException(403, "Сетевой доступ настраивается только на главном компьютере")
        net = db.settings()["network"]
        if body.password:
            net["password_hash"], net["salt"] = network.hash_password(body.password)
            sessions.revoke()
        if body.enabled and not net.get("password_hash"):
            raise HTTPException(400, "Сначала задайте пароль редактора")
        net.update(enabled=body.enabled, port=body.port)
        db.save_settings({"network": net})
        if body.enabled:
            lan.start(body.port)
            for _ in range(50):  # wait for uvicorn to bind
                if lan.running or lan.error:
                    break
                time.sleep(0.1)
        else:
            lan.stop()
        return network_info()

    # ---------- public read-only schedule (teachers, students) ----------
    @api.get("/public/meta")
    def public_meta():
        s = db.settings()
        return {
            "days": [DAYS[i] for i in range(s["days"])],
            "pairs": s["pairs"],
            "groups": [{"id": g["id"], "name": g["name"], "course": g["course"]} for g in db.all("student_groups", "course, name")],
            "teachers": [{"id": t["id"], "name": t["name"]} for t in db.all("teachers", "name")],
            "rooms": [{"id": r["id"], "name": r["name"], "building": r["building"]} for r in db.all("rooms", "building, name")],
            "version": db.version,
        }

    @api.get("/public/schedule")
    def public_schedule(kind: Literal["group", "teacher", "room"], id: int):
        snap = Snapshot(db)
        items = []
        for l in snap.lessons.values():
            if (kind == "group" and id in l["group_ids"]) or (kind == "teacher" and l["teacher_id"] == id) \
                    or (kind == "room" and l["room_id"] == id):
                room = snap.rooms.get(l["room_id"])
                teacher = snap.teachers.get(l["teacher_id"])
                items.append({
                    "id": l["id"], "day": l["day"], "pair": l["pair"], "week": l["week"], "subject": l["subject"],
                    "kind": LESSON_KINDS.get(l["kind"], l["kind"]),
                    "teacher": teacher["name"] if teacher else "",
                    "groups": ", ".join(snap.groups[g]["name"] for g in l["group_ids"] if g in snap.groups),
                    "room": room["name"] if room else "", "building": room["building"] if room else "",
                })
        items.sort(key=lambda x: (x["day"], x["pair"], x["week"]))
        return {"lessons": items, "version": db.version}

    @api.get("/public/version")
    def public_version():
        return {"version": db.version}

    # ---------- equipment ----------
    @api.post("/equipment")
    def upsert_equipment(e: EquipmentIn):
        db.upsert_equipment(e.code, e.name)
        return db.equipment()

    @api.delete("/equipment/{code}")
    def delete_equipment(code: str):
        db.delete_equipment(code)
        return db.equipment()

    # ---------- simple CRUD ----------
    def crud(path: str, table: str, model):
        def create(item: model):  # type: ignore[valid-type]
            try:
                return need(table, db.insert(table, item.model_dump()))
            except Exception as e:  # noqa: BLE001
                unique_error(e)

        def update(id_: int, item: model):  # type: ignore[valid-type]
            need(table, id_)
            try:
                db.update(table, id_, item.model_dump())
            except Exception as e:  # noqa: BLE001
                unique_error(e)
            return need(table, id_)

        def delete(id_: int):
            db.delete(table, id_)
            return {"ok": True}

        api.add_api_route(f"/{path}", create, methods=["POST"])
        api.add_api_route(f"/{path}/{{id_}}", update, methods=["PUT"])
        api.add_api_route(f"/{path}/{{id_}}", delete, methods=["DELETE"])

    crud("rooms", "rooms", RoomIn)
    crud("teachers", "teachers", TeacherIn)
    crud("groups", "student_groups", GroupIn)
    crud("blocks", "room_blocks", BlockIn)

    # ---------- lessons ----------
    @api.post("/lessons")
    def create_lesson(item: LessonIn):
        return db.lesson(db.save_lesson(item.model_dump()))

    @api.put("/lessons/{id_}")
    def update_lesson(id_: int, item: LessonIn):
        need("lessons", id_)
        db.save_lesson(item.model_dump(), id_)
        return db.lesson(id_)

    @api.delete("/lessons/{id_}")
    def delete_lesson(id_: int):
        db.delete("lessons", id_)
        return {"ok": True}

    @api.post("/lessons/{id_}/move")
    def move_lesson(id_: int, m: MoveIn):
        l = need("lessons", id_)
        change = {k: v for k, v in m.model_dump().items() if v is not None and k != "clear_room"}
        if m.clear_room:
            change["room_id"] = None
        snap = Snapshot(db)
        room = snap.rooms.get(change.get("room_id", l["room_id"]))
        what = []
        if "day" in change or "pair" in change:
            what.append(f"{DAY_SHORT[change.get('day', l['day'])]} {change.get('pair', l['pair'])} пара")
        if "room_id" in change:
            what.append(room["name"] if room else "без аудитории")
        n = db.apply_changes(f"«{l['subject']}» → " + ", ".join(what), {id_: change})
        return {"changed": n, "lesson": db.lesson(id_)}

    @api.post("/lessons/{id_}/lock")
    def lock_lesson(id_: int, body: LockIn):
        l = need("lessons", id_)
        db.apply_changes(f"{'Закреплено' if body.locked else 'Откреплено'} «{l['subject']}»", {id_: {"locked": body.locked}})
        return db.lesson(id_)

    @api.get("/lessons/{id_}/suggest")
    def suggest(id_: int):
        need("lessons", id_)
        return suggest_rooms(Snapshot(db), id_)

    @api.get("/lessons/{id_}/evaluate")
    def evaluate(id_: int, day: int):
        need("lessons", id_)
        return evaluate_grid(Snapshot(db), id_, day)

    # ---------- checks & solving ----------
    @api.get("/conflicts")
    def conflicts():
        return find_conflicts(Snapshot(db))

    @api.post("/solve")
    def run_solver(body: SolveIn):
        return solver.solve(db, body.mode, body.time_limit)

    @api.post("/timetable")
    def run_timetable(body: TimetableIn):
        return timetable.solve_timetable(db, body.mode, body.time_limit)

    @api.post("/apply")
    def apply(body: ApplyIn):
        return {"changed": solver.apply(db, body.changes, body.description)}

    # ---------- assistant ----------
    @api.get("/assistant/status")
    def assistant_status():
        return assistant.status(db.settings())

    @api.post("/assistant/interpret")
    def assistant_interpret(body: AskIn):
        return assistant.interpret(db, body.text)

    @api.post("/assistant/execute")
    def assistant_execute(body: ExecIn):
        try:
            return assistant.execute(db, body.action)
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(400, f"Не удалось выполнить: {e}") from e

    @api.post("/undo")
    def undo():
        res = db.undo()
        if not res:
            raise HTTPException(400, "Нечего отменять")
        return res

    # ---------- data ----------
    @api.post("/demo")
    def demo():
        return seed_demo(db)

    @api.post("/clear")
    def clear():
        db.clear()
        return {"ok": True}

    @api.get("/export/data.xlsx")
    def export_data():
        return Response(excel_io.export_data(db), media_type=XLSX,
                        headers={"Content-Disposition": 'attachment; filename="unirooms-data.xlsx"'})

    @api.get("/export/schedule.xlsx")
    def export_schedule():
        return Response(excel_io.export_schedule(db), media_type=XLSX,
                        headers={"Content-Disposition": 'attachment; filename="unirooms-schedule.xlsx"'})

    @api.post("/import")
    async def import_data(file: UploadFile):
        try:
            return excel_io.import_data(db, await file.read())
        except excel_io.ImportError_ as e:
            raise HTTPException(422, {"errors": e.errors}) from e
        except Exception as e:  # noqa: BLE001
            raise HTTPException(422, {"errors": [f"Не удалось прочитать файл: {e}"]}) from e

    app.include_router(api)

    static_dir = static_dir or _static_dir()
    if static_dir and (static_dir / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

        @app.get("/{path:path}")
        def spa(path: str):
            f = (static_dir / path).resolve()
            if path and f.is_file() and f.is_relative_to(static_dir.resolve()):
                return FileResponse(f)
            return FileResponse(static_dir / "index.html")

    return app


def _static_dir() -> Path | None:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    for p in (base / "frontend" / "dist", base / "static"):
        if p.exists():
            return p
    return None
