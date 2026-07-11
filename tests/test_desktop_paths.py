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
