"""Keyway FastAPI application — LLM routing gateway.

Endpoints:
  Proxy (db_sk_ Bearer auth):
    POST /v1/chat/completions   — OpenAI-compatible
    GET  /v1/models             — OpenAI-compatible model list
    POST /v1/messages           — Anthropic Messages-compatible
    POST /v1/messages/count_tokens — Anthropic token count
    POST /v1/generations        — Generic generation forwarding (image/video/3D)

  Admin (X-Admin-Token header or session cookie):
    /admin/llm/groups           — CRUD for routing groups
    /admin/llm/groups/{id}/providers, routes, keys, tool-providers
    /admin/llm/{providers,routes,keys,tool-providers}/{id}
    /admin/llm/logs, /admin/llm/stats, /admin/llm/test, /admin/llm/e2e
    /admin/login, /admin/session, /admin/logout
    /admin/config               — runtime config for the web UI

  Web UI:
    GET /                       — admin UI (index.html)
    GET /docs                   — integration docs (docs.html)
    GET /health                 — health check
"""

from __future__ import annotations

import json
import logging
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import crypto
from .config import Settings, load_settings
from .llm_keys import generate_key as _llm_generate_key, hash_key as _llm_hash_key, key_prefix as _llm_key_prefix
from .llm_router import LLMRouter
from .llm_store import LLMStore
from .models import (
    AdminLoginRequest,
    LLMGroupCopyRequest,
    LLMGroupCreateRequest,
    LLMGroupUpdateRequest,
    LLMKeyCreateRequest,
    LLMKeyUpdateRequest,
    LLMProviderCreateRequest,
    LLMProviderUpdateRequest,
    LLMRouteCreateRequest,
    LLMRouteUpdateRequest,
    LLMTestRequest,
    LLMToolProviderCreateRequest,
    LLMToolProviderUpdateRequest,
)

WEB_DIR = Path(__file__).resolve().parent / "web"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---- session store (in-memory, single-admin) ----
class _SessionStore:
    def __init__(self) -> None:
        self._token: str = ""

    def create(self) -> str:
        self._token = secrets.token_urlsafe(32)
        return self._token

    def valid(self, token: str) -> bool:
        return bool(self._token and token == self._token)

    def destroy(self) -> None:
        self._token = ""


def create_app() -> FastAPI:
    settings = load_settings()

    # ---- logging ----
    logger = logging.getLogger("keyway")
    if not logger.handlers:
        logger.setLevel(settings.log_level.upper())
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.propagate = False

    # ---- secret enforcement ----
    if crypto.is_dev_fallback(settings.secret):
        raise RuntimeError(
            "KEYWAY_SECRET is unset or empty. Refusing to start — at-rest key "
            "encryption requires a strong KEYWAY_SECRET. Set it in .env "
            "(see .env.example) or generate with: "
            'python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )

    # ---- admin token auto-generation ----
    admin_token = settings.admin_token
    if not admin_token:
        admin_token = secrets.token_urlsafe(24)
        logger.warning(
            "KEYWAY_ADMIN_TOKEN not set — generated a random admin token for this session:\n"
            "  %s\n"
            "Set KEYWAY_ADMIN_TOKEN in .env for a persistent token.",
            admin_token,
        )

    # ---- stores ----
    llm_store = LLMStore(settings.data_dir / "keyway.db", secret=settings.secret)
    llm_router = LLMRouter(llm_store)
    sessions = _SessionStore()

    app = FastAPI(title="Keyway", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.settings = settings
    app.state.llm_store = llm_store
    app.state.llm_router = llm_router
    app.state.admin_token = admin_token
    app.state.sessions = sessions
    app.state.logger = logger

    # ==================== Auth helpers ====================

    def _require_admin(
        request: Request,
        x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    ) -> dict[str, Any]:
        token = x_admin_token or request.cookies.get("keyway_admin_session", "")
        if token and token == request.app.state.admin_token:
            return {"ok": True}
        if token and request.app.state.sessions.valid(token):
            return {"ok": True}
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin authentication required. Use X-Admin-Token header or login via /admin/login.",
        )

    def _llm_encrypt(plaintext: str) -> str:
        return crypto.encrypt_value(plaintext, settings.secret) if plaintext else ""

    def _llm_decrypt(token: str) -> str:
        try:
            return crypto.decrypt_value(token, settings.secret)
        except Exception:
            return ""

    def _llm_bearer_auth(authorization: str | None = Header(default=None)) -> str:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid Authorization header. Use 'Bearer db_sk_...'.",
            )
        return authorization[7:].strip()

    def _resolve_llm_api_key(
        request: Request,
        token: str = Depends(_llm_bearer_auth),
    ) -> dict[str, Any]:
        key_row = request.app.state.llm_store.get_key_by_hash(_llm_hash_key(token))
        if not key_row or not key_row.get("enabled"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or disabled API key.")
        if key_row.get("expires_at") and key_row["expires_at"] < _utc_now_iso():
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key expired.")
        request.app.state.llm_store.touch_key_used(key_row["key_id"])
        return key_row

    def _estimate_tokens(req: dict) -> int:
        """Rough char/4 heuristic."""
        chars = 0
        for m in req.get("messages") or []:
            content = m.get("content")
            if isinstance(content, str):
                chars += len(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        chars += len(str(block.get("text", "")))
        chars += len(req.get("system", "") if isinstance(req.get("system"), str) else "")
        return max(1, chars // 4 + 4)

    # ==================== Admin: login / session ====================

    @app.post("/admin/login")
    def admin_login(payload: AdminLoginRequest, request: Request, response: Response) -> dict:
        if payload.token != request.app.state.admin_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token.")
        session_token = request.app.state.sessions.create()
        response.set_cookie(
            key="keyway_admin_session",
            value=session_token,
            max_age=SESSION_TTL_SECONDS,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
        )
        return {"ok": True}

    @app.get("/admin/session")
    def admin_session(_admin: dict = Depends(_require_admin)) -> dict:
        return {"ok": True}

    @app.post("/admin/logout")
    def admin_logout(request: Request) -> dict:
        request.app.state.sessions.destroy()
        return {"ok": True}

    @app.get("/admin/config")
    def admin_config(request: Request, _admin: dict = Depends(_require_admin)) -> dict:
        base_url = request.app.state.settings.public_base_url
        if not base_url:
            base_url = str(request.base_url).rstrip("/")
        return {"ok": True, "config": {"app_base_url": base_url}}

    # ==================== Admin: groups ====================

    @app.get("/admin/llm/groups")
    def admin_list_llm_groups(_admin: dict = Depends(_require_admin)) -> dict:
        return {"ok": True, "groups": llm_store.list_groups()}

    @app.post("/admin/llm/groups")
    def admin_create_llm_group(
        payload: LLMGroupCreateRequest,
        _admin: dict = Depends(_require_admin),
    ) -> dict:
        try:
            g = llm_store.create_group(group_id=payload.group_id, name=payload.name, note=payload.note)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"group_id '{payload.group_id}' already exists",
            )
        return {"ok": True, "group": g}

    @app.get("/admin/llm/groups/{group_id}")
    def admin_get_llm_group(group_id: str, _admin: dict = Depends(_require_admin)) -> dict:
        g = llm_store.get_group(group_id)
        if not g:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"group not found: {group_id}")
        return {"ok": True, "group": g}

    @app.patch("/admin/llm/groups/{group_id}")
    def admin_update_llm_group(
        group_id: str,
        payload: LLMGroupUpdateRequest,
        _admin: dict = Depends(_require_admin),
    ) -> dict:
        g = llm_store.update_group(group_id=group_id, name=payload.name, enabled=payload.enabled, note=payload.note)
        if not g:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"group not found: {group_id}")
        return {"ok": True, "group": g}

    @app.delete("/admin/llm/groups/{group_id}")
    def admin_delete_llm_group(group_id: str, _admin: dict = Depends(_require_admin)) -> dict:
        try:
            if not llm_store.delete_group(group_id):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"group not found: {group_id}")
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        return {"ok": True, "message": f"group deleted: {group_id}"}

    @app.post("/admin/llm/groups/{group_id}/copy")
    def admin_copy_llm_group(
        group_id: str,
        payload: LLMGroupCopyRequest,
        _admin: dict = Depends(_require_admin),
    ) -> dict:
        resolved_new_gid = payload.new_group_id or (group_id + "-copy-" + uuid.uuid4().hex[:6])
        try:
            g = llm_store.copy_group(
                src_group_id=group_id,
                new_group_id=resolved_new_gid,
                new_name=payload.new_name,
                plaintext_for_key=_llm_generate_key,
                hash_for_key=_llm_hash_key,
                encrypt_for_key=_llm_encrypt,
                key_prefix_for_key=_llm_key_prefix,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"group_id '{resolved_new_gid}' already exists",
            )
        return {"ok": True, "group": g}

    # ==================== Admin: group providers ====================

    @app.get("/admin/llm/groups/{group_id}/providers")
    def admin_list_group_providers(group_id: str, _admin: dict = Depends(_require_admin)) -> dict:
        if not llm_store.get_group(group_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"group not found: {group_id}")
        return {"ok": True, "providers": llm_store.list_providers_in_group(group_id)}

    @app.post("/admin/llm/groups/{group_id}/providers")
    def admin_create_group_provider(
        group_id: str,
        payload: LLMProviderCreateRequest,
        _admin: dict = Depends(_require_admin),
    ) -> dict:
        if not llm_store.get_group(group_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"group not found: {group_id}")
        try:
            p = llm_store.create_provider_in_group(
                group_id=group_id, provider_id=payload.provider_id, name=payload.name,
                base_url=payload.base_url, api_key=payload.api_key,
                protocol=payload.protocol, note=payload.note,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        return {"ok": True, "provider": p}

    @app.get("/admin/llm/providers/{provider_id}")
    def admin_get_llm_provider(provider_id: str, _admin: dict = Depends(_require_admin)) -> dict:
        p = llm_store.get_provider(provider_id)
        if not p:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"provider not found: {provider_id}")
        provider_with_key = llm_store.get_provider_with_key(provider_id)
        if provider_with_key:
            p["api_key"] = provider_with_key["api_key"]
        return {"ok": True, "provider": p}

    @app.patch("/admin/llm/providers/{provider_id}")
    def admin_update_llm_provider(
        provider_id: str,
        payload: LLMProviderUpdateRequest,
        _admin: dict = Depends(_require_admin),
    ) -> dict:
        p = llm_store.update_provider_in_group(
            provider_id=provider_id, name=payload.name, base_url=payload.base_url,
            api_key=payload.api_key, protocol=payload.protocol, enabled=payload.enabled, note=payload.note,
        )
        if not p:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"provider not found: {provider_id}")
        return {"ok": True, "provider": p}

    @app.delete("/admin/llm/providers/{provider_id}")
    def admin_delete_llm_provider(provider_id: str, _admin: dict = Depends(_require_admin)) -> dict:
        if not llm_store.delete_provider_in_group(provider_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"provider not found: {provider_id}")
        return {"ok": True, "message": f"provider deleted: {provider_id}"}

    # ==================== Admin: group routes ====================

    @app.get("/admin/llm/groups/{group_id}/routes")
    def admin_list_group_routes(group_id: str, _admin: dict = Depends(_require_admin)) -> dict:
        if not llm_store.get_group(group_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"group not found: {group_id}")
        return {"ok": True, "routes": llm_store.list_routes_in_group(group_id)}

    @app.post("/admin/llm/groups/{group_id}/routes")
    def admin_create_group_route(
        group_id: str,
        payload: LLMRouteCreateRequest,
        _admin: dict = Depends(_require_admin),
    ) -> dict:
        if not llm_store.get_group(group_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"group not found: {group_id}")
        try:
            r = llm_store.create_route_in_group(
                group_id=group_id, alias=payload.alias, provider_id=payload.provider_id,
                upstream_model=payload.upstream_model, upstream_path=payload.upstream_path, note=payload.note,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        return {"ok": True, "route": r}

    @app.get("/admin/llm/routes/{route_id}")
    def admin_get_llm_route(route_id: str, _admin: dict = Depends(_require_admin)) -> dict:
        r = llm_store.get_route(route_id)
        if not r:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"route not found: {route_id}")
        return {"ok": True, "route": r}

    @app.patch("/admin/llm/routes/{route_id}")
    def admin_update_llm_route(
        route_id: str,
        payload: LLMRouteUpdateRequest,
        _admin: dict = Depends(_require_admin),
    ) -> dict:
        r = llm_store.update_route_in_group(
            route_id=route_id, alias=payload.alias, provider_id=payload.provider_id,
            upstream_model=payload.upstream_model, upstream_path=payload.upstream_path,
            enabled=payload.enabled, note=payload.note,
        )
        if not r:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"route not found: {route_id}")
        return {"ok": True, "route": r}

    @app.delete("/admin/llm/routes/{route_id}")
    def admin_delete_llm_route(route_id: str, _admin: dict = Depends(_require_admin)) -> dict:
        if not llm_store.delete_route_in_group(route_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"route not found: {route_id}")
        return {"ok": True, "message": f"route deleted: {route_id}"}

    # ==================== Admin: group api keys ====================

    @app.get("/admin/llm/groups/{group_id}/keys")
    def admin_list_group_keys(group_id: str, _admin: dict = Depends(_require_admin)) -> dict:
        if not llm_store.get_group(group_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"group not found: {group_id}")
        return {"ok": True, "keys": llm_store.list_keys_in_group(group_id)}

    @app.post("/admin/llm/groups/{group_id}/keys")
    def admin_create_group_key(
        group_id: str,
        payload: LLMKeyCreateRequest,
        _admin: dict = Depends(_require_admin),
    ) -> dict:
        if not llm_store.get_group(group_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"group not found: {group_id}")
        plaintext = _llm_generate_key()
        try:
            key_row = llm_store.create_key_in_group(
                group_id=group_id, key_hash=_llm_hash_key(plaintext),
                key_prefix=_llm_key_prefix(plaintext), name=payload.name,
                owner_user_id=payload.owner_user_id, expires_at=payload.expires_at,
                key_encrypted=_llm_encrypt(plaintext),
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        return {
            "ok": True,
            "key": key_row,
            "plaintext": plaintext,
            "plaintext_note": "Store securely. As admin you can re-retrieve the plaintext later from the key list.",
        }

    @app.get("/admin/llm/keys/{key_id}/plaintext")
    def admin_get_key_plaintext(key_id: str, _admin: dict = Depends(_require_admin)) -> dict:
        full = llm_store.get_key_full(key_id)
        if not full:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"key not found: {key_id}")
        enc = full.get("key_encrypted")
        if not enc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This key was created before encrypted storage was enabled and cannot be retrieved.",
            )
        try:
            plaintext = _llm_decrypt(enc)
        except Exception:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to decrypt key")
        return {"ok": True, "plaintext": plaintext, "key_id": key_id}

    @app.patch("/admin/llm/keys/{key_id}")
    def admin_update_llm_key(
        key_id: str,
        payload: LLMKeyUpdateRequest,
        _admin: dict = Depends(_require_admin),
    ) -> dict:
        k = llm_store.update_key_in_group(
            key_id=key_id, name=payload.name, enabled=payload.enabled, expires_at=payload.expires_at,
        )
        if not k:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"key not found: {key_id}")
        return {"ok": True, "key": k}

    @app.delete("/admin/llm/keys/{key_id}")
    def admin_delete_llm_key(key_id: str, _admin: dict = Depends(_require_admin)) -> dict:
        if not llm_store.delete_key_in_group(key_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"key not found: {key_id}")
        return {"ok": True, "message": f"key deleted: {key_id}"}

    # ==================== Admin: group tool providers ====================

    @app.get("/admin/llm/groups/{group_id}/tool-providers")
    def admin_list_group_tool_providers(group_id: str, _admin: dict = Depends(_require_admin)) -> dict:
        if not llm_store.get_group(group_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"group not found: {group_id}")
        return {"ok": True, "tool_providers": llm_store.list_tool_providers_in_group(group_id)}

    @app.post("/admin/llm/groups/{group_id}/tool-providers")
    def admin_create_group_tool_provider(
        group_id: str,
        payload: LLMToolProviderCreateRequest,
        _admin: dict = Depends(_require_admin),
    ) -> dict:
        if not llm_store.get_group(group_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"group not found: {group_id}")
        try:
            t = llm_store.create_tool_provider_in_group(
                group_id=group_id, tool_id=payload.tool_id, name=payload.name,
                api_key=payload.api_key, config=payload.config,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        return {"ok": True, "tool_provider": t}

    @app.patch("/admin/llm/tool-providers/{tool_id}")
    def admin_update_llm_tool_provider(
        tool_id: str,
        payload: LLMToolProviderUpdateRequest,
        _admin: dict = Depends(_require_admin),
    ) -> dict:
        t = llm_store.update_tool_provider_in_group(
            tool_id=tool_id, name=payload.name, api_key=payload.api_key,
            config=payload.config, enabled=payload.enabled,
        )
        if not t:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"tool provider not found: {tool_id}")
        return {"ok": True, "tool_provider": t}

    @app.delete("/admin/llm/tool-providers/{tool_id}")
    def admin_delete_llm_tool_provider(tool_id: str, _admin: dict = Depends(_require_admin)) -> dict:
        if not llm_store.delete_tool_provider_in_group(tool_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"tool provider not found: {tool_id}")
        return {"ok": True, "message": f"tool provider deleted: {tool_id}"}

    # ==================== Admin: logs & diagnostics ====================

    @app.get("/admin/llm/logs")
    def admin_list_llm_logs(
        api_key_id: str | None = Query(default=None),
        group_id: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=1000),
        _admin: dict = Depends(_require_admin),
    ) -> dict:
        return {"ok": True, "logs": llm_store.list_logs(api_key_id=api_key_id, group_id=group_id, limit=limit)}

    @app.get("/admin/llm/stats")
    def admin_llm_stats(api_key_id: str = Query(...), _admin: dict = Depends(_require_admin)) -> dict:
        return {"ok": True, "stats": llm_store.log_stats_for_key(api_key_id)}

    @app.post("/admin/llm/test")
    async def admin_llm_test(payload: LLMTestRequest, request: Request, _admin: dict = Depends(_require_admin)) -> dict:
        router = request.app.state.llm_router
        if payload.provider_id:
            prov = llm_store.get_provider_with_key(payload.provider_id)
            if not prov:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"provider not found: {payload.provider_id}")
            test = await router.probe(prov)
        elif payload.alias:
            route = llm_store.get_route_by_alias(payload.alias)
            if not route:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"route not found: {payload.alias}")
            prov = llm_store.get_provider_with_key(route["provider_id"])
            if not prov:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"provider not found for route: {payload.alias}")
            test = await router.probe(prov, route["upstream_model"])
            test["alias"] = payload.alias
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="provider_id or alias required")
        return {"ok": True, "test": test}

    @app.post("/admin/llm/e2e")
    async def admin_llm_e2e(request: Request, _admin: dict = Depends(_require_admin)) -> dict:
        router = request.app.state.llm_router
        groups = llm_store.list_groups()
        all_ok = 0
        all_total = 0
        group_results = []
        for g in groups:
            gid = g["group_id"]
            routes = llm_store.list_enabled_routes_with_provider(group_id=gid)
            results = []
            provider_probes = []
            seen_providers: set[str] = set()
            for r in routes:
                prov = {"provider_id": r["provider_id"], "base_url": r["base_url"],
                        "api_key": r["api_key"], "protocol": r.get("protocol", "openai"),
                        "group_id": gid}
                t = await router.probe(prov, r["upstream_model"])
                t["alias"] = r["alias"]
                t["provider_id"] = r["provider_id"]
                t["protocol"] = r.get("protocol", "openai")
                t["upstream_model"] = r["upstream_model"]
                results.append(t)
                if r["provider_id"] not in seen_providers:
                    seen_providers.add(r["provider_id"])
                    pt = await router.probe(prov)
                    pt["provider_id"] = r["provider_id"]
                    provider_probes.append(pt)
            ok_count = sum(1 for r in results if r.get("ok"))
            prov_ok = sum(1 for p in provider_probes if p.get("ok"))
            all_ok += ok_count
            all_total += len(results)
            group_results.append({
                "group_id": gid, "group_name": g["name"],
                "passed": ok_count, "total": len(results),
                "providers_passed": prov_ok, "providers_total": len(provider_probes),
                "results": results, "provider_probes": provider_probes,
            })
        summary = f"PASS ({all_ok}/{all_total})" if all_ok == all_total else f"FAIL ({all_ok}/{all_total})"
        return {"ok": True, "summary": summary, "group_results": group_results}

    # ==================== Proxy: OpenAI-compatible ====================

    @app.post("/v1/chat/completions")
    async def v1_chat_completions(request: Request, key: dict[str, Any] = Depends(_resolve_llm_api_key)):
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body")
        if not isinstance(body, dict):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Body must be a JSON object")
        router = request.app.state.llm_router
        group_id = key.get("group_id", "")
        openai_resolved = router.resolve_route(body.get("model", ""), group_id=group_id, required_protocol="openai")
        if not openai_resolved:
            any_route = llm_store.get_route_by_alias_in_group(body.get("model", ""), group_id=group_id)
            if any_route:
                prov = llm_store.get_provider_with_key_in_group(any_route["provider_id"], group_id)
                actual_proto = (prov or {}).get("protocol", "openai")
                msg = (f"model '{body.get('model','')}' is bound to {actual_proto} provider "
                       f"in group '{group_id}', not openai")
            else:
                msg = f"model '{body.get('model','')}' not found in group '{group_id}'"
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        if body.get("stream"):
            return StreamingResponse(
                router.stream(body, api_key_id=key["key_id"], protocol="openai", resolved=openai_resolved),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        try:
            result = await router.complete(body, api_key_id=key["key_id"], protocol="openai", resolved=openai_resolved)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        except Exception as exc:
            logger.error("LLM upstream error: %s", exc)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"upstream error: {exc}")
        return JSONResponse(result)

    @app.get("/v1/models")
    async def v1_models(request: Request, key: dict[str, Any] = Depends(_resolve_llm_api_key)) -> JSONResponse:
        group_id = key.get("group_id", "")
        return JSONResponse(request.app.state.llm_router.list_models(group_id=group_id or None))

    # ==================== Proxy: Anthropic-compatible ====================

    @app.post("/v1/messages/count_tokens")
    async def v1_count_tokens(request: Request, key: dict[str, Any] = Depends(_resolve_llm_api_key)) -> JSONResponse:
        try:
            req = await request.json()
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body")
        if not isinstance(req, dict):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Body must be a JSON object")
        return JSONResponse({"input_tokens": _estimate_tokens(req)})

    @app.post("/v1/messages")
    async def v1_messages(request: Request, key: dict[str, Any] = Depends(_resolve_llm_api_key)):
        try:
            req = await request.json()
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body")
        if not isinstance(req, dict):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Body must be a JSON object")

        alias = req.get("model", "")
        router = request.app.state.llm_router
        group_id = key.get("group_id", "")
        resolved = router.resolve_route(alias, group_id=group_id, required_protocol="anthropic")
        if not resolved:
            any_route = llm_store.get_route_by_alias_in_group(alias, group_id=group_id)
            if any_route:
                prov = llm_store.get_provider_with_key_in_group(any_route["provider_id"], group_id)
                actual_proto = (prov or {}).get("protocol", "openai")
                msg = (f"model '{alias}' is bound to {actual_proto} provider in group "
                       f"'{group_id}', not anthropic")
            else:
                msg = f"model '{alias}' not found in group '{group_id}'"
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"type": "not_found_error", "message": msg},
            )
        route, provider = resolved
        forward_body = dict(req)
        forward_body["model"] = route["upstream_model"]

        if req.get("stream"):
            return StreamingResponse(
                router.stream(forward_body, api_key_id=key["key_id"], protocol="anthropic", resolved=resolved),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        try:
            anthropic_resp = await router.complete(
                forward_body, api_key_id=key["key_id"], protocol="anthropic", resolved=resolved,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"type": "not_found_error", "message": str(exc)},
            )
        except Exception as exc:
            logger.error("Anthropic LLM upstream error: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"type": "upstream_error", "message": f"upstream error: {exc}"},
            )
        return JSONResponse(anthropic_resp)

    # ==================== Proxy: Generic generation ====================

    @app.post("/v1/generations")
    async def v1_generations(request: Request, key: dict[str, Any] = Depends(_resolve_llm_api_key)):
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body")
        if not isinstance(body, dict):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Body must be a JSON object")

        alias = body.get("model", "")
        group_id = key.get("group_id", "")
        router = request.app.state.llm_router
        resolved = router.resolve_route(alias, group_id=group_id)
        if not resolved:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"model '{alias}' not found in group '{group_id}'",
            )
        route = resolved[0]
        upstream_path = (route.get("upstream_path") or "").strip()
        if not upstream_path:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"route '{alias}' has no upstream_path configured.",
            )

        extra_headers: dict[str, str] = {}
        for hname, hval in request.headers.items():
            lname = hname.lower()
            if lname.startswith("x-dashscope-") or lname == "accept":
                extra_headers[hname] = hval

        try:
            result = await router.forward_to_path(body, resolved, api_key_id=key["key_id"], extra_headers=extra_headers)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
        except Exception as exc:
            logger.error("Generation upstream error: %s", exc)
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"upstream error: {exc}")
        return JSONResponse(result)

    # ==================== Health ====================

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "version": "0.1.0"}

    # ==================== Web UI ====================

    if WEB_DIR.exists():
        app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

    return app
