"""Symmetric encryption for at-rest-retrievable secrets (e.g. self-signed LLM
API keys that must be copyable at any time by the owner).

Keyed off ``settings.secret`` (KEYWAY_SECRET). When KEYWAY_SECRET is unset we
fall back to a known dev string so the feature degrades instead of crashing
— but production MUST set a strong random KEYWAY_SECRET (see ``.env.example``).

A stable Fernet key is derived from the secret via SHA-256 (no salt). This is
acceptable because KEYWAY_SECRET is a high-entropy operator-chosen value; the
goal is reversibility, not key stretching. ``hash_key`` in ``llm_keys.py`` is
unchanged and remains the fast auth-lookup path — encryption here only powers
on-demand plaintext retrieval.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


DEV_FALLBACK_SECRET = "keyway-dev-insecure-llm-key"


def is_dev_fallback(secret: str) -> bool:
    return not (secret or "").strip()


def _fernet(secret: str) -> Fernet:
    raw = hashlib.sha256((secret or DEV_FALLBACK_SECRET).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt_value(plaintext: str, secret: str) -> str:
    return _fernet(secret).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_value(token: str, secret: str) -> str:
    """Decrypt; raises ``InvalidToken`` on tamper or wrong key."""
    return _fernet(secret).decrypt(token.encode("ascii")).decode("utf-8")
