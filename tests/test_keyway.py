"""Tests for Keyway LLM Router.

Covers:
- LLMStore CRUD (providers, routes, api_keys, tool_providers, request_logs)
- LLM key generation, hashing, prefix
- LLMRouter.resolve_route (enabled / disabled / missing)
- LLMRouter.complete with tool-use loop (Tavily integration mocked)
- LLMRouter.stream passthrough
- HTTP endpoints: /v1/chat/completions (Bearer auth, stream + non-stream)
- HTTP endpoints: /v1/models
- HTTP endpoints: /v1/messages (Anthropic)
- Admin CRUD for providers / routes / keys / tool_providers / logs (X-Admin-Token)
- Encryption at rest
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
import httpx
from fastapi.testclient import TestClient

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if str(SRC_ROOT) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SRC_ROOT))

from keyway.llm_keys import generate_key, hash_key, key_prefix
from keyway.llm_router import LLMRouter
from keyway.llm_store import LLMStore
from keyway.app import create_app

SECRET = "test-secret-not-for-production-use-32chars"
ADMIN_TOKEN = "test-admin-token-fixed"


# ---------- fixtures ----------

@pytest.fixture()
def keyway_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Set up an isolated data dir and return its path."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("KEYWAY_DATA_DIR", str(data_dir))
    monkeypatch.setenv("KEYWAY_SECRET", SECRET)
    monkeypatch.setenv("KEYWAY_ADMIN_TOKEN", ADMIN_TOKEN)
    monkeypatch.setenv("KEYWAY_HOST", "127.0.0.1")
    monkeypatch.setenv("KEYWAY_PORT", "9233")
    return data_dir


@pytest.fixture()
def client(keyway_env: Path) -> TestClient:
    with TestClient(create_app()) as c:
        yield c


ADMIN_HEADERS = {"X-Admin-Token": ADMIN_TOKEN}


# ---------- LLM keys ----------

def test_key_format_and_hash_roundtrip() -> None:
    k = generate_key()
    assert k.startswith("db_sk_")
    assert len(k) > 20
    assert hash_key(k) == hash_key(k)
    assert hash_key(k) != hash_key(k[:-1] + "x")
    p = key_prefix(k)
    assert p.startswith("db_sk_")
    assert p.endswith("...")


# ---------- LLMStore CRUD ----------

def test_provider_crud(keyway_env: Path) -> None:
    s = LLMStore(keyway_env / "keyway.db", secret=SECRET)
    s.create_provider("deepseek", "DeepSeek", "https://api.deepseek.com/v1", "sk-real-1", "main")
    p = s.get_provider("deepseek")
    assert p is not None and p["name"] == "DeepSeek"
    assert p["api_key_set"] is True
    assert "sk-real-1" not in str(p), "api_key must be masked on read"
    s.update_provider("deepseek", name="DeepSeek Co")
    assert s.get_provider("deepseek")["name"] == "DeepSeek Co"
    s.create_provider("minimax", "minimax", "https://api.minimax.chat/v1", "k2")
    assert len(s.list_providers()) == 2
    assert s.delete_provider("deepseek") is True
    assert s.get_provider("deepseek") is None
    s.close()


def test_route_cascade(keyway_env: Path) -> None:
    s = LLMStore(keyway_env / "keyway.db", secret=SECRET)
    s.create_provider("p1", "P1", "https://x/v1", "k")
    s.create_route("alias-1", "p1", "model-x")
    r = s.get_route_by_alias("alias-1")
    assert r is not None and r["upstream_model"] == "model-x"
    s.update_route(r["route_id"], upstream_model="model-y")
    assert s.get_route_by_alias("alias-1")["upstream_model"] == "model-y"
    s.delete_provider("p1")
    assert s.get_route_by_alias("alias-1") is None
    s.close()


def test_provider_api_key_encrypted_at_rest(keyway_env: Path) -> None:
    SECRET_VAL = SECRET
    s = LLMStore(keyway_env / "keyway.db", secret=SECRET_VAL)
    s.create_provider_in_group("default", "p1", "P1", "https://x/v1", "sk-upstream-secret")
    with_key = s.get_provider_with_key("p1")
    assert with_key["api_key"] == "sk-upstream-secret"
    con = sqlite3.connect(str(keyway_env / "keyway.db"))
    raw = con.execute("SELECT api_key FROM llm_providers WHERE provider_id='p1'").fetchone()[0]
    con.close()
    assert raw != "sk-upstream-secret", "api_key must be encrypted at rest"
    assert "sk-upstream-secret" not in raw
    masked = s.get_provider("p1")
    assert "sk-upstream-secret" not in str(masked)
    s.close()


def test_tool_provider_api_key_encrypted_at_rest(keyway_env: Path) -> None:
    s = LLMStore(keyway_env / "keyway.db", secret=SECRET)
    s.create_tool_provider_in_group("default", "tavily", "Tavily", "tvly-real-key")
    assert s.get_tool_provider_with_key("tavily")["api_key"] == "tvly-real-key"
    con = sqlite3.connect(str(keyway_env / "keyway.db"))
    raw = con.execute("SELECT api_key FROM llm_tool_providers WHERE tool_id='tavily'").fetchone()[0]
    con.close()
    assert raw != "tvly-real-key"
    assert "tvly-real-key" not in raw
    s.close()


def test_key_and_log_flow(keyway_env: Path) -> None:
    s = LLMStore(keyway_env / "keyway.db", secret=SECRET)
    s.create_provider("p1", "P1", "https://x/v1", "k")
    k = generate_key()
    s.create_key(hash_key(k), key_prefix(k), "test key")
    row = s.get_key_by_hash(hash_key(k))
    assert row is not None and row["name"] == "test key"
    s.log_request(api_key_id=row["key_id"], route_alias="alias-1", provider_id="p1",
                  upstream_model="model-x", status_code=200, request_tokens=10,
                  response_tokens=20, latency_ms=123)
    logs = s.list_logs(api_key_id=row["key_id"])
    assert len(logs) == 1
    assert logs[0]["latency_ms"] == 123
    stats = s.log_stats_for_key(row["key_id"])
    assert stats["total"] == 1 and stats["ok"] == 1
    s.touch_key_used(row["key_id"])
    assert s.get_key_by_hash(hash_key(k))["last_used_at"] is not None
    s.close()


def test_tool_provider_crud(keyway_env: Path) -> None:
    s = LLMStore(keyway_env / "keyway.db", secret=SECRET)
    s.create_tool_provider("tavily", "Tavily", "tvly-real-key")
    t = s.get_tool_provider("tavily")
    assert t is not None and t["api_key_set"] is True
    assert "tvly-real-key" not in str(t)
    assert s.get_tool_provider_with_key("tavily")["api_key"] == "tvly-real-key"
    s.update_tool_provider("tavily", api_key="tvly-new")
    assert s.get_tool_provider_with_key("tavily")["api_key"] == "tvly-new"
    s.close()


# ---------- LLMRouter resolution ----------

def test_router_resolve_route_disabled_or_missing(keyway_env: Path) -> None:
    s = LLMStore(keyway_env / "keyway.db", secret=SECRET)
    s.create_provider("p1", "P1", "https://x/v1", "k")
    s.create_route("alias-1", "p1", "model-x")
    r = LLMRouter(s)
    resolved = r.resolve_route("alias-1")
    assert resolved is not None
    s.update_route(resolved[0]["route_id"], enabled=False)
    assert r.resolve_route("alias-1") is None
    s.close()


# ---------- LLMRouter.forward_to_path ----------

def test_forward_to_path_passes_extra_headers_and_keeps_auth(keyway_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = LLMStore(keyway_env / "keyway.db", secret=SECRET)
    s.create_provider_in_group("default", "p1", "P1", "https://x/v1", "sk-provider-secret", protocol="openai")
    s.create_route_in_group("default", "alias-1", "p1", "model-x",
                            upstream_path="services/aigc/text2image/image-synthesis")
    r = LLMRouter(s)

    captured: dict = {}

    class _FakeResp:
        status_code = 200
        def json(self):
            return {"output": {"task_id": "t-1", "task_status": "PENDING"}}

    class _FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["model"] = (json or {}).get("model")
            return _FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    import asyncio
    resolved = r.resolve_route("alias-1", group_id="default")
    out = asyncio.run(r.forward_to_path(
        {"model": "alias-1", "input": {"prompt": "cat"}},
        resolved,
        extra_headers={"X-DashScope-Async": "enable", "Authorization": "Bearer db_sk_attacker"},
    ))
    assert out["output"]["task_id"] == "t-1"
    assert captured["url"] == "https://x/v1/services/aigc/text2image/image-synthesis"
    assert captured["model"] == "model-x"
    assert captured["headers"]["X-DashScope-Async"] == "enable"
    assert captured["headers"]["Authorization"] == "Bearer sk-provider-secret"
    s.close()


# ---------- LLMRouter complete ----------

def test_router_complete_simple_response(keyway_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = LLMStore(keyway_env / "keyway.db", secret=SECRET)
    s.create_provider("p1", "P1", "https://x/v1", "k")
    s.create_route("alias-1", "p1", "model-x")
    r = LLMRouter(s)

    async def fake_complete(self, body, api_key_id=None, protocol=None, resolved=None):
        return {
            "id": "x", "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        }
    monkeypatch.setattr(LLMRouter, "complete", fake_complete)
    import asyncio
    out = asyncio.run(r.complete({"model": "alias-1", "messages": []}))
    assert out["choices"][0]["message"]["content"] == "hi"
    s.close()


def test_router_complete_with_tool_loop(keyway_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = LLMStore(keyway_env / "keyway.db", secret=SECRET)
    s.create_provider("p1", "P1", "https://x/v1", "k")
    s.create_route("alias-1", "p1", "model-x")
    s.create_tool_provider("tavily", "Tavily", "tvly-test")
    r = LLMRouter(s)

    call_count = {"n": 0}

    async def fake_call_non_stream(self, provider, model, body):
        call_count["n"] += 1
        msgs = body.get("messages", [])
        has_tool = any(m.get("role") == "tool" for m in msgs)
        if has_tool:
            return {
                "id": "x", "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        return {
            "id": "x", "object": "chat.completion",
            "choices": [{"index": 0, "message": {
                "role": "assistant", "content": None,
                "tool_calls": [{
                    "id": "call_1", "type": "function",
                    "function": {"name": "tavily_search", "arguments": json.dumps({"query": "q"})},
                }],
            }, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        }
    monkeypatch.setattr(LLMRouter, "_call_upstream_non_stream", fake_call_non_stream)

    from keyway import llm_router as llm_router_mod
    async def fake_execute_tool(name, args, providers):
        return json.dumps({"results": [{"title": "t", "url": "u", "content": "c"}]})
    monkeypatch.setattr(llm_router_mod, "execute_tool", fake_execute_tool)

    import asyncio
    out = asyncio.run(r.complete({"model": "alias-1", "messages": []}))
    assert call_count["n"] == 2, f"expected 2 calls, got {call_count['n']}"
    assert out["choices"][0]["message"]["content"] == "done"
    logs = s.list_logs()
    assert len(logs) == 2
    s.close()


# ---------- HTTP: /v1/chat/completions ----------

def test_v1_chat_completions_requires_bearer(keyway_env: Path) -> None:
    with TestClient(create_app()) as c:
        r = c.post("/v1/chat/completions", json={"model": "x", "messages": []})
        assert r.status_code == 401


def test_v1_chat_completions_invalid_key(keyway_env: Path) -> None:
    with TestClient(create_app()) as c:
        r = c.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer db_sk_boguskeyvalue"},
            json={"model": "x", "messages": []},
        )
        assert r.status_code == 401


def test_v1_chat_completions_success(keyway_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = LLMStore(keyway_env / "keyway.db", secret=SECRET)
    s.create_provider("p1", "P1", "https://x/v1", "k")
    s.create_route("alias-1", "p1", "model-x")
    plaintext = generate_key()
    s.create_key(hash_key(plaintext), key_prefix(plaintext), "test")
    s.close()

    async def fake_complete(self, body, api_key_id=None, protocol=None, resolved=None):
        return {"id": "x", "choices": [{"message": {"role": "assistant", "content": "ok"}}]}
    monkeypatch.setattr(LLMRouter, "complete", fake_complete)

    with TestClient(create_app()) as c:
        r = c.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {plaintext}"},
            json={"model": "alias-1", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["choices"][0]["message"]["content"] == "ok"


def test_v1_chat_completions_streaming(keyway_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = LLMStore(keyway_env / "keyway.db", secret=SECRET)
    s.create_provider("p1", "P1", "https://x/v1", "k")
    s.create_route("alias-1", "p1", "model-x")
    plaintext = generate_key()
    s.create_key(hash_key(plaintext), key_prefix(plaintext), "test")
    s.close()

    async def fake_stream(self, body, api_key_id=None, protocol=None, resolved=None):
        for chunk in (b"data: a\n\n", b"data: b\n\n", b"data: [DONE]\n\n"):
            yield chunk
    monkeypatch.setattr(LLMRouter, "stream", fake_stream)

    with TestClient(create_app()) as c:
        r = c.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {plaintext}"},
            json={"model": "alias-1", "stream": True, "messages": []},
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = b"".join(r.iter_bytes()).decode()
        assert "data: a" in body and "data: b" in body and "[DONE]" in body


# ---------- HTTP: /v1/models ----------

def test_v1_models_lists_enabled_routes(keyway_env: Path) -> None:
    s = LLMStore(keyway_env / "keyway.db", secret=SECRET)
    s.create_provider("p1", "P1", "https://x/v1", "k")
    s.create_route("a-on", "p1", "m1")
    s.create_route("a-off", "p1", "m2")
    s.update_route(s.get_route_by_alias("a-off")["route_id"], enabled=False)
    plaintext = generate_key()
    s.create_key(hash_key(plaintext), key_prefix(plaintext), "t")
    s.close()
    with TestClient(create_app()) as c:
        r = c.get("/v1/models", headers={"Authorization": f"Bearer {plaintext}"})
        assert r.status_code == 200
        ids = [m["id"] for m in r.json()["data"]]
        assert "a-on" in ids and "a-off" not in ids


# ---------- HTTP: /v1/messages (Anthropic) ----------

def test_v1_messages_success(keyway_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = LLMStore(keyway_env / "keyway.db", secret=SECRET)
    s.create_provider_in_group("default", "p1", "P1", "https://api.anthropic.com", "sk-ant", protocol="anthropic")
    s.create_route_in_group("default", "claude-test", "p1", "claude-sonnet-4")
    plaintext = generate_key()
    s.create_key_in_group("default", hash_key(plaintext), key_prefix(plaintext), "test")
    s.close()

    async def fake_complete(self, body, api_key_id=None, protocol=None, resolved=None):
        return {
            "id": "msg_test", "type": "message", "role": "assistant",
            "content": [{"type": "text", "text": "hello"}],
            "model": "claude-sonnet-4", "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
    monkeypatch.setattr(LLMRouter, "complete", fake_complete)

    with TestClient(create_app()) as c:
        r = c.post(
            "/v1/messages",
            headers={"Authorization": f"Bearer {plaintext}"},
            json={"model": "claude-test", "max_tokens": 16, "messages": [{"role": "user", "content": "hi"}]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["content"][0]["text"] == "hello"


def test_v1_messages_protocol_mismatch(keyway_env: Path) -> None:
    s = LLMStore(keyway_env / "keyway.db", secret=SECRET)
    s.create_provider_in_group("default", "p1", "P1", "https://x/v1", "k", protocol="openai")
    s.create_route_in_group("default", "alias-1", "p1", "model-x")
    plaintext = generate_key()
    s.create_key_in_group("default", hash_key(plaintext), key_prefix(plaintext), "test")
    s.close()
    with TestClient(create_app()) as c:
        r = c.post(
            "/v1/messages",
            headers={"Authorization": f"Bearer {plaintext}"},
            json={"model": "alias-1", "max_tokens": 16, "messages": [{"role": "user", "content": "hi"}]},
        )
        assert r.status_code == 404


# ---------- HTTP: admin CRUD ----------

def test_admin_endpoints_require_auth(keyway_env: Path) -> None:
    with TestClient(create_app()) as c:
        r = c.get("/admin/llm/groups")
        assert r.status_code == 401


def test_admin_login(keyway_env: Path) -> None:
    with TestClient(create_app()) as c:
        r = c.post("/admin/login", json={"token": "wrong"})
        assert r.status_code == 401
        r = c.post("/admin/login", json={"token": ADMIN_TOKEN})
        assert r.status_code == 200


def test_admin_provider_full_crud(keyway_env: Path) -> None:
    with TestClient(create_app()) as c:
        r = c.post("/admin/llm/groups/default/providers", json={
            "provider_id": "deepseek", "name": "DeepSeek",
            "base_url": "https://api.deepseek.com/v1", "api_key": "sk-real",
        }, headers=ADMIN_HEADERS)
        assert r.status_code == 200, r.text
        assert "sk-real" not in r.text
        r = c.get("/admin/llm/groups/default/providers", headers=ADMIN_HEADERS)
        assert any(p["provider_id"] == "deepseek" for p in r.json()["providers"])
        r = c.patch("/admin/llm/providers/deepseek", json={"name": "DeepSeek v2"}, headers=ADMIN_HEADERS)
        assert r.json()["provider"]["name"] == "DeepSeek v2"
        r = c.delete("/admin/llm/providers/deepseek", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        r = c.get("/admin/llm/groups/default/providers", headers=ADMIN_HEADERS)
        assert all(p["provider_id"] != "deepseek" for p in r.json()["providers"])


def test_admin_key_create_returns_plaintext_once(keyway_env: Path) -> None:
    with TestClient(create_app()) as c:
        r = c.post("/admin/llm/groups/default/keys", json={"name": "claude-code"}, headers=ADMIN_HEADERS)
        assert r.status_code == 200, r.text
        body = r.json()
        plaintext = body["plaintext"]
        assert plaintext.startswith("db_sk_")
        assert body["key"]["key_prefix"].startswith("db_sk_")
        r = c.get("/admin/llm/groups/default/keys", headers=ADMIN_HEADERS)
        for k in r.json()["keys"]:
            assert plaintext not in str(k)


def test_admin_key_plaintext_retrieval(keyway_env: Path) -> None:
    with TestClient(create_app()) as c:
        r = c.post("/admin/llm/groups/default/keys", json={"name": "test-key"}, headers=ADMIN_HEADERS)
        plaintext = r.json()["plaintext"]
        key_id = r.json()["key"]["key_id"]
        r = c.get(f"/admin/llm/keys/{key_id}/plaintext", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        assert r.json()["plaintext"] == plaintext


def test_admin_keys_and_routes_crud(keyway_env: Path) -> None:
    with TestClient(create_app()) as c:
        c.post("/admin/llm/groups/default/providers", json={
            "provider_id": "p1", "name": "P", "base_url": "https://x/v1", "api_key": "k",
        }, headers=ADMIN_HEADERS)
        r = c.post("/admin/llm/groups/default/routes", json={
            "alias": "alias-1", "provider_id": "p1", "upstream_model": "model-x",
        }, headers=ADMIN_HEADERS)
        assert r.status_code == 200
        route_id = r.json()["route"]["route_id"]
        r = c.patch(f"/admin/llm/routes/{route_id}", json={"upstream_model": "model-y"}, headers=ADMIN_HEADERS)
        assert r.json()["route"]["upstream_model"] == "model-y"
        c.delete(f"/admin/llm/routes/{route_id}", headers=ADMIN_HEADERS)


def test_admin_tool_providers_and_logs(keyway_env: Path) -> None:
    with TestClient(create_app()) as c:
        r = c.post("/admin/llm/groups/default/tool-providers", json={
            "tool_id": "tavily", "name": "Tavily", "api_key": "tvly-x",
        }, headers=ADMIN_HEADERS)
        assert r.status_code == 200
        assert "tvly-x" not in r.text
        r = c.patch("/admin/llm/tool-providers/tavily", json={"api_key": "tvly-y"}, headers=ADMIN_HEADERS)
        assert r.status_code == 200

        s = LLMStore(keyway_env / "keyway.db", secret=SECRET)
        s.create_provider("p1", "P", "https://x/v1", "k")
        s.create_route("alias-1", "p1", "m")
        plaintext = generate_key()
        s.create_key(hash_key(plaintext), key_prefix(plaintext), "k1")
        s.log_request(api_key_id=s.get_key_by_hash(hash_key(plaintext))["key_id"],
                      route_alias="alias-1", provider_id="p1", upstream_model="m",
                      status_code=200, request_tokens=1, response_tokens=2, latency_ms=50)
        s.close()
        r = c.get("/admin/llm/logs?limit=10", headers=ADMIN_HEADERS)
        assert r.status_code == 200 and len(r.json()["logs"]) == 1


def test_admin_group_create_and_delete(keyway_env: Path) -> None:
    with TestClient(create_app()) as c:
        r = c.post("/admin/llm/groups", json={"group_id": "test-grp", "name": "Test Group"}, headers=ADMIN_HEADERS)
        assert r.status_code == 200
        assert r.json()["group"]["group_id"] == "test-grp"
        r = c.delete("/admin/llm/groups/test-grp", headers=ADMIN_HEADERS)
        assert r.status_code == 200


def test_admin_group_copy(keyway_env: Path) -> None:
    with TestClient(create_app()) as c:
        c.post("/admin/llm/groups/default/providers", json={
            "provider_id": "p1", "name": "P", "base_url": "https://x/v1", "api_key": "k",
        }, headers=ADMIN_HEADERS)
        r = c.post("/admin/llm/groups/default/copy", json={"new_name": "Copied Group", "new_group_id": "grp-copy"}, headers=ADMIN_HEADERS)
        assert r.status_code == 200, r.text
        assert r.json()["group"]["group_id"] == "grp-copy"
