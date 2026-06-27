"""Keyway configuration loader. Reads from environment / .env file."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


TRUE_VALUES = {"1", "true", "yes", "on", "y"}


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in TRUE_VALUES


def _parse_int(value: str | None, default: int, minimum: int) -> int:
    if value is None or value.strip() == "":
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(minimum, parsed)


def _parse_csv(value: str | None, default: Iterable[str]) -> list[str]:
    if value is None:
        return list(default)
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items if items else list(default)


def load_dotenv(dotenv_path: Path) -> None:
    """Read a local .env file (does not overwrite existing env vars)."""
    if not dotenv_path.exists():
        return
    for raw in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(slots=True)
class Settings:
    host: str
    port: int
    log_level: str
    admin_token: str
    secret: str
    data_dir: Path
    cors_origins: list[str]
    public_base_url: str


def _find_env_file() -> Path:
    """Look for .env in CWD, then in the package parent, then in ~/.keyway."""
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[2] / ".env",
    ]
    for c in candidates:
        if c.exists():
            return c
    return Path.cwd() / ".env"  # may not exist; load_dotenv handles that


def load_settings() -> Settings:
    load_dotenv(_find_env_file())

    host = os.getenv("KEYWAY_HOST", "127.0.0.1")
    port = _parse_int(os.getenv("KEYWAY_PORT"), 9233, 1)
    log_level = os.getenv("KEYWAY_LOG_LEVEL", "info")

    admin_token = os.getenv("KEYWAY_ADMIN_TOKEN", "").strip()
    secret = os.getenv("KEYWAY_SECRET", "").strip()

    data_dir_raw = os.getenv("KEYWAY_DATA_DIR", "").strip()
    if data_dir_raw:
        data_dir = Path(data_dir_raw).expanduser()
    else:
        data_dir = Path.cwd() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    cors_origins = _parse_csv(
        os.getenv("KEYWAY_CORS_ORIGINS"),
        [f"http://127.0.0.1:{port}", f"http://localhost:{port}"],
    )

    public_base_url = os.getenv("KEYWAY_PUBLIC_BASE_URL", "").strip()

    return Settings(
        host=host,
        port=port,
        log_level=log_level,
        admin_token=admin_token,
        secret=secret,
        data_dir=data_dir,
        cors_origins=cors_origins,
        public_base_url=public_base_url,
    )
