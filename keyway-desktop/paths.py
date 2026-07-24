"""Desktop app paths and persistent config under the user data directory.

Windows:  %APPDATA%/Keyway
macOS:    ~/Library/Application Support/Keyway
Linux:    ~/.local/share/Keyway
"""

from __future__ import annotations

import os
import secrets
import socket
import sys
from pathlib import Path


APP_NAME = "Keyway"
DEFAULT_PORT = 9233
CONFIG_FILENAME = "config.env"


def app_data_dir() -> Path:
    """Return the persistent application data directory (created if missing)."""
    override = os.environ.get("KEYWAY_DESKTOP_HOME", "").strip()
    if override:
        root = Path(override).expanduser()
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        root = Path(base) / APP_NAME
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        xdg = os.environ.get("XDG_DATA_HOME", "").strip()
        root = Path(xdg).expanduser() / APP_NAME if xdg else Path.home() / ".local" / "share" / APP_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def data_dir(root: Path | None = None) -> Path:
    d = (root or app_data_dir()) / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path(root: Path | None = None) -> Path:
    return (root or app_data_dir()) / CONFIG_FILENAME


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


def _write_env_file(path: Path, values: dict[str, str]) -> None:
    lines = [
        "# Keyway desktop persistent config — do not commit",
        f"KEYWAY_SECRET={values['KEYWAY_SECRET']}",
        f"KEYWAY_ADMIN_TOKEN={values['KEYWAY_ADMIN_TOKEN']}",
        f"KEYWAY_PORT={values['KEYWAY_PORT']}",
        f"KEYWAY_DATA_DIR={values['KEYWAY_DATA_DIR']}",
        "KEYWAY_HOST=127.0.0.1",
        "KEYWAY_DESKTOP_MODE=1",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_or_create_config(root: Path | None = None) -> dict[str, str]:
    """Load desktop config; generate and persist secrets on first run.

    Environment variables already set by the user take precedence and are
    written back into the config file so subsequent launches stay consistent.
    """
    root = root or app_data_dir()
    path = config_path(root)
    stored = _parse_env_file(path)
    dd = str(data_dir(root))

    secret = (
        os.environ.get("KEYWAY_SECRET", "").strip()
        or stored.get("KEYWAY_SECRET", "").strip()
        or secrets.token_urlsafe(48)
    )
    admin = (
        os.environ.get("KEYWAY_ADMIN_TOKEN", "").strip()
        or stored.get("KEYWAY_ADMIN_TOKEN", "").strip()
        or secrets.token_urlsafe(24)
    )
    port_raw = (
        os.environ.get("KEYWAY_PORT", "").strip()
        or stored.get("KEYWAY_PORT", "").strip()
        or str(DEFAULT_PORT)
    )
    try:
        preferred_port = max(1, min(65535, int(port_raw)))
    except ValueError:
        preferred_port = DEFAULT_PORT

    data_dir_val = os.environ.get("KEYWAY_DATA_DIR", "").strip() or stored.get("KEYWAY_DATA_DIR", "").strip() or dd
    Path(data_dir_val).mkdir(parents=True, exist_ok=True)

    values = {
        "KEYWAY_SECRET": secret,
        "KEYWAY_ADMIN_TOKEN": admin,
        "KEYWAY_PORT": str(preferred_port),
        "KEYWAY_DATA_DIR": data_dir_val,
        "KEYWAY_HOST": "127.0.0.1",
        "KEYWAY_DESKTOP_MODE": "1",
    }
    # Persist when new or when env overrode stored values
    if (
        not path.exists()
        or stored.get("KEYWAY_SECRET") != secret
        or stored.get("KEYWAY_ADMIN_TOKEN") != admin
        or stored.get("KEYWAY_PORT") != str(preferred_port)
        or stored.get("KEYWAY_DATA_DIR") != data_dir_val
    ):
        _write_env_file(path, values)
    return values


def port_is_free(host: str, port: int) -> bool:
    # A listener that answers connections means "not free" — on Windows a
    # second bind with SO_REUSEADDR would otherwise wrongly succeed.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        if probe.connect_ex((host, port)) == 0:
            return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def find_free_port(host: str = "127.0.0.1", preferred: int = DEFAULT_PORT, span: int = 50) -> int:
    """Return preferred if free, else the next free port in ``[preferred, preferred+span)``."""
    preferred = max(1, min(65535, preferred))
    for port in range(preferred, min(65536, preferred + span)):
        if port_is_free(host, port):
            return port
    # Last resort: OS-assigned ephemeral
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def windows_run_key_name() -> str:
    return "KeywayDesktop"


def get_autostart_command() -> str:
    """Command line used for Windows Run registry / startup."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    main = Path(__file__).resolve().parent / "main.py"
    # Prefer pythonw.exe so login autostart doesn't pop a console window.
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{exe}" "{main}"'


def is_autostart_enabled() -> bool:
    """True only when the Run key exists AND points at this installation."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_READ,
        ) as key:
            value, _ = winreg.QueryValueEx(key, windows_run_key_name())
            return str(value).strip() == get_autostart_command()
    except OSError:
        return False


def set_autostart(enabled: bool) -> bool:
    """Enable/disable Start with Windows (Windows only). Returns success."""
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            if enabled:
                winreg.SetValueEx(key, windows_run_key_name(), 0, winreg.REG_SZ, get_autostart_command())
            else:
                try:
                    winreg.DeleteValue(key, windows_run_key_name())
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
