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

import os
import sys
import threading
import time
import webbrowser

import webview

from paths import is_autostart_enabled, set_autostart
from server import ServerManager
from win_icon import APP_ID, apply_icons_with_retry, set_app_id

HOST = "127.0.0.1"


def _get_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


_ICON_PATH = os.path.join(_get_base_dir(), "keyway.ico")
_LOGO_PNG = os.path.join(_get_base_dir(), "assets", "logo.png")
if not os.path.exists(_LOGO_PNG):
    _LOGO_PNG = os.path.join(_get_base_dir(), "logo.png")


class KeywayDesktop:
    def __init__(self) -> None:
        self.server = ServerManager(HOST)
        self._window: webview.Window | None = None
        self._polling = True
        self._tray = None
        self._quitting = False
        self._autostart = is_autostart_enabled()
        self._icons_started = threading.Event()

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

    def _on_shown(self) -> None:
        self._start_icon_thread()

    def _start_icon_thread(self) -> None:
        """Kick off the icon-apply worker exactly once (shown event and the
        unconditional fallback both call this)."""
        if self._icons_started.is_set():
            return
        self._icons_started.set()
        threading.Thread(
            target=apply_icons_with_retry,
            kwargs={
                "icon_path": _ICON_PATH,
                "png_path": _LOGO_PNG if os.path.exists(_LOGO_PNG) else None,
            },
            daemon=True,
        ).start()

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

        if os.path.exists(_LOGO_PNG):
            image = Image.open(_LOGO_PNG)
        elif os.path.exists(_ICON_PATH):
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

    def _server_error_html(self) -> str:
        """Fallback page shown when the embedded server fails to start."""
        admin_url = self.server.admin_url()
        return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Keyway</title>
<style>
  body {{ font-family: "Segoe UI", system-ui, sans-serif; background: #f6f7f9;
         color: #1f2329; display: flex; align-items: center; justify-content: center;
         min-height: 100vh; margin: 0; }}
  .card {{ background: #fff; border-radius: 12px; padding: 32px 36px; max-width: 520px;
           box-shadow: 0 4px 24px rgba(0,0,0,.08); }}
  h1 {{ font-size: 20px; margin: 0 0 12px; }}
  p, li {{ font-size: 14px; line-height: 1.7; color: #4b5563; }}
  code {{ background: #f3f4f6; padding: 1px 6px; border-radius: 4px; }}
  a.btn {{ display: inline-block; margin-top: 16px; padding: 10px 22px; border-radius: 8px;
           background: #2563eb; color: #fff; text-decoration: none; font-size: 14px; }}
  a.btn:hover {{ background: #1d4ed8; }}
</style></head><body>
  <div class="card">
    <h1>Keyway server failed to start</h1>
    <p>The embedded Keyway server did not come up on <code>{self.server.url}</code>. Common causes:</p>
    <ul>
      <li>Another Keyway instance (or another app) is already listening on the port</li>
      <li>A proxy/VPN is intercepting loopback connections</li>
      <li>The data directory is not writable</li>
    </ul>
    <p>If the server came up late (slow machine), retry below. Otherwise quit from the system tray and relaunch.</p>
    <a class="btn" href="{admin_url}">Retry</a>
  </div>
</body></html>"""

    def run(self) -> None:
        # Must run before any HWND is created so the taskbar uses our AppID.
        set_app_id(APP_ID)

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

        if ok:
            self._window = webview.create_window(
                self._status_text(),
                self.server.admin_url(),
                width=1100,
                height=750,
                min_size=(800, 600),
                confirm_close=False,
            )
        else:
            # Show an actionable error page instead of a dead URL.
            self._window = webview.create_window(
                "Keyway — Server Failed to Start",
                html=self._server_error_html(),
                width=900,
                height=640,
                min_size=(800, 600),
                confirm_close=False,
            )
        self._window.events.closing += self._on_closing
        try:
            self._window.events.shown += self._on_shown
        except Exception:
            self._on_shown()

        threading.Thread(target=self._poll_status, daemon=True).start()
        self._start_tray()
        # Fallback if the shown event never fires
        self._start_icon_thread()

        webview.start()

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
    set_app_id(APP_ID)
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
    if root not in sys.path and os.path.isdir(root):
        sys.path.insert(0, root)
    KeywayDesktop().run()


if __name__ == "__main__":
    main()
