import socket

from fastapi.testclient import TestClient

from app import network
from app.api import create_app
from app.db import Database
from app.seed import seed_demo


def clients():
    db = Database(":memory:")
    seed_demo(db)
    app = create_app(db, static_dir=None)
    local = TestClient(app)
    remote = TestClient(app, client=("192.168.1.50", 50000))
    return db, local, remote


def test_password_hashing():
    digest, salt = network.hash_password("secret")
    assert network.check_password("secret", digest, salt)
    assert not network.check_password("wrong", digest, salt)
    assert not network.check_password("secret", "", "")


def test_remote_needs_login_but_view_is_public():
    db, local, remote = clients()
    assert local.get("/api/state").status_code == 200
    assert remote.get("/api/state").status_code == 401
    assert remote.post("/api/solve", json={}).status_code == 401
    meta = remote.get("/api/public/meta").json()
    gid = meta["groups"][0]["id"]
    sched = remote.get("/api/public/schedule", params={"kind": "group", "id": gid}).json()
    assert sched["lessons"] and "preferences" not in str(sched)
    assert remote.get("/api/session").json() == {"local": False, "editor": False, "password_set": False}


def test_login_flow_and_secrets_are_hidden():
    db, local, remote = clients()
    # only the main computer may configure the network; enabling needs a password
    assert remote.put("/api/network", json={"enabled": False, "port": 8765, "password": "x"}).status_code == 401
    port = _free_port()
    res = local.put("/api/network", json={"enabled": True, "port": port, "password": "pass1234"}).json()
    try:
        assert res["enabled"] and res["password_set"]
        settings = local.get("/api/state").json()["settings"]
        assert "password_hash" not in str(settings) and settings["network"]["password_set"]
        assert remote.post("/api/login", json={"password": "nope"}).status_code == 403
        assert remote.post("/api/login", json={"password": "pass1234"}).status_code == 200
        assert remote.get("/api/state").status_code == 200
        assert remote.get("/api/session").json()["editor"] is True
        # remote editors cannot change network settings, even logged in
        assert remote.put("/api/network", json={"enabled": False, "port": port}).status_code == 403
        # nor sneak them in through the general settings endpoint
        remote.put("/api/settings", json={"network": {"password_hash": "", "salt": ""}})
        assert db.settings()["network"]["password_hash"]
        remote.post("/api/logout")
        assert remote.get("/api/state").status_code == 401
    finally:
        local.put("/api/network", json={"enabled": False, "port": port})


def test_version_changes_on_writes():
    db, local, _ = clients()
    v1 = local.get("/api/version").json()["version"]
    lid = local.get("/api/state").json()["lessons"][0]["id"]
    local.post(f"/api/lessons/{lid}/lock", json={"locked": True})
    assert local.get("/api/version").json()["version"] > v1


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
