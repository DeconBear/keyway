"""Tests for Keyway desktop paths / persistent config / port picking."""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest

DESKTOP = Path(__file__).resolve().parents[1] / "keyway-desktop"
if str(DESKTOP) not in sys.path:
    sys.path.insert(0, str(DESKTOP))

from paths import (  # noqa: E402
    DEFAULT_PORT,
    app_data_dir,
    config_path,
    find_free_port,
    load_or_create_config,
    port_is_free,
)


@pytest.fixture()
def desktop_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "KeywayHome"
    monkeypatch.setenv("KEYWAY_DESKTOP_HOME", str(home))
    for k in ("KEYWAY_SECRET", "KEYWAY_ADMIN_TOKEN", "KEYWAY_PORT", "KEYWAY_DATA_DIR"):
        monkeypatch.delenv(k, raising=False)
    return home


def test_app_data_dir_respects_override(desktop_home: Path) -> None:
    root = app_data_dir()
    assert root == desktop_home
    assert root.is_dir()


def test_load_or_create_config_persists_and_reuses(desktop_home: Path) -> None:
    cfg1 = load_or_create_config()
    assert cfg1["KEYWAY_SECRET"]
    assert cfg1["KEYWAY_ADMIN_TOKEN"]
    assert Path(cfg1["KEYWAY_DATA_DIR"]).is_dir()
    assert config_path().exists()

    cfg2 = load_or_create_config()
    assert cfg2["KEYWAY_SECRET"] == cfg1["KEYWAY_SECRET"]
    assert cfg2["KEYWAY_ADMIN_TOKEN"] == cfg1["KEYWAY_ADMIN_TOKEN"]
    assert cfg2["KEYWAY_DATA_DIR"] == cfg1["KEYWAY_DATA_DIR"]


def test_load_or_create_config_env_override(desktop_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    load_or_create_config()
    monkeypatch.setenv("KEYWAY_SECRET", "override-secret-value-32chars-xxxx")
    monkeypatch.setenv("KEYWAY_ADMIN_TOKEN", "override-admin-token")
    cfg = load_or_create_config()
    assert cfg["KEYWAY_SECRET"] == "override-secret-value-32chars-xxxx"
    assert cfg["KEYWAY_ADMIN_TOKEN"] == "override-admin-token"
    # persisted
    text = config_path().read_text(encoding="utf-8")
    assert "override-secret-value-32chars-xxxx" in text


def test_find_free_port_skips_busy(desktop_home: Path) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    busy = int(sock.getsockname()[1])
    try:
        assert not port_is_free("127.0.0.1", busy)
        free = find_free_port("127.0.0.1", preferred=busy, span=20)
        assert free != busy
        assert port_is_free("127.0.0.1", free)
    finally:
        sock.close()


def test_find_free_port_prefers_default_when_free() -> None:
    if port_is_free("127.0.0.1", DEFAULT_PORT):
        assert find_free_port("127.0.0.1", preferred=DEFAULT_PORT, span=5) == DEFAULT_PORT


# ---------- Regression: desktop fixes ----------

def test_port_is_free_detects_listener() -> None:
    """A bound+listening socket must read as busy even on Windows, where a
    second bind with SO_REUSEADDR could otherwise wrongly succeed."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    busy = int(sock.getsockname()[1])
    try:
        assert not port_is_free("127.0.0.1", busy)
    finally:
        sock.close()


def test_prepare_env_does_not_persist_drifted_port(desktop_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the preferred port is busy the server drifts to a free one, but
    that drift must not be written back to KEYWAY_PORT in the environment
    (otherwise it gets persisted into config.env on the next start)."""
    from server import ServerManager

    saved_env = dict(os.environ)  # prepare_env mutates os.environ directly
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    busy = int(sock.getsockname()[1])
    try:
        monkeypatch.setenv("KEYWAY_PORT", str(busy))
        mgr = ServerManager("127.0.0.1")
        mgr.prepare_env()
        assert mgr.port != busy, "should drift to a free port"
        assert os.environ.get("KEYWAY_PORT") == str(busy), "preferred port must stay stable in env"
    finally:
        sock.close()
        os.environ.clear()
        os.environ.update(saved_env)


def test_health_check_bypasses_system_proxy() -> None:
    import server as desktop_server
    import urllib.request

    # The opener must not carry any ProxyHandler with real (env/registry)
    # proxies, so loopback health checks can never be routed via a proxy.
    opener = desktop_server._NO_PROXY_OPENER
    proxy_handlers = [h for h in opener.handlers if isinstance(h, urllib.request.ProxyHandler)]
    assert all(not h.proxies for h in proxy_handlers)


def test_win_icon_public_api_importable() -> None:
    """win_icon must import cleanly and expose no-op-safe public functions
    regardless of platform."""
    import win_icon

    assert callable(win_icon.set_app_id)
    assert callable(win_icon.apply_window_icons)
    assert callable(win_icon.apply_icons_with_retry)
    if not win_icon.IS_WINDOWS:
        assert win_icon.apply_window_icons("nonexistent.ico") == 0
        win_icon.set_app_id()  # must not raise


def test_autostart_command_prefers_pythonw(monkeypatch: pytest.MonkeyPatch) -> None:
    import paths as desktop_paths

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    cmd = desktop_paths.get_autostart_command()
    assert "main.py" in cmd
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if pythonw.exists():
        assert "pythonw.exe" in cmd, "autostart should not pop a console window"


def test_is_autostart_enabled_validates_command(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stale Run-key entry pointing at another install must NOT read as enabled."""
    import paths as desktop_paths

    if sys.platform != "win32":
        pytest.skip("windows-only")

    class _FakeKey:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    fake_winreg = type(sys)("winreg")
    fake_winreg.HKEY_CURRENT_USER = object()
    fake_winreg.KEY_READ = 0
    fake_winreg.OpenKey = lambda *a, **k: _FakeKey()
    fake_winreg.QueryValueEx = lambda key, name: ('"C:\\old\\other.exe" --foo', 1)
    monkeypatch.setitem(sys.modules, "winreg", fake_winreg)

    assert desktop_paths.is_autostart_enabled() is False
