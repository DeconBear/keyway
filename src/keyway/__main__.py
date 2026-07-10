"""CLI entry point: ``python -m keyway`` or ``keyway``."""

from __future__ import annotations

import os

import uvicorn

from .config import load_settings

_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
_TRUE = {"1", "true", "yes", "on", "y"}


def main() -> None:
    settings = load_settings()
    host = settings.host
    desktop_mode = os.getenv("KEYWAY_DESKTOP_MODE", "").strip().lower() in _TRUE
    if desktop_mode and host.strip().lower() not in _LOOPBACK:
        host = "127.0.0.1"
        os.environ["KEYWAY_HOST"] = host
    uvicorn.run(
        "keyway.app:create_app",
        host=host,
        port=settings.port,
        reload=False,
        log_level=settings.log_level,
        factory=True,
    )


if __name__ == "__main__":
    main()
