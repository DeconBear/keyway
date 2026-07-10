"""Keyway server manager — in-process mode for standalone desktop.

Starts the Keyway server in a daemon thread inside the same Python
process. No subprocess needed — works when packaged via PyInstaller.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
import urllib.request
from typing import Any

READY_TIMEOUT = 30  # seconds


class ServerManager:
    """Manages the Keyway server lifecycle in a daemon thread."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9233) -> None:
        self.host = host
        self.port = port
        self.url = f"http://{host}:{port}"
        self._thread: threading.Thread | None = None
        self._server: Any = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def admin_token(self) -> str:
        env = self._env()
        return env.get("KEYWAY_ADMIN_TOKEN", "")

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        # Desktop always binds loopback — never expose auth-bypass remotely.
        env["KEYWAY_HOST"] = self.host if self.host in {"127.0.0.1", "localhost", "::1"} else "127.0.0.1"
        self.host = env["KEYWAY_HOST"]
        self.url = f"http://{self.host}:{self.port}"
        env.setdefault("KEYWAY_PORT", str(self.port))
        if not env.get("KEYWAY_SECRET"):
            env["KEYWAY_SECRET"] = secrets.token_urlsafe(48)
        if not env.get("KEYWAY_ADMIN_TOKEN"):
            env["KEYWAY_ADMIN_TOKEN"] = secrets.token_urlsafe(24)
        env.setdefault("KEYWAY_DESKTOP_MODE", "1")
        return env

    def start(self) -> bool:
        if self.running:
            return True

        env = self._env()
        for k, v in env.items():
            if k.startswith("KEYWAY_"):
                os.environ[k] = v

        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()

        deadline = time.time() + READY_TIMEOUT
        while time.time() < deadline:
            if self.is_healthy():
                return True
            if not self._thread.is_alive():
                return False
            time.sleep(0.3)
        return self.running and self.is_healthy()

    def _run_server(self) -> None:
        import uvicorn

        config = uvicorn.Config(
            "keyway.app:create_app",
            host=self.host,
            port=self.port,
            log_level="warning",
            factory=True,
        )
        self._server = uvicorn.Server(config)
        self._server.run()

    def stop(self) -> None:
        server = self._server
        if server is not None:
            server.should_exit = True
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
        self._server = None
        self._thread = None

    def is_healthy(self) -> bool:
        if not self.running:
            return False
        try:
            with urllib.request.urlopen(f"{self.url}/health", timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False
