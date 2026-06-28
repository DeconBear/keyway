"""LLM Router data layer (grouped): 8 tables
(llm_groups / llm_providers / model_routes / route_providers /
llm_api_keys / llm_tool_providers / llm_request_logs / provider_health) + CRUD.
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from . import crypto


DEFAULT_GROUP_ID = "default"
DEFAULT_GROUP_NAME = "Default Group"
VALID_MODES = ("direct", "auto-select", "adapter", "fusion")
CIRCUIT_FAIL_THRESHOLD = 3
CIRCUIT_OPEN_SECONDS = 60


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LLMStore:
    def __init__(self, db_path: Path, secret: str = "") -> None:
        self._db_path = db_path
        self._secret = secret
        self._lock = Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init_schema()
        self._ensure_default_group()

    def close(self) -> None:
        self._conn.close()

    # ---- at-rest secret encryption helpers ----
    # Provider/tool api_keys are encrypted with KEYWAY_SECRET (Fernet via
    # crypto.py). When no secret is configured these degrade to plaintext
    # passthrough. _dec_api_key is tolerant: a value that fails to decrypt
    # is returned as-is, so databases partway through the
    # plaintext->ciphertext migration still read.
    def _enc_api_key(self, plaintext: str) -> str:
        if not plaintext or crypto.is_dev_fallback(self._secret):
            return plaintext
        return crypto.encrypt_value(plaintext, self._secret)

    def _dec_api_key(self, value: str) -> str:
        if not value or crypto.is_dev_fallback(self._secret):
            return value
        try:
            return crypto.decrypt_value(value, self._secret)
        except Exception:
            return value

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS llm_groups (
                    group_id   TEXT PRIMARY KEY,
                    name       TEXT NOT NULL,
                    enabled    INTEGER NOT NULL DEFAULT 1,
                    note       TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS llm_providers (
                    provider_id TEXT PRIMARY KEY,
                    group_id    TEXT NOT NULL DEFAULT 'default',
                    name        TEXT NOT NULL,
                    base_url    TEXT NOT NULL,
                    api_key     TEXT NOT NULL,
                    protocol    TEXT NOT NULL DEFAULT 'openai',
                    enabled     INTEGER NOT NULL DEFAULT 1,
                    note        TEXT NOT NULL DEFAULT '',
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL,
                    FOREIGN KEY (group_id) REFERENCES llm_groups(group_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS model_routes (
                    route_id       TEXT PRIMARY KEY,
                    group_id       TEXT NOT NULL DEFAULT 'default',
                    alias          TEXT NOT NULL,
                    provider_id    TEXT NOT NULL,
                    upstream_model TEXT NOT NULL,
                    upstream_path  TEXT NOT NULL DEFAULT '',
                    enabled        INTEGER NOT NULL DEFAULT 1,
                    note           TEXT NOT NULL DEFAULT '',
                    created_at     TEXT NOT NULL,
                    updated_at     TEXT NOT NULL,
                    FOREIGN KEY (group_id)    REFERENCES llm_groups(group_id) ON DELETE CASCADE,
                    FOREIGN KEY (provider_id) REFERENCES llm_providers(provider_id) ON DELETE CASCADE,
                    UNIQUE (group_id, alias)
                );

                CREATE TABLE IF NOT EXISTS llm_api_keys (
                    key_id         TEXT PRIMARY KEY,
                    group_id       TEXT NOT NULL DEFAULT 'default',
                    key_hash       TEXT UNIQUE NOT NULL,
                    key_prefix     TEXT NOT NULL,
                    name           TEXT NOT NULL,
                    owner_user_id  TEXT,
                    enabled        INTEGER NOT NULL DEFAULT 1,
                    expires_at     TEXT,
                    last_used_at   TEXT,
                    created_at     TEXT NOT NULL,
                    key_encrypted  TEXT,
                    FOREIGN KEY (group_id) REFERENCES llm_groups(group_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS llm_tool_providers (
                    tool_id    TEXT PRIMARY KEY,
                    group_id   TEXT NOT NULL DEFAULT 'default',
                    name       TEXT NOT NULL,
                    api_key    TEXT NOT NULL,
                    config     TEXT NOT NULL DEFAULT '{}',
                    enabled    INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (group_id) REFERENCES llm_groups(group_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS llm_request_logs (
                    log_id          TEXT PRIMARY KEY,
                    group_id        TEXT NOT NULL DEFAULT 'default',
                    api_key_id      TEXT,
                    route_alias     TEXT,
                    provider_id     TEXT,
                    upstream_model  TEXT,
                    status_code     INTEGER,
                    request_tokens  INTEGER,
                    response_tokens INTEGER,
                    latency_ms      INTEGER,
                    error           TEXT NOT NULL DEFAULT '',
                    created_at      TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS route_providers (
                    rp_id          TEXT PRIMARY KEY,
                    route_id       TEXT NOT NULL,
                    provider_id    TEXT NOT NULL,
                    upstream_model TEXT NOT NULL,
                    priority       INTEGER NOT NULL DEFAULT 0,
                    enabled        INTEGER NOT NULL DEFAULT 1,
                    created_at     TEXT NOT NULL,
                    FOREIGN KEY (route_id)    REFERENCES model_routes(route_id) ON DELETE CASCADE,
                    FOREIGN KEY (provider_id) REFERENCES llm_providers(provider_id) ON DELETE CASCADE,
                    UNIQUE (route_id, provider_id)
                );

                CREATE TABLE IF NOT EXISTS provider_health (
                    provider_id        TEXT PRIMARY KEY,
                    group_id           TEXT NOT NULL DEFAULT 'default',
                    consecutive_fails  INTEGER NOT NULL DEFAULT 0,
                    last_fail_at       TEXT,
                    last_success_at    TEXT,
                    circuit_open       INTEGER NOT NULL DEFAULT 0,
                    circuit_open_until TEXT,
                    FOREIGN KEY (provider_id) REFERENCES llm_providers(provider_id) ON DELETE CASCADE
                );
                """
            )
        self._ensure_column("llm_providers", "group_id", "TEXT NOT NULL DEFAULT 'default'")
        self._ensure_column("llm_providers", "protocol", "TEXT NOT NULL DEFAULT 'openai'")
        self._ensure_column("model_routes", "group_id", "TEXT NOT NULL DEFAULT 'default'")
        self._ensure_column("model_routes", "upstream_path", "TEXT NOT NULL DEFAULT ''")
        self._ensure_column("model_routes", "mode", "TEXT NOT NULL DEFAULT 'direct'")
        self._ensure_column("model_routes", "adapter_config", "TEXT NOT NULL DEFAULT '{}'")
        self._ensure_column("model_routes", "fusion_config", "TEXT NOT NULL DEFAULT '{}'")
        self._ensure_column("llm_api_keys", "group_id", "TEXT NOT NULL DEFAULT 'default'")
        self._ensure_column("llm_api_keys", "key_encrypted", "TEXT")
        self._ensure_column("llm_tool_providers", "group_id", "TEXT NOT NULL DEFAULT 'default'")
        self._ensure_column("llm_request_logs", "group_id", "TEXT NOT NULL DEFAULT 'default'")
        self._ensure_column("llm_request_logs", "fusion_id", "TEXT")
        self._ensure_index("idx_llm_providers_group", "llm_providers(group_id)")
        self._ensure_index("idx_model_routes_group", "model_routes(group_id)")
        self._ensure_index("idx_model_routes_alias_group", "model_routes(alias, group_id)")
        self._ensure_index("idx_llm_api_keys_group", "llm_api_keys(group_id)")
        self._ensure_index("idx_llm_tool_providers_group", "llm_tool_providers(group_id)")
        self._ensure_index("idx_logs_group_created", "llm_request_logs(group_id, created_at DESC)")
        self._ensure_index("idx_logs_key", "llm_request_logs(api_key_id, created_at DESC)")
        self._ensure_index("idx_logs_created", "llm_request_logs(created_at DESC)")
        self._ensure_index("idx_route_providers_route", "route_providers(route_id, priority)")
        self._ensure_index("idx_provider_health_group", "provider_health(group_id)")

    def _ensure_column(self, table: str, column: str, decl: str) -> None:
        cols = {row["name"] for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            with self._conn:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

    def _ensure_index(self, name: str, definition: str) -> None:
        with self._conn:
            self._conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {definition}")

    def _ensure_default_group(self) -> None:
        row = self._conn.execute(
            "SELECT 1 FROM llm_groups WHERE group_id = ?", (DEFAULT_GROUP_ID,)
        ).fetchone()
        if row:
            return
        now = _utc_now_iso()
        with self._conn:
            self._conn.execute(
                "INSERT INTO llm_groups (group_id, name, enabled, note, created_at, updated_at) "
                "VALUES (?, ?, 1, '', ?, ?)",
                (DEFAULT_GROUP_ID, DEFAULT_GROUP_NAME, now, now),
            )

    # ---------- groups ----------
    def list_groups(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT group_id, name, enabled, note, created_at, updated_at "
            "FROM llm_groups ORDER BY created_at ASC"
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            gid = d["group_id"]
            d["provider_count"] = self._conn.execute(
                "SELECT COUNT(*) FROM llm_providers WHERE group_id = ?", (gid,)
            ).fetchone()[0]
            d["route_count"] = self._conn.execute(
                "SELECT COUNT(*) FROM model_routes WHERE group_id = ?", (gid,)
            ).fetchone()[0]
            d["key_count"] = self._conn.execute(
                "SELECT COUNT(*) FROM llm_api_keys WHERE group_id = ?", (gid,)
            ).fetchone()[0]
            d["tool_count"] = self._conn.execute(
                "SELECT COUNT(*) FROM llm_tool_providers WHERE group_id = ?", (gid,)
            ).fetchone()[0]
            result.append(d)
        return result

    def get_group(self, group_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT group_id, name, enabled, note, created_at, updated_at "
            "FROM llm_groups WHERE group_id = ?",
            (group_id,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        gid = d["group_id"]
        d["provider_count"] = self._conn.execute(
            "SELECT COUNT(*) FROM llm_providers WHERE group_id = ?", (gid,)
        ).fetchone()[0]
        d["route_count"] = self._conn.execute(
            "SELECT COUNT(*) FROM model_routes WHERE group_id = ?", (gid,)
        ).fetchone()[0]
        d["key_count"] = self._conn.execute(
            "SELECT COUNT(*) FROM llm_api_keys WHERE group_id = ?", (gid,)
        ).fetchone()[0]
        d["tool_count"] = self._conn.execute(
            "SELECT COUNT(*) FROM llm_tool_providers WHERE group_id = ?", (gid,)
        ).fetchone()[0]
        return d

    def create_group(self, group_id: str, name: str, note: str = "") -> dict[str, Any]:
        if not group_id or not group_id.strip():
            raise ValueError("group_id cannot be empty")
        if not name or not name.strip():
            raise ValueError("name cannot be empty")
        now = _utc_now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO llm_groups (group_id, name, enabled, note, created_at, updated_at) "
                "VALUES (?, ?, 1, ?, ?, ?)",
                (group_id, name, note, now, now),
            )
        return self.get_group(group_id)  # type: ignore[return-value]

    def update_group(self, group_id: str, name: str | None = None,
                    enabled: bool | None = None, note: str | None = None) -> dict[str, Any] | None:
        sets: list[str] = []
        vals: list[Any] = []
        if name is not None:
            sets.append("name = ?"); vals.append(name)
        if enabled is not None:
            sets.append("enabled = ?"); vals.append(1 if enabled else 0)
        if note is not None:
            sets.append("note = ?"); vals.append(note)
        if not sets:
            return self.get_group(group_id)
        sets.append("updated_at = ?"); vals.append(_utc_now_iso())
        vals.append(group_id)
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE llm_groups SET {', '.join(sets)} WHERE group_id = ?", tuple(vals)
            )
        return self.get_group(group_id)

    def delete_group(self, group_id: str) -> bool:
        if group_id == DEFAULT_GROUP_ID:
            raise ValueError("default group cannot be deleted")
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM llm_groups WHERE group_id = ?", (group_id,))
            return cur.rowcount > 0

    def copy_group(self, src_group_id: str, new_group_id: str, new_name: str,
                  plaintext_for_key, hash_for_key, encrypt_for_key,
                  key_prefix_for_key) -> dict[str, Any]:
        if not new_group_id or not new_group_id.strip():
            raise ValueError("new_group_id cannot be empty")
        if not new_name or not new_name.strip():
            raise ValueError("new_name cannot be empty")
        if self.get_group(src_group_id) is None:
            raise ValueError(f"source group not found: {src_group_id}")
        if self.get_group(new_group_id) is not None:
            raise ValueError(f"target group_id already exists: {new_group_id}")

        now = _utc_now_iso()
        issued_keys: list[dict[str, Any]] = []

        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO llm_groups (group_id, name, enabled, note, created_at, updated_at) "
                "VALUES (?, ?, 1, '', ?, ?)",
                (new_group_id, new_name, now, now),
            )

            provider_id_map: dict[str, str] = {}
            for prov_row in self._conn.execute(
                "SELECT * FROM llm_providers WHERE group_id = ?", (src_group_id,)
            ).fetchall():
                prov = dict(prov_row)
                new_pid = f"{new_group_id}.{prov['provider_id']}"
                provider_id_map[prov["provider_id"]] = new_pid
                self._conn.execute(
                    "INSERT INTO llm_providers "
                    "(provider_id, group_id, name, base_url, api_key, protocol, enabled, note, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (new_pid, new_group_id, prov["name"], prov["base_url"],
                     self._enc_api_key(self._dec_api_key(prov["api_key"])),
                     prov.get("protocol", "openai"),
                     prov["enabled"], prov.get("note", ""), now, now),
                )

            route_id_map: dict[str, str] = {}
            for r_row in self._conn.execute(
                "SELECT * FROM model_routes WHERE group_id = ?", (src_group_id,)
            ).fetchall():
                r = dict(r_row)
                new_pid = provider_id_map.get(r["provider_id"], r["provider_id"])
                new_route_id = uuid.uuid4().hex
                route_id_map[r["route_id"]] = new_route_id
                self._conn.execute(
                    "INSERT INTO model_routes "
                    "(route_id, group_id, alias, provider_id, upstream_model, upstream_path, "
                    " enabled, note, created_at, updated_at, mode, adapter_config, fusion_config) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (new_route_id, new_group_id, r["alias"], new_pid,
                     r["upstream_model"], r.get("upstream_path", ""),
                     r["enabled"], r.get("note", ""), now, now,
                     r.get("mode", "direct"), r.get("adapter_config", "{}"),
                     r.get("fusion_config", "{}")),
                )

            # Copy route_providers associations into the new group
            for rp_row in self._conn.execute(
                "SELECT rp.* FROM route_providers rp "
                "JOIN model_routes r ON rp.route_id = r.route_id "
                "WHERE r.group_id = ?",
                (src_group_id,),
            ).fetchall():
                rp = dict(rp_row)
                self._conn.execute(
                    "INSERT INTO route_providers "
                    "(rp_id, route_id, provider_id, upstream_model, priority, enabled, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (uuid.uuid4().hex, route_id_map.get(rp["route_id"], rp["route_id"]),
                     provider_id_map.get(rp["provider_id"], rp["provider_id"]),
                     rp["upstream_model"], rp["priority"], rp["enabled"], now),
                )

            for t_row in self._conn.execute(
                "SELECT * FROM llm_tool_providers WHERE group_id = ?", (src_group_id,)
            ).fetchall():
                t = dict(t_row)
                new_tid = f"{new_group_id}.{t['tool_id']}"
                self._conn.execute(
                    "INSERT INTO llm_tool_providers "
                    "(tool_id, group_id, name, api_key, config, enabled, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (new_tid, new_group_id, t["name"],
                     self._enc_api_key(self._dec_api_key(t["api_key"])),
                     t["config"], t["enabled"], now, now),
                )

            for k in self._conn.execute(
                "SELECT * FROM llm_api_keys WHERE group_id = ?", (src_group_id,)
            ).fetchall():
                plaintext = plaintext_for_key()
                new_key_id = uuid.uuid4().hex
                key_hash = hash_for_key(plaintext)
                key_prefix = key_prefix_for_key(plaintext)
                key_encrypted = encrypt_for_key(plaintext)
                self._conn.execute(
                    "INSERT INTO llm_api_keys "
                    "(key_id, group_id, key_hash, key_prefix, name, owner_user_id, "
                    " enabled, expires_at, last_used_at, created_at, key_encrypted) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
                    (new_key_id, new_group_id, key_hash, key_prefix, k["name"],
                     k["owner_user_id"], k["enabled"], k["expires_at"], now,
                     key_encrypted),
                )
                issued_keys.append({
                    "key_id": new_key_id,
                    "name": k["name"],
                    "plaintext": plaintext,
                    "key_prefix": key_prefix,
                })

        new_group = self.get_group(new_group_id)
        new_group["issued_keys"] = issued_keys  # type: ignore[index]
        return new_group

    # ---------- providers (flat + grouped) ----------
    def list_providers(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT provider_id, group_id, name, base_url, api_key, protocol, enabled, note, created_at, updated_at "
            "FROM llm_providers ORDER BY created_at ASC"
        ).fetchall()
        return [self._mask_provider(r) for r in rows]

    def list_providers_in_group(self, group_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT provider_id, group_id, name, base_url, api_key, protocol, enabled, note, created_at, updated_at "
            "FROM llm_providers WHERE group_id = ? ORDER BY created_at ASC",
            (group_id,),
        ).fetchall()
        return [self._mask_provider(r) for r in rows]

    def get_provider(self, provider_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT provider_id, group_id, name, base_url, api_key, protocol, enabled, note, created_at, updated_at "
            "FROM llm_providers WHERE provider_id = ?",
            (provider_id,),
        ).fetchone()
        return self._mask_provider(row) if row else None

    def get_provider_with_key(self, provider_id: str) -> dict[str, Any] | None:
        """Internal use (router/owner-reveal): returns the row INCLUDING the
        decrypted real api_key."""
        row = self._conn.execute(
            "SELECT * FROM llm_providers WHERE provider_id = ?", (provider_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["api_key"] = self._dec_api_key(d.get("api_key", ""))
        return d

    def get_provider_with_key_in_group(self, provider_id: str, group_id: str) -> dict[str, Any] | None:
        """Internal use (router/owner-reveal): returns the row INCLUDING the
        decrypted real api_key, constrained to the given group."""
        row = self._conn.execute(
            "SELECT * FROM llm_providers WHERE provider_id = ? AND group_id = ?",
            (provider_id, group_id),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["api_key"] = self._dec_api_key(d.get("api_key", ""))
        return d

    def create_provider(self, provider_id: str, name: str, base_url: str, api_key: str, note: str = "") -> dict[str, Any]:
        now = _utc_now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO llm_providers (provider_id, group_id, name, base_url, api_key, enabled, note, created_at, updated_at) "
                "VALUES (?, 'default', ?, ?, ?, 1, ?, ?, ?)",
                (provider_id, name, base_url, self._enc_api_key(api_key), note, now, now),
            )
        return self.get_provider(provider_id)  # type: ignore[return-value]

    def create_provider_in_group(self, group_id: str, provider_id: str, name: str, base_url: str,
                                  api_key: str, protocol: str = "openai", note: str = "") -> dict[str, Any]:
        if not self.get_group(group_id):
            raise ValueError(f"group not found: {group_id}")
        now = _utc_now_iso()
        proto = protocol if protocol in ("openai", "anthropic") else "openai"
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO llm_providers (provider_id, group_id, name, base_url, api_key, protocol, enabled, note, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?)",
                (provider_id, group_id, name, base_url, self._enc_api_key(api_key), proto, note, now, now),
            )
        return self.get_provider(provider_id)  # type: ignore[return-value]

    def update_provider(self, provider_id: str, name: str | None = None, base_url: str | None = None,
                       api_key: str | None = None, enabled: bool | None = None, note: str | None = None) -> dict[str, Any] | None:
        sets: list[str] = []
        vals: list[Any] = []
        if name is not None:
            sets.append("name = ?"); vals.append(name)
        if base_url is not None:
            sets.append("base_url = ?"); vals.append(base_url)
        if api_key is not None:
            sets.append("api_key = ?"); vals.append(self._enc_api_key(api_key))
        if enabled is not None:
            sets.append("enabled = ?"); vals.append(1 if enabled else 0)
        if note is not None:
            sets.append("note = ?"); vals.append(note)
        if not sets:
            return self.get_provider(provider_id)
        sets.append("updated_at = ?"); vals.append(_utc_now_iso())
        vals.append(provider_id)
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE llm_providers SET {', '.join(sets)} WHERE provider_id = ?", tuple(vals)
            )
        return self.get_provider(provider_id)

    def update_provider_in_group(self, provider_id: str, group_id_check: str | None = None,
                                 name: str | None = None, base_url: str | None = None,
                                 api_key: str | None = None, enabled: bool | None = None,
                                 note: str | None = None, protocol: str | None = None) -> dict[str, Any] | None:
        if group_id_check is not None:
            existing = self.get_provider_with_key(provider_id)
            if not existing or existing.get("group_id") != group_id_check:
                return None
        sets: list[str] = []
        vals: list[Any] = []
        if name is not None:
            sets.append("name = ?"); vals.append(name)
        if base_url is not None:
            sets.append("base_url = ?"); vals.append(base_url)
        if api_key is not None:
            sets.append("api_key = ?"); vals.append(self._enc_api_key(api_key))
        if enabled is not None:
            sets.append("enabled = ?"); vals.append(1 if enabled else 0)
        if note is not None:
            sets.append("note = ?"); vals.append(note)
        if protocol is not None:
            sets.append("protocol = ?"); vals.append("anthropic" if protocol == "anthropic" else "openai")
        if not sets:
            return self.get_provider(provider_id)
        sets.append("updated_at = ?"); vals.append(_utc_now_iso())
        vals.append(provider_id)
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE llm_providers SET {', '.join(sets)} WHERE provider_id = ?", tuple(vals)
            )
        return self.get_provider(provider_id)

    def delete_provider(self, provider_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM llm_providers WHERE provider_id = ?", (provider_id,))
            return cur.rowcount > 0

    def delete_provider_in_group(self, provider_id: str, group_id_check: str | None = None) -> bool:
        if group_id_check is not None:
            existing = self.get_provider_with_key(provider_id)
            if not existing or existing.get("group_id") != group_id_check:
                return False
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM llm_providers WHERE provider_id = ?", (provider_id,))
            return cur.rowcount > 0

    @staticmethod
    def _mask_provider(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        d = dict(row)
        if "api_key" in d and d["api_key"]:
            k = d["api_key"]
            d["api_key"] = (k[:4] + "..." + k[-2:]) if len(k) > 8 else "***"
            d["api_key_set"] = True
        else:
            d["api_key_set"] = False
        return d

    # ---------- model_routes (flat + grouped) ----------
    def list_routes(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT route_id, group_id, alias, provider_id, upstream_model, upstream_path, "
            "enabled, note, created_at, updated_at, mode, adapter_config, fusion_config "
            "FROM model_routes ORDER BY alias ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    def list_routes_in_group(self, group_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT route_id, group_id, alias, provider_id, upstream_model, upstream_path, "
            "enabled, note, created_at, updated_at, mode, adapter_config, fusion_config "
            "FROM model_routes WHERE group_id = ? ORDER BY alias ASC",
            (group_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_route(self, route_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM model_routes WHERE route_id = ?", (route_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_route_by_alias(self, alias: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM model_routes WHERE alias = ?", (alias,)
        ).fetchone()
        return dict(row) if row else None

    def get_route_by_alias_in_group(self, alias: str, group_id: str) -> dict[str, Any] | None:
        """Scoped to a single group."""
        row = self._conn.execute(
            "SELECT * FROM model_routes WHERE alias = ? AND group_id = ?",
            (alias, group_id),
        ).fetchone()
        return dict(row) if row else None

    def create_route(self, alias: str, provider_id: str, upstream_model: str, note: str = "") -> dict[str, Any]:
        now = _utc_now_iso()
        route_id = uuid.uuid4().hex
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO model_routes (route_id, group_id, alias, provider_id, upstream_model, enabled, note, created_at, updated_at) "
                "VALUES (?, 'default', ?, ?, ?, 1, ?, ?, ?)",
                (route_id, alias, provider_id, upstream_model, note, now, now),
            )
        return self.get_route(route_id)  # type: ignore[return-value]

    def create_route_in_group(self, group_id: str, alias: str, provider_id: str,
                               upstream_model: str, upstream_path: str = "", note: str = "",
                               mode: str = "direct", adapter_config: str = "{}",
                               fusion_config: str = "{}") -> dict[str, Any]:
        if not self.get_group(group_id):
            raise ValueError(f"group not found: {group_id}")
        prov = self.get_provider_with_key(provider_id)
        if not prov:
            raise ValueError(f"provider not found: {provider_id}")
        if prov.get("group_id") != group_id:
            raise ValueError("provider does not belong to this group")
        if mode not in VALID_MODES:
            raise ValueError(f"invalid mode: {mode} (must be one of {', '.join(VALID_MODES)})")
        now = _utc_now_iso()
        route_id = uuid.uuid4().hex
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO model_routes (route_id, group_id, alias, provider_id, upstream_model, upstream_path, "
                "enabled, note, created_at, updated_at, mode, adapter_config, fusion_config) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)",
                (route_id, group_id, alias, provider_id, upstream_model, upstream_path, note, now, now,
                 mode, adapter_config, fusion_config),
            )
        return self.get_route(route_id)  # type: ignore[return-value]

    def update_route(self, route_id: str, alias: str | None = None, provider_id: str | None = None,
                    upstream_model: str | None = None, enabled: bool | None = None, note: str | None = None) -> dict[str, Any] | None:
        sets: list[str] = []
        vals: list[Any] = []
        if alias is not None:
            sets.append("alias = ?"); vals.append(alias)
        if provider_id is not None:
            sets.append("provider_id = ?"); vals.append(provider_id)
        if upstream_model is not None:
            sets.append("upstream_model = ?"); vals.append(upstream_model)
        if enabled is not None:
            sets.append("enabled = ?"); vals.append(1 if enabled else 0)
        if note is not None:
            sets.append("note = ?"); vals.append(note)
        if not sets:
            return self.get_route(route_id)
        sets.append("updated_at = ?"); vals.append(_utc_now_iso())
        vals.append(route_id)
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE model_routes SET {', '.join(sets)} WHERE route_id = ?", tuple(vals)
            )
        return self.get_route(route_id)

    def update_route_in_group(self, route_id: str, group_id_check: str | None = None,
                              alias: str | None = None, provider_id: str | None = None,
                              upstream_model: str | None = None,
                              upstream_path: str | None = None,
                              enabled: bool | None = None, note: str | None = None,
                              mode: str | None = None,
                              adapter_config: str | None = None,
                              fusion_config: str | None = None) -> dict[str, Any] | None:
        if group_id_check is not None:
            existing = self.get_route(route_id)
            if not existing or existing.get("group_id") != group_id_check:
                return None
        if mode is not None and mode not in VALID_MODES:
            raise ValueError(f"invalid mode: {mode} (must be one of {', '.join(VALID_MODES)})")
        sets: list[str] = []
        vals: list[Any] = []
        if alias is not None:
            sets.append("alias = ?"); vals.append(alias)
        if provider_id is not None:
            sets.append("provider_id = ?"); vals.append(provider_id)
        if upstream_model is not None:
            sets.append("upstream_model = ?"); vals.append(upstream_model)
        if upstream_path is not None:
            sets.append("upstream_path = ?"); vals.append(upstream_path)
        if enabled is not None:
            sets.append("enabled = ?"); vals.append(1 if enabled else 0)
        if note is not None:
            sets.append("note = ?"); vals.append(note)
        if mode is not None:
            sets.append("mode = ?"); vals.append(mode)
        if adapter_config is not None:
            sets.append("adapter_config = ?"); vals.append(adapter_config)
        if fusion_config is not None:
            sets.append("fusion_config = ?"); vals.append(fusion_config)
        if not sets:
            return self.get_route(route_id)
        sets.append("updated_at = ?"); vals.append(_utc_now_iso())
        vals.append(route_id)
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE model_routes SET {', '.join(sets)} WHERE route_id = ?", tuple(vals)
            )
        return self.get_route(route_id)

    def delete_route(self, route_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM model_routes WHERE route_id = ?", (route_id,))
            return cur.rowcount > 0

    def delete_route_in_group(self, route_id: str, group_id_check: str | None = None) -> bool:
        if group_id_check is not None:
            existing = self.get_route(route_id)
            if not existing or existing.get("group_id") != group_id_check:
                return False
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM model_routes WHERE route_id = ?", (route_id,))
            return cur.rowcount > 0

    # ---------- api_keys (flat + grouped) ----------
    def list_keys(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT key_id, group_id, key_prefix, name, owner_user_id, enabled, expires_at, last_used_at, created_at "
            "FROM llm_api_keys ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def list_keys_in_group(self, group_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT key_id, group_id, key_prefix, name, owner_user_id, enabled, expires_at, last_used_at, created_at "
            "FROM llm_api_keys WHERE group_id = ? ORDER BY created_at DESC",
            (group_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_key_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM llm_api_keys WHERE key_hash = ?", (key_hash,)
        ).fetchone()
        return dict(row) if row else None

    def get_key(self, key_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT key_id, group_id, key_prefix, name, owner_user_id, enabled, expires_at, last_used_at, created_at "
            "FROM llm_api_keys WHERE key_id = ?", (key_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_key_full(self, key_id: str) -> dict[str, Any] | None:
        """Return the full key row INCLUDING ``key_encrypted``. Owner-only use."""
        row = self._conn.execute(
            "SELECT * FROM llm_api_keys WHERE key_id = ?", (key_id,),
        ).fetchone()
        return dict(row) if row else None

    def create_key(self, key_hash: str, key_prefix: str, name: str, owner_user_id: str | None = None,
                   expires_at: str | None = None) -> dict[str, Any]:
        now = _utc_now_iso()
        key_id = uuid.uuid4().hex
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO llm_api_keys (key_id, group_id, key_hash, key_prefix, name, owner_user_id, enabled, expires_at, last_used_at, created_at) "
                "VALUES (?, 'default', ?, ?, ?, ?, 1, ?, NULL, ?)",
                (key_id, key_hash, key_prefix, name, owner_user_id, expires_at, now),
            )
        return self.get_key(key_id)  # type: ignore[return-value]

    def create_key_in_group(self, group_id: str, key_hash: str, key_prefix: str, name: str,
                             owner_user_id: str | None = None, expires_at: str | None = None,
                             key_encrypted: str | None = None) -> dict[str, Any]:
        if not self.get_group(group_id):
            raise ValueError(f"group not found: {group_id}")
        now = _utc_now_iso()
        key_id = uuid.uuid4().hex
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO llm_api_keys (key_id, group_id, key_hash, key_prefix, name, owner_user_id, enabled, expires_at, last_used_at, created_at, key_encrypted) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, ?, NULL, ?, ?)",
                (key_id, group_id, key_hash, key_prefix, name, owner_user_id, expires_at, now, key_encrypted),
            )
        return self.get_key(key_id)  # type: ignore[return-value]

    def update_key(self, key_id: str, name: str | None = None, enabled: bool | None = None,
                   expires_at: str | None = "__UNSET__") -> dict[str, Any] | None:
        sets: list[str] = []
        vals: list[Any] = []
        if name is not None:
            sets.append("name = ?"); vals.append(name)
        if enabled is not None:
            sets.append("enabled = ?"); vals.append(1 if enabled else 0)
        if expires_at != "__UNSET__":
            sets.append("expires_at = ?"); vals.append(expires_at)
        if not sets:
            return self.get_key(key_id)
        vals.append(key_id)
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE llm_api_keys SET {', '.join(sets)} WHERE key_id = ?", tuple(vals)
            )
        return self.get_key(key_id)

    def update_key_in_group(self, key_id: str, group_id_check: str | None = None,
                             name: str | None = None, enabled: bool | None = None,
                             expires_at: str | None = "__UNSET__") -> dict[str, Any] | None:
        if group_id_check is not None:
            existing = self.get_key(key_id)
            if not existing or existing.get("group_id") != group_id_check:
                return None
        return self.update_key(key_id, name=name, enabled=enabled, expires_at=expires_at)

    def delete_key(self, key_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM llm_api_keys WHERE key_id = ?", (key_id,))
            return cur.rowcount > 0

    def delete_key_in_group(self, key_id: str, group_id_check: str | None = None) -> bool:
        if group_id_check is not None:
            existing = self.get_key(key_id)
            if not existing or existing.get("group_id") != group_id_check:
                return False
        return self.delete_key(key_id)

    def touch_key_used(self, key_id: str) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE llm_api_keys SET last_used_at = ? WHERE key_id = ?",
                (_utc_now_iso(), key_id),
            )

    # ---------- tool_providers (flat + grouped) ----------
    def list_tool_providers(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT tool_id, group_id, name, config, enabled, created_at, updated_at "
            "FROM llm_tool_providers ORDER BY created_at ASC"
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["api_key_set"] = bool(self._conn.execute(
                "SELECT 1 FROM llm_tool_providers WHERE tool_id = ? AND api_key != ''", (d["tool_id"],)
            ).fetchone())
            result.append(d)
        return result

    def list_tool_providers_in_group(self, group_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT tool_id, group_id, name, config, enabled, created_at, updated_at "
            "FROM llm_tool_providers WHERE group_id = ? ORDER BY created_at ASC",
            (group_id,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["api_key_set"] = bool(self._conn.execute(
                "SELECT 1 FROM llm_tool_providers WHERE tool_id = ? AND api_key != ''", (d["tool_id"],)
            ).fetchone())
            result.append(d)
        return result

    def get_tool_provider_with_key(self, tool_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM llm_tool_providers WHERE tool_id = ?", (tool_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["api_key"] = self._dec_api_key(d.get("api_key", ""))
        return d

    def get_tool_provider(self, tool_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT tool_id, group_id, name, config, enabled, created_at, updated_at "
            "FROM llm_tool_providers WHERE tool_id = ?", (tool_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["api_key_set"] = bool(self._conn.execute(
            "SELECT 1 FROM llm_tool_providers WHERE tool_id = ? AND api_key != ''", (tool_id,)
        ).fetchone())
        return d

    def create_tool_provider(self, tool_id: str, name: str, api_key: str, config: str = "{}") -> dict[str, Any]:
        now = _utc_now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO llm_tool_providers (tool_id, group_id, name, api_key, config, enabled, created_at, updated_at) "
                "VALUES (?, 'default', ?, ?, ?, 1, ?, ?)",
                (tool_id, name, self._enc_api_key(api_key), config, now, now),
            )
        return self.get_tool_provider(tool_id)  # type: ignore[return-value]

    def create_tool_provider_in_group(self, group_id: str, tool_id: str, name: str, api_key: str,
                                       config: str = "{}") -> dict[str, Any]:
        if not self.get_group(group_id):
            raise ValueError(f"group not found: {group_id}")
        now = _utc_now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO llm_tool_providers (tool_id, group_id, name, api_key, config, enabled, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                (tool_id, group_id, name, self._enc_api_key(api_key), config, now, now),
            )
        return self.get_tool_provider(tool_id)  # type: ignore[return-value]

    def update_tool_provider(self, tool_id: str, name: str | None = None, api_key: str | None = None,
                             config: str | None = None, enabled: bool | None = None) -> dict[str, Any] | None:
        sets: list[str] = []
        vals: list[Any] = []
        if name is not None:
            sets.append("name = ?"); vals.append(name)
        if api_key is not None:
            sets.append("api_key = ?"); vals.append(self._enc_api_key(api_key))
        if config is not None:
            sets.append("config = ?"); vals.append(config)
        if enabled is not None:
            sets.append("enabled = ?"); vals.append(1 if enabled else 0)
        if not sets:
            return self.get_tool_provider(tool_id)
        sets.append("updated_at = ?"); vals.append(_utc_now_iso())
        vals.append(tool_id)
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE llm_tool_providers SET {', '.join(sets)} WHERE tool_id = ?", tuple(vals)
            )
        return self.get_tool_provider(tool_id)

    def update_tool_provider_in_group(self, tool_id: str, group_id_check: str | None = None,
                                       name: str | None = None, api_key: str | None = None,
                                       config: str | None = None,
                                       enabled: bool | None = None) -> dict[str, Any] | None:
        if group_id_check is not None:
            existing = self.get_tool_provider(tool_id)
            if not existing or existing.get("group_id") != group_id_check:
                return None
        return self.update_tool_provider(tool_id, name=name, api_key=api_key, config=config, enabled=enabled)

    def delete_tool_provider(self, tool_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM llm_tool_providers WHERE tool_id = ?", (tool_id,))
            return cur.rowcount > 0

    def delete_tool_provider_in_group(self, tool_id: str, group_id_check: str | None = None) -> bool:
        if group_id_check is not None:
            existing = self.get_tool_provider(tool_id)
            if not existing or existing.get("group_id") != group_id_check:
                return False
        return self.delete_tool_provider(tool_id)

    # ---------- request_logs (flat + grouped) ----------
    def log_request(self, *, api_key_id: str | None, route_alias: str, provider_id: str,
                    upstream_model: str, status_code: int | None, request_tokens: int | None,
                    response_tokens: int | None, latency_ms: int, error: str = "",
                    group_id: str = "", fusion_id: str | None = None) -> None:
        log_id = uuid.uuid4().hex
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO llm_request_logs (log_id, group_id, api_key_id, route_alias, provider_id, upstream_model, "
                "status_code, request_tokens, response_tokens, latency_ms, error, created_at, fusion_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (log_id, group_id or "default", api_key_id, route_alias, provider_id, upstream_model,
                 status_code, request_tokens, response_tokens, latency_ms, error, _utc_now_iso(), fusion_id),
            )

    def list_logs(self, api_key_id: str | None = None, group_id: str | None = None,
                  limit: int = 100) -> list[dict[str, Any]]:
        clauses: list[str] = []
        vals: list[Any] = []
        if api_key_id:
            clauses.append("api_key_id = ?"); vals.append(api_key_id)
        if group_id:
            clauses.append("group_id = ?"); vals.append(group_id)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._conn.execute(
            "SELECT log_id, group_id, api_key_id, route_alias, provider_id, upstream_model, status_code, "
            "request_tokens, response_tokens, latency_ms, error, created_at, fusion_id "
            f"FROM llm_request_logs {where} ORDER BY created_at DESC LIMIT ?",
            (*vals, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def log_stats_for_key(self, api_key_id: str) -> dict[str, Any]:
        row = self._conn.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN status_code = 200 THEN 1 ELSE 0 END) AS ok, "
            "COALESCE(SUM(request_tokens), 0) AS req_t, "
            "COALESCE(SUM(response_tokens), 0) AS resp_t, "
            "COALESCE(AVG(latency_ms), 0) AS avg_latency "
            "FROM llm_request_logs WHERE api_key_id = ?",
            (api_key_id,),
        ).fetchone()
        return dict(row) if row else {"total": 0, "ok": 0, "req_t": 0, "resp_t": 0, "avg_latency": 0}

    # ---------- route_providers (multi-provider associations) ----------
    def list_route_providers(self, route_id: str) -> list[dict[str, Any]]:
        """List all provider associations for a route, sorted by priority."""
        rows = self._conn.execute(
            "SELECT rp_id, route_id, provider_id, upstream_model, priority, enabled, created_at "
            "FROM route_providers WHERE route_id = ? ORDER BY priority ASC, created_at ASC",
            (route_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def add_route_provider(self, route_id: str, provider_id: str,
                           upstream_model: str, priority: int = 0,
                           enabled: bool = True) -> dict[str, Any]:
        route = self.get_route(route_id)
        if not route:
            raise ValueError(f"route not found: {route_id}")
        prov = self.get_provider_with_key(provider_id)
        if not prov:
            raise ValueError(f"provider not found: {provider_id}")
        if prov.get("group_id") != route.get("group_id"):
            raise ValueError("provider does not belong to this route's group")
        now = _utc_now_iso()
        rp_id = uuid.uuid4().hex
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO route_providers (rp_id, route_id, provider_id, upstream_model, priority, enabled, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rp_id, route_id, provider_id, upstream_model, priority, 1 if enabled else 0, now),
            )
        return self.get_route_provider(rp_id)  # type: ignore[return-value]

    def get_route_provider(self, rp_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT rp_id, route_id, provider_id, upstream_model, priority, enabled, created_at "
            "FROM route_providers WHERE rp_id = ?",
            (rp_id,),
        ).fetchone()
        return dict(row) if row else None

    def update_route_provider(self, rp_id: str, *,
                              priority: int | None = None,
                              enabled: bool | None = None,
                              upstream_model: str | None = None) -> dict[str, Any] | None:
        existing = self.get_route_provider(rp_id)
        if not existing:
            return None
        sets: list[str] = []
        vals: list[Any] = []
        if priority is not None:
            sets.append("priority = ?"); vals.append(int(priority))
        if enabled is not None:
            sets.append("enabled = ?"); vals.append(1 if enabled else 0)
        if upstream_model is not None:
            sets.append("upstream_model = ?"); vals.append(upstream_model)
        if not sets:
            return self.get_route_provider(rp_id)
        vals.append(rp_id)
        with self._lock, self._conn:
            self._conn.execute(
                f"UPDATE route_providers SET {', '.join(sets)} WHERE rp_id = ?", tuple(vals)
            )
        return self.get_route_provider(rp_id)

    def delete_route_provider(self, rp_id: str) -> bool:
        with self._lock, self._conn:
            cur = self._conn.execute("DELETE FROM route_providers WHERE rp_id = ?", (rp_id,))
            return cur.rowcount > 0

    # ---------- provider_health (circuit breaker) ----------
    def _get_provider_health(self, provider_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM provider_health WHERE provider_id = ?",
            (provider_id,),
        ).fetchone()
        return dict(row) if row else None

    def record_provider_success(self, provider_id: str, group_id: str = "") -> None:
        now = _utc_now_iso()
        with self._lock, self._conn:
            existing = self._get_provider_health(provider_id)
            if existing:
                self._conn.execute(
                    "UPDATE provider_health SET consecutive_fails = 0, last_success_at = ?, "
                    "circuit_open = 0, circuit_open_until = NULL WHERE provider_id = ?",
                    (now, provider_id),
                )
            else:
                self._conn.execute(
                    "INSERT INTO provider_health (provider_id, group_id, consecutive_fails, "
                    "last_success_at, circuit_open, circuit_open_until) VALUES (?, ?, 0, ?, 0, NULL)",
                    (provider_id, group_id or "default", now),
                )

    def record_provider_failure(self, provider_id: str, group_id: str = "") -> None:
        now_iso = _utc_now_iso()
        now_dt = datetime.now(timezone.utc)
        with self._lock, self._conn:
            existing = self._get_provider_health(provider_id)
            if existing:
                fails = int(existing.get("consecutive_fails", 0)) + 1
                if fails >= CIRCUIT_FAIL_THRESHOLD:
                    open_until = (now_dt + timedelta(seconds=CIRCUIT_OPEN_SECONDS)).isoformat()
                    self._conn.execute(
                        "UPDATE provider_health SET consecutive_fails = ?, last_fail_at = ?, "
                        "circuit_open = 1, circuit_open_until = ? WHERE provider_id = ?",
                        (fails, now_iso, open_until, provider_id),
                    )
                else:
                    self._conn.execute(
                        "UPDATE provider_health SET consecutive_fails = ?, last_fail_at = ? "
                        "WHERE provider_id = ?",
                        (fails, now_iso, provider_id),
                    )
            else:
                opens = 1 if 1 >= CIRCUIT_FAIL_THRESHOLD else 0
                open_until = (now_dt + timedelta(seconds=CIRCUIT_OPEN_SECONDS)).isoformat() if opens else None
                self._conn.execute(
                    "INSERT INTO provider_health (provider_id, group_id, consecutive_fails, "
                    "last_fail_at, circuit_open, circuit_open_until) VALUES (?, ?, ?, ?, ?, ?)",
                    (provider_id, group_id or "default", 1, now_iso, opens, open_until),
                )

    def is_circuit_open(self, provider_id: str) -> bool:
        row = self._get_provider_health(provider_id)
        if not row:
            return False
        if not int(row.get("circuit_open", 0)):
            return False
        until = row.get("circuit_open_until")
        if not until:
            return True
        try:
            return datetime.now(timezone.utc) < datetime.fromisoformat(until)
        except Exception:
            return True

    def reset_provider_health(self, provider_id: str) -> dict[str, Any] | None:
        with self._lock, self._conn:
            existing = self._get_provider_health(provider_id)
            if not existing:
                return None
            self._conn.execute(
                "UPDATE provider_health SET consecutive_fails = 0, circuit_open = 0, "
                "circuit_open_until = NULL WHERE provider_id = ?",
                (provider_id,),
            )
        return self._get_provider_health(provider_id)

    def list_provider_health(self, group_id: str | None = None) -> list[dict[str, Any]]:
        if group_id:
            rows = self._conn.execute(
                "SELECT ph.* FROM provider_health ph "
                "JOIN llm_providers p ON ph.provider_id = p.provider_id "
                "WHERE ph.group_id = ? ORDER BY ph.last_fail_at DESC NULLS LAST",
                (group_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM provider_health ORDER BY last_fail_at DESC NULLS LAST"
            ).fetchall()
        return [dict(r) for r in rows]

    # ---------- e2e helper ----------
    def list_enabled_routes_with_provider(self, group_id: str | None = None) -> list[dict[str, Any]]:
        if group_id is None:
            rows = self._conn.execute(
                "SELECT r.route_id, r.group_id, r.alias, r.upstream_model, "
                "       p.provider_id, p.protocol, p.base_url, p.api_key, p.enabled AS provider_enabled "
                "FROM model_routes r JOIN llm_providers p ON r.provider_id = p.provider_id "
                "WHERE r.enabled = 1 ORDER BY r.alias ASC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT r.route_id, r.group_id, r.alias, r.upstream_model, "
                "       p.provider_id, p.protocol, p.base_url, p.api_key, p.enabled AS provider_enabled "
                "FROM model_routes r JOIN llm_providers p ON r.provider_id = p.provider_id "
                "WHERE r.enabled = 1 AND r.group_id = ? ORDER BY r.alias ASC",
                (group_id,),
            ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["api_key"] = self._dec_api_key(d.get("api_key", ""))
            out.append(d)
        return out
