"""Keyway self-signed LLM API key generation and verification.

Format: db_sk_<32 url-safe chars>. The plaintext is shown ONCE at creation
time; only the sha256 hex digest is stored. The first 12 chars are kept
as `key_prefix` for display/identification.
"""

from __future__ import annotations

import hashlib
import secrets


def generate_key() -> str:
    return "db_sk_" + secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def key_prefix(key: str) -> str:
    return key[:12] + "..." if len(key) > 12 else key


def verify_key(key: str, key_hash: str) -> bool:
    return hash_key(key) == key_hash
