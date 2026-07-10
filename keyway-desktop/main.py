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

import ctypes
import os
import sys
import threading
import time

import webview

from server import ServerManager

HOST = "127.0.0.1"
PORT = 9233
URL = f"http://{HOST}:{PORT}"

# App identity — used for the Windows taskbar icon and window class
APP_ID = "keyway.desktop.v1"


def _get_base_dir() -> str:
    """Return the directory containing bundled assets.

    Works both in development (__file__-based) and inside a PyInstaller
    one-file or one-folder bundle (sys._MEIPASS).
    """
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


_ICON_PATH = os.path.join(_get_base_dir(), "keyway.ico")


def _set_window_icon() -> None:
    """Set the window icon to the bundled keyway.ico. Safe to call from any thread."""
    if sys.platform != "win32" or not os.path.exists(_ICON_PATH):
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        pid = os.getpid()
        found = None

        def _enum_cb(h: int, _: int) -> bool:
            nonlocal found
            import ctypes.wintypes
            proc_id = ctypes.wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(h, ctypes.byref(proc_id))
            if proc_id.value == pid and ctypes.windll.user32.IsWindowVisible(h):
                buf = ctypes.create_unicode_buffer(256)
                ctypes.windll.user32.GetWindowTextW(h, buf, 255)
                if "Keyway Admin" in buf.value and not found:
                    found = h
                    return False
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        ctypes.windll.user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)
        hwnd = found

        if hwnd:
            hicon = ctypes.windll.user32.LoadImageW(0, _ICON_PATH, 1, 0, 0, 0x0010)
            if hicon:
                # PostMessageW works cross-thread (unlike SendMessageW)
                WM_SETICON = 0x0080
                ctypes.windll.user32.PostMessageW(hwnd, WM_SETICON, 1, hicon)  # ICON_BIG
                ctypes.windll.user32.PostMessageW(hwnd, WM_SETICON, 0, hicon)  # ICON_SMALL
    except Exception:
        pass


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
        _set_window_icon()
        print("[desktop] starting Keyway server...")
        ok = self._start_server()
        if not ok:
            print("[desktop] WARNING: server failed to start. Admin panel may show 502.", flush=True)

        url = f"http://{HOST}:{PORT}/admin.html"

        self._window = webview.create_window(
            "Keyway Admin — Starting...",
            url,
            width=1100,
            height=750,
            min_size=(800, 600),
            confirm_close=True,
        )

        # Start status polling thread
        t = threading.Thread(target=self._poll_status, daemon=True)
        t.start()

        # Icon setter — runs after window is fully on-screen
        threading.Thread(target=lambda: (time.sleep(2), _set_window_icon()), daemon=True).start()

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
