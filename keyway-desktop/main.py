"""Keyway Desktop — native window + tray app that runs a local Keyway server.

Features:
- Persists secret / admin token / DB under the user app-data directory
- Auto-picks a free loopback port when 9233 is busy
- Embedded webview loads the admin panel (desktop-login sets session cookie)
- System tray: show window, open in browser, start with Windows, quit
- Closing the window hides to tray; Quit from tray stops the server

Usage:
    python main.py
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
import webbrowser

import webview

from paths import is_autostart_enabled, set_autostart
from server import ServerManager

HOST = "127.0.0.1"
APP_ID = "keyway.desktop.v1"


def _get_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


_ICON_PATH = os.path.join(_get_base_dir(), "keyway.ico")


def _set_window_icon() -> None:
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
                if "Keyway" in buf.value and not found:
                    found = h
                    return False
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        ctypes.windll.user32.EnumWindows(WNDENUMPROC(_enum_cb), 0)
        hwnd = found
        if hwnd:
            hicon = ctypes.windll.user32.LoadImageW(0, _ICON_PATH, 1, 0, 0, 0x0010)
            if hicon:
                WM_SETICON = 0x0080
                ctypes.windll.user32.PostMessageW(hwnd, WM_SETICON, 1, hicon)
                ctypes.windll.user32.PostMessageW(hwnd, WM_SETICON, 0, hicon)
    except Exception:
        pass


class KeywayDesktop:
    def __init__(self) -> None:
        self.server = ServerManager(HOST)
        self._window: webview.Window | None = None
        self._polling = True
        self._tray = None
        self._quitting = False
        self._autostart = is_autostart_enabled()

    def _status_text(self) -> str:
        if self.server.running:
            return f"Keyway Admin — Running (:{self.server.port})"
        return "Keyway Admin — Server Stopped"

    def _poll_status(self) -> None:
        while self._polling:
            if self._window:
                try:
                    self._window.set_title(self._status_text())
                except Exception:
                    pass
            time.sleep(2)

    def _show_window(self) -> None:
        if self._window:
            try:
                self._window.show()
                self._window.restore()
            except Exception:
                pass

    def _hide_window(self) -> None:
        if self._window:
            try:
                self._window.hide()
            except Exception:
                pass

    def _open_browser(self) -> None:
        webbrowser.open(self.server.admin_url())

    def _toggle_autostart(self) -> None:
        self._autostart = not self._autostart
        set_autostart(self._autostart)
        # Rebuild tray menu so checkmark updates
        self._restart_tray()

    def _quit(self) -> None:
        self._quitting = True
        self._polling = False
        try:
            if self._tray is not None:
                self._tray.stop()
        except Exception:
            pass
        self.server.stop()
        if self._window:
            try:
                self._window.destroy()
            except Exception:
                pass

    def _on_closing(self) -> bool:
        """Window close → hide to tray when tray is available; else quit."""
        if self._quitting:
            return True
        if self._tray is None:
            self._quitting = True
            self._polling = False
            self.server.stop()
            return True
        self._hide_window()
        return False

    def _build_tray_menu(self):
        import pystray
        from pystray import MenuItem as Item

        return pystray.Menu(
            Item("Show Admin", lambda: self._show_window(), default=True),
            Item("Open in Browser", lambda: self._open_browser()),
            Item(
                "Start with Windows",
                lambda: self._toggle_autostart(),
                checked=lambda _: self._autostart,
                enabled=sys.platform == "win32",
            ),
            pystray.Menu.SEPARATOR,
            Item("Quit Keyway", lambda: self._quit()),
        )

    def _start_tray(self) -> None:
        try:
            import pystray
            from PIL import Image
        except ImportError:
            print("[desktop] pystray/Pillow not installed — tray disabled", flush=True)
            return

        if os.path.exists(_ICON_PATH):
            image = Image.open(_ICON_PATH)
        else:
            image = Image.new("RGB", (64, 64), color=(17, 17, 17))

        self._tray = pystray.Icon(
            "Keyway",
            image,
            "Keyway",
            menu=self._build_tray_menu(),
        )
        threading.Thread(target=self._tray.run, daemon=True).start()

    def _restart_tray(self) -> None:
        if self._tray is None:
            return
        try:
            self._tray.menu = self._build_tray_menu()
            self._tray.update_menu()
        except Exception:
            pass

    def run(self) -> None:
        _set_window_icon()
        print("[desktop] starting Keyway server...", flush=True)
        ok = self.server.start()
        if not ok:
            print("[desktop] WARNING: server failed to start.", flush=True)
        else:
            print(
                f"[desktop] listening on {self.server.url} "
                f"(data: {self.server.config.get('KEYWAY_DATA_DIR', '')})",
                flush=True,
            )

        url = self.server.admin_url()
        self._window = webview.create_window(
            self._status_text(),
            url,
            width=1100,
            height=750,
            min_size=(800, 600),
            confirm_close=False,
        )
        self._window.events.closing += self._on_closing

        threading.Thread(target=self._poll_status, daemon=True).start()
        threading.Thread(target=lambda: (time.sleep(1.5), _set_window_icon()), daemon=True).start()
        self._start_tray()

        webview.start()

        # Event loop ended (destroy / quit)
        self._quitting = True
        self._polling = False
        try:
            if self._tray is not None:
                self._tray.stop()
        except Exception:
            pass
        self.server.stop()
        print("[desktop] goodbye.", flush=True)


def main() -> None:
    # Ensure src/ is importable when running from a source checkout
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
    if root not in sys.path and os.path.isdir(root):
        sys.path.insert(0, root)
    KeywayDesktop().run()


if __name__ == "__main__":
    main()
