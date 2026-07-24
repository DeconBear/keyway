"""Keyway server manager — in-process mode for standalone desktop.

Starts the Keyway server in a daemon thread inside the same Python
process. No subprocess needed — works when packaged via PyInstaller.

Persists KEYWAY_SECRET / ADMIN_TOKEN / DATA_DIR under the user app-data
directory and picks a free loopback port when the preferred port is busy.
"""

from __future__ import annotations

import os
import threading
import time
import urllib.request
from typing import Any
from urllib.parse import quote

from paths import DEFAULT_PORT, find_free_port, load_or_create_config

READY_TIMEOUT = 30  # seconds

# Loopback health checks must never go through a system proxy (Windows
# registry proxies don't bypass-dotted-hosts reliably). build_opener keeps
# the default HTTP(S) handlers; a bare OpenerDirector would miss them and
# always fail open().
_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ServerManager:
    """Manages the Keyway server lifecycle in a daemon thread."""

    def __init__(self, host: str = "127.0.0.1", preferred_port: int | None = None) -> None:
        self.host = host if host in {"127.0.0.1", "localhost", "::1"} else "127.0.0.1"
        self.preferred_port = preferred_port
        self.port = preferred_port or DEFAULT_PORT
        self.url = f"http://{self.host}:{self.port}"
        self.config: dict[str, str] = {}
        self._thread: threading.Thread | None = None
        self._server: Any = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def admin_token(self) -> str:
        return (self.config.get("KEYWAY_ADMIN_TOKEN")
                or os.environ.get("KEYWAY_ADMIN_TOKEN", ""))

    def admin_url(self) -> str:
        """URL that sets a session cookie then opens the admin panel."""
        token = self.admin_token
        if token:
            return f"{self.url}/admin/desktop-login?token={quote(token, safe='')}"
        return f"{self.url}/admin.html"

    def prepare_env(self) -> dict[str, str]:
        """Load persistent config, choose a free port, apply to os.environ."""
        cfg = load_or_create_config()
        preferred = self.preferred_port
        if preferred is None:
            try:
                preferred = int(cfg.get("KEYWAY_PORT") or DEFAULT_PORT)
            except ValueError:
                preferred = DEFAULT_PORT

        port = find_free_port(self.host, preferred)
        self.port = port
        self.url = f"http://{self.host}:{port}"

        cfg = dict(cfg)
        cfg["KEYWAY_HOST"] = self.host
        cfg["KEYWAY_DESKTOP_MODE"] = "1"
        self.config = cfg

        for k, v in cfg.items():
            if k == "KEYWAY_PORT":
                # The actually-bound port goes to uvicorn directly (below);
                # writing it back here would persist a drifted port into
                # config.env on the next start and lose the user's preference.
                continue
            os.environ[k] = v
        # Ensure public base matches the bound port for admin URL display
        os.environ["KEYWAY_PUBLIC_BASE_URL"] = self.url
        return cfg

    def start(self) -> bool:
        if self.running:
            return True

        self.prepare_env()

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
            with _NO_PROXY_OPENER.open(f"{self.url}/health", timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False
