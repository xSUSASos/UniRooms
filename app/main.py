"""Entry point: start the local API server and open the app window.

    python -m app.main            # desktop window (pywebview), browser as fallback
    python -m app.main --server   # API only, for frontend development (vite on :5173)
"""
from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
import threading
import time
import webbrowser

import uvicorn

from .api import create_app
from .db import Database
from .seed import seed_demo

log = logging.getLogger("unirooms")


def free_port(preferred: int) -> int:
    for port in (preferred, 0):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return s.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("Нет свободного порта")


def wait_ready(port: int, timeout: float = 15) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.1)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="UniRooms — распределение аудиторий")
    parser.add_argument("--server", action="store_true", help="только сервер, без окна")
    parser.add_argument("--browser", action="store_true", help="открыть в браузере вместо окна")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", help="путь к файлу базы данных")
    args = parser.parse_args()

    db = Database(args.db)
    # windowed exe has no console: keep writes from crashing and log to a file next to the db
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    if not args.server:
        logging.basicConfig(filename=os.path.join(os.path.dirname(os.path.abspath(db.path)), "unirooms.log"),
                            level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if db.is_empty():
        seed_demo(db)

    port = args.port if args.server else free_port(args.port)
    config = uvicorn.Config(create_app(db), host="127.0.0.1", port=port, log_level="warning", log_config=None)
    server = uvicorn.Server(config)

    if args.server:
        print(f"UniRooms API: http://127.0.0.1:{port}  (база: {db.path})")
        server.run()
        return

    threading.Thread(target=server.run, daemon=True).start()
    if not wait_ready(port):
        raise SystemExit("Сервер не запустился")
    url = f"http://127.0.0.1:{port}/"

    if not args.browser:
        try:
            import webview

            webview.settings["ALLOW_DOWNLOADS"] = True
            webview.create_window("UniRooms — распределение аудиторий", url, width=1400, height=880,
                                  min_size=(1000, 640))
            webview.start()
            server.should_exit = True
            return
        except Exception:  # noqa: BLE001 — no WebView2: fall back to the browser
            log.exception("pywebview failed, falling back to browser")

    webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.should_exit = True


if __name__ == "__main__":
    sys.exit(main())
