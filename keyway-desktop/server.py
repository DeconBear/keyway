"""Keyway server subprocess manager.

Starts and stops ``python -m keyway`` as a child process, monitors its
stdout for the ready signal, and provides health check capability.

Config is inherited from the parent environment (``KEYWAY_SECRET``,
``KEYWAY_ADMIN_TOKEN``, ``KEYWAY_PORT``, ``KEYWAY_HOST``, etc.).
If ``KEYWAY_SECRET`` is not set, a dev secret is generated automatically.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

READY_MARKER = "running on"
START_TIMEOUT = 30  # seconds


def _keyway_root() -> Path:
    return Path(__file__).resolve().parents[1] / "src"


class ServerManager:
    """Manages the Keyway server subprocess lifecycle."""

    def __init__(self, host: str = "127.0.0.1", port: int = 9233) -> None:
        self.host = host
        self.port = port
        self.url = f"http://{host}:{port}"
        self._proc: subprocess.Popen | None = None

    @property
    def running(self) -> bool:
        if self._proc is None:
            return False
        return self._proc.poll() is None

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env.setdefault("KEYWAY_HOST", self.host)
        env.setdefault("KEYWAY_PORT", str(self.port))
        if not env.get("KEYWAY_SECRET"):
            env["KEYWAY_SECRET"] = secrets.token_urlsafe(48)
        if not env.get("KEYWAY_ADMIN_TOKEN"):
            env["KEYWAY_ADMIN_TOKEN"] = secrets.token_urlsafe(24)
        self._admin_token = env["KEYWAY_ADMIN_TOKEN"]
        return env

    @property
    def admin_token(self) -> str:
        if not hasattr(self, '_admin_token'):
            self._admin_token = self._env().get("KEYWAY_ADMIN_TOKEN", "")
        return self._admin_token

    def start(self) -> bool:
        """Start keyway server subprocess. Returns True if started successfully."""
        if self.running:
            return True

        root = _keyway_root()
        creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

        try:
            self._proc = subprocess.Popen(
                [sys.executable, "-m", "keyway"],
                cwd=str(root.parent),
                env=self._env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=creation_flags,
            )
        except Exception:
            return False

        # Wait for ready signal
        start = time.time()
        while time.time() - start < START_TIMEOUT:
            if self._proc.poll() is not None:
                return False
            line = self._proc.stdout.readline()  # type: ignore[union-attr]
            if READY_MARKER in line:
                return True
            if not line:
                time.sleep(0.1)
        return self.running

    def stop(self) -> None:
        if self._proc and self.running:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
        self._proc = None

    def is_healthy(self) -> bool:
        """Quick health check via HTTP GET /health."""
        if not self.running:
            return False
        import urllib.request
        try:
            with urllib.request.urlopen(f"{self.url}/health", timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False
