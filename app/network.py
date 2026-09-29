"""Network mode: the same app served to the local network.

* Dispatchers on other computers open http://<ip>:<port>/ and log in with the editor password.
* Teachers and students open http://<ip>:<port>/view — a read-only schedule, no password.
The desktop window itself always talks to 127.0.0.1 and needs no login."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import socket
import threading

import uvicorn

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
COOKIE = "ur_token"


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000).hex()
    return digest, salt


def check_password(password: str, digest: str, salt: str) -> bool:
    if not digest or not salt:
        return False
    return hmac.compare_digest(hash_password(password, salt)[0], digest)


def local_ips() -> list[str]:
    ips: set[str] = set()
    try:  # the address used for the default route — the most useful one
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127."))


class Sessions:
    """Editor tokens issued after a successful login (kept in memory)."""

    def __init__(self):
        self._tokens: set[str] = set()
        self._lock = threading.Lock()

    def issue(self) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._tokens.add(token)
        return token

    def valid(self, token: str | None) -> bool:
        with self._lock:
            return bool(token) and token in self._tokens

    def revoke(self, token: str | None = None) -> None:
        with self._lock:
            if token is None:
                self._tokens.clear()
            else:
                self._tokens.discard(token)


class LanServer:
    """Starts/stops a second uvicorn server bound to all interfaces for the same ASGI app."""

    def __init__(self):
        self.app = None
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self.port: int | None = None
        self.error: str | None = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive() and self._server and self._server.started)

    def start(self, port: int) -> None:
        if self.running and self.port == port:
            return
        self.stop()
        self.error = None
        with socket.socket() as probe:
            try:
                probe.bind(("0.0.0.0", port))
            except OSError:
                self.error = f"порт {port} занят"
                return
        config = uvicorn.Config(self.app, host="0.0.0.0", port=port, log_level="warning", log_config=None)
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        self.port = port

    def stop(self) -> None:
        if self._server:
            self._server.should_exit = True
        if self._thread:
            self._thread.join(timeout=5)
        self._server = None
        self._thread = None
        self.port = None
