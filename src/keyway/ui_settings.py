"""Persisted UI settings (language, etc.) stored under KEYWAY_DATA_DIR."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SUPPORTED_LANGUAGES = ("en", "zh")
DEFAULT_LANGUAGE = "en"


def default_settings() -> dict[str, Any]:
    return {
        "language": DEFAULT_LANGUAGE,
    }


def settings_path(data_dir: Path) -> Path:
    return Path(data_dir) / "ui_settings.json"


def load_ui_settings(data_dir: Path) -> dict[str, Any]:
    path = settings_path(data_dir)
    base = default_settings()
    if not path.exists():
        return base
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return base
    if not isinstance(raw, dict):
        return base
    lang = str(raw.get("language") or DEFAULT_LANGUAGE).strip().lower()
    if lang not in SUPPORTED_LANGUAGES:
        lang = DEFAULT_LANGUAGE
    base["language"] = lang
    return base


def save_ui_settings(data_dir: Path, patch: dict[str, Any]) -> dict[str, Any]:
    current = load_ui_settings(data_dir)
    if "language" in patch and patch["language"] is not None:
        lang = str(patch["language"]).strip().lower()
        if lang not in SUPPORTED_LANGUAGES:
            raise ValueError(f"unsupported language: {patch['language']}; use {', '.join(SUPPORTED_LANGUAGES)}")
        current["language"] = lang
    path = settings_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return current
