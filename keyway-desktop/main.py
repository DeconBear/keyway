"""Keyway Desktop — native window app that runs a local Keyway server.

Features:
- Auto-starts the Keyway server on launch
- Embedded webview window loads the admin panel at http://localhost:{port}/
- Window title shows server status in real time
- Clean shutdown on close — stops the server subprocess

Usage:
    python main.py
"""

from __future__ import annotations

import threading
import time

import webview

from server import ServerManager

HOST = "127.0.0.1"
PORT = 9233
URL = f"http://{HOST}:{PORT}"


class KeywayDesktop:
    def __init__(self) -> None:
        self.server = ServerManager(HOST, PORT)
        self._window: webview.Window | None = None
        self._polling = True

    def _start_server(self) -> bool:
        if self.server.running:
            return True
        return self.server.start()

    def _stop_server(self) -> None:
        self.server.stop()

    def _status_text(self) -> str:
        if self.server.running:
            return "Keyway Admin — Server Running"
        return "Keyway Admin — Server Stopped"

    def _poll_status(self) -> None:
        """Background thread: updates window title every 2 seconds."""
        while self._polling:
            if self._window:
                try:
                    self._window.set_title(self._status_text())
                except Exception:
                    pass
            time.sleep(2)

    def _on_closing(self) -> None:
        self._polling = False
        self._stop_server()

    def run(self) -> None:
        print("[desktop] starting Keyway server...")
        ok = self._start_server()
        if not ok:
            print("[desktop] WARNING: server failed to start. Admin panel may show 502.", flush=True)

        # Build the window
        self._window = webview.create_window(
            "Keyway Admin — Starting...",
            URL,
            width=1100,
            height=750,
            min_size=(800, 600),
            confirm_close=True,
        )

        # Start status polling thread
        t = threading.Thread(target=self._poll_status, daemon=True)
        t.start()

        # Blocking start — runs the webview event loop
        webview.start()

        # After window closes
        self._on_closing()
        print("[desktop] goodbye.")


def main() -> None:
    app = KeywayDesktop()
    app.run()


if __name__ == "__main__":
    main()
