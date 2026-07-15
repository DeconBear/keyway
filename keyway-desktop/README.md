# Keyway Desktop

Native Windows/macOS/Linux window that runs Keyway locally and opens the admin panel.

## Features

- Persists `KEYWAY_SECRET`, `KEYWAY_ADMIN_TOKEN`, and SQLite under the user data dir:
  - Windows: `%APPDATA%\Keyway`
  - macOS: `~/Library/Application Support/Keyway`
  - Linux: `~/.local/share/Keyway`
- Auto-picks a free loopback port when `9233` is busy
- System tray: Show Admin / Open in Browser / Start with Windows / Quit
- Closing the window hides to tray; **Quit** from the tray stops the server

## Run from source

```bash
# from repo root
pip install -e ".[dev]"
pip install -r keyway-desktop/requirements.txt
python keyway-desktop/main.py
```

Optional override for the data home:

```bash
set KEYWAY_DESKTOP_HOME=D:\keyway-data   # Windows
export KEYWAY_DESKTOP_HOME=/path/to/keyway-data
```

## Build (Windows)

```bash
pip install pyinstaller
cd keyway-desktop
pyinstaller Keyway.spec
# → dist/Keyway.exe
```

Double-click `Keyway.exe`. First launch creates `%APPDATA%\Keyway\config.env` and `data\keyway.db`.

## Notes

- Desktop mode always binds `127.0.0.1` (auth bypass never exposed on LAN).
- Admin opens via `/admin/desktop-login` so a session cookie is set even when desktop auth bypass is active.
- Upstream key pools and user-key quotas are served by the same in-process Keyway server; manage them in Admin → Providers → Keys / Self-issued API Keys. See [../tutorial/key-pool.md](../tutorial/key-pool.md).
- PyInstaller `Keyway.spec` includes `keyway.key_quota` and `keyway.ui_settings` in `hiddenimports` for packaged builds.
