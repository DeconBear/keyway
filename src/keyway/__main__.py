"""CLI entry point: ``python -m keyway`` or ``keyway``."""

from __future__ import annotations

import uvicorn

from .config import load_settings


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        "keyway.app:create_app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level=settings.log_level,
        factory=True,
    )


if __name__ == "__main__":
    main()
