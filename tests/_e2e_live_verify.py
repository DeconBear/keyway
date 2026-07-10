"""Live end-to-end verification: real mock upstream + Keyway ASGI app.

Uses httpx ASGITransport for Keyway (reliable on Windows) and a real
ThreadingHTTPServer as the upstream provider.

Run:  python tests/_e2e_live_verify.py
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from keyway.app import create_app  # noqa: E402
from keyway.llm_router import LLMRouter  # noqa: E402


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class _MockUpstream(BaseHTTPRequestHandler):
    """Minimal OpenAI + Anthropic compatible upstream."""

    def log_message(self, fmt: str, *args) -> None:
        return

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def _json(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path.rstrip("/").endswith("/models"):
            self._json(200, {"data": [{"id": "mock-model"}]})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        body = self._read_json()
        path = self.path

        if path.endswith("/chat/completions") or path.endswith("/v1/chat/completions"):
            model = body.get("model", "mock")
            msgs = body.get("messages") or []
            has_image = False
            for m in msgs:
                c = m.get("content")
                if isinstance(c, list) and any(
                    isinstance(b, dict) and b.get("type") == "image_url" for b in c
                ):
                    has_image = True
            blob = json.dumps(msgs)
            if has_image:
                content = "a red apple on a table"
            elif "judge" in model or "Synthesize" in blob or "candidate answers" in blob.lower():
                content = "fused-final-answer"
            else:
                content = f"ok-from-{model}"
            self._json(200, {
                "id": "chatcmpl-2",
                "object": "chat.completion",
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
            })
            return

        if path.endswith("/messages") or path.endswith("/v1/messages"):
            model = body.get("model", "mock")
            self._json(200, {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": f"anthropic-ok-{model}"}],
                "model": model,
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 4, "output_tokens": 3},
            })
            return

        if "image-synthesis" in path:
            self._json(200, {"output": {"task_id": "task-e2e", "task_status": "PENDING"}})
            return

        self._json(404, {"error": f"unknown path {path}"})


def _start_mock(port: int) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer(("127.0.0.1", port), _MockUpstream)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    # wait until accepting
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return srv
        except OSError:
            time.sleep(0.05)
    return srv


class Report:
    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0

    def check(self, name: str, cond: bool, detail: str = "") -> None:
        if cond:
            self.passed += 1
            print(f"PASS  {name}" + (f" — {detail}" if detail else ""))
        else:
            self.failed += 1
            print(f"FAIL  {name} — {detail or 'assertion failed'}")


def main() -> int:
    report = Report()
    mock_port = _free_port()
    admin = "e2e-admin-token"
    secret = secrets.token_urlsafe(32)
    mock_base = f"http://127.0.0.1:{mock_port}/v1"
    mock_anth = f"http://127.0.0.1:{mock_port}"

    mock = _start_mock(mock_port)
    tmp = tempfile.TemporaryDirectory(prefix="keyway-e2e-")
    data_dir = Path(tmp.name)

    os.environ["KEYWAY_HOST"] = "127.0.0.1"
    os.environ["KEYWAY_PORT"] = "9233"
    os.environ["KEYWAY_DATA_DIR"] = str(data_dir)
    os.environ["KEYWAY_SECRET"] = secret
    os.environ["KEYWAY_ADMIN_TOKEN"] = admin
    os.environ.pop("KEYWAY_DESKTOP_MODE", None)

    try:
        app = create_app()
        h = {"X-Admin-Token": admin}

        with TestClient(app) as c:
            # health
            r = c.get("/health")
            report.check("GET /health", r.status_code == 200 and r.json().get("ok") is True, r.text[:120])

            r = c.post("/admin/login", json={"token": admin})
            report.check("POST /admin/login", r.status_code == 200, r.text[:120])

            r = c.get("/admin/session", headers=h)
            report.check("GET /admin/session", r.status_code == 200)

            # providers
            r = c.post("/admin/llm/groups/default/providers", headers=h, json={
                "provider_id": "mock-oai", "name": "Mock OpenAI",
                "base_url": mock_base, "api_key": "sk-mock", "protocol": "openai",
            })
            report.check("create openai provider", r.status_code == 200, r.text[:160])

            r = c.post("/admin/llm/groups/default/providers", headers=h, json={
                "provider_id": "mock-oai-2", "name": "Mock OpenAI 2",
                "base_url": mock_base, "api_key": "sk-mock-2", "protocol": "openai",
            })
            report.check("create openai provider 2", r.status_code == 200)

            r = c.post("/admin/llm/groups/default/providers", headers=h, json={
                "provider_id": "mock-ant", "name": "Mock Anthropic",
                "base_url": mock_anth, "api_key": "ant-mock", "protocol": "anthropic",
            })
            report.check("create anthropic provider", r.status_code == 200, r.text[:160])

            # routes
            r = c.post("/admin/llm/groups/default/routes", headers=h, json={
                "alias": "chat", "provider_id": "mock-oai", "upstream_model": "mock-model",
            })
            report.check("create direct route", r.status_code == 200, r.text[:160])

            r = c.post("/admin/llm/groups/default/routes", headers=h, json={
                "alias": "claude", "provider_id": "mock-ant", "upstream_model": "claude-mock",
            })
            report.check("create anthropic route", r.status_code == 200)

            r = c.post("/admin/llm/groups/default/routes", headers=h, json={
                "alias": "vl", "provider_id": "mock-oai", "upstream_model": "vision-mock",
            })
            report.check("create vision route", r.status_code == 200)

            r = c.post("/admin/llm/groups/default/routes", headers=h, json={
                "alias": "judge", "provider_id": "mock-oai", "upstream_model": "judge-model",
            })
            report.check("create judge route", r.status_code == 200)

            r = c.post("/admin/llm/groups/default/routes", headers=h, json={
                "alias": "smart", "provider_id": "mock-oai", "upstream_model": "m1",
                "mode": "auto-select",
            })
            report.check("create auto-select route", r.status_code == 200)
            smart_id = r.json()["route"]["route_id"]
            r = c.post(f"/admin/llm/routes/{smart_id}/providers", headers=h, json={
                "provider_id": "mock-oai", "upstream_model": "m1", "priority": 0,
            })
            report.check("add route-provider p1", r.status_code == 200, r.text[:160])
            r = c.post(f"/admin/llm/routes/{smart_id}/providers", headers=h, json={
                "provider_id": "mock-oai-2", "upstream_model": "m2", "priority": 1,
            })
            report.check("add route-provider p2", r.status_code == 200, r.text[:160])

            r = c.post("/admin/llm/groups/default/routes", headers=h, json={
                "alias": "text-adapt", "provider_id": "mock-oai", "upstream_model": "text-model",
                "mode": "adapter",
                "adapter_config": json.dumps({"vision_alias": "vl", "fallback": "error"}),
            })
            report.check("create adapter route", r.status_code == 200)

            r = c.post("/admin/llm/groups/default/routes", headers=h, json={
                "alias": "fuse", "provider_id": "mock-oai", "upstream_model": "m1",
                "mode": "fusion",
                "fusion_config": json.dumps({
                    "judge_alias": "judge",
                    "strategy": "compare_and_synthesize",
                    "min_candidates": 2,
                }),
            })
            report.check("create fusion route", r.status_code == 200)
            fuse_id = r.json()["route"]["route_id"]
            c.post(f"/admin/llm/routes/{fuse_id}/providers", headers=h, json={
                "provider_id": "mock-oai", "upstream_model": "m1", "priority": 0,
            })
            c.post(f"/admin/llm/routes/{fuse_id}/providers", headers=h, json={
                "provider_id": "mock-oai-2", "upstream_model": "m2", "priority": 1,
            })

            r = c.post("/admin/llm/groups/default/routes", headers=h, json={
                "alias": "img-gen", "provider_id": "mock-oai", "upstream_model": "img-model",
                "upstream_path": "services/aigc/text2image/image-synthesis",
            })
            report.check("create generation route", r.status_code == 200)

            # API key
            r = c.post("/admin/llm/groups/default/keys", headers=h, json={"name": "e2e"})
            report.check("create api key", r.status_code == 200 and "plaintext" in r.json(), r.text[:160])
            key = r.json()["plaintext"]
            auth = {"Authorization": f"Bearer {key}"}

            # proxy
            r = c.get("/v1/models", headers=auth)
            ids = {m["id"] for m in r.json().get("data", [])}
            report.check("GET /v1/models", r.status_code == 200 and "chat" in ids, str(sorted(ids)))

            r = c.post("/v1/chat/completions", headers=auth, json={
                "model": "chat", "messages": [{"role": "user", "content": "hi"}],
            })
            report.check(
                "POST /v1/chat/completions direct",
                r.status_code == 200 and "ok-from-mock-model" in r.text,
                r.text[:200],
            )

            r = c.post("/v1/messages", headers=auth, json={
                "model": "claude", "max_tokens": 32,
                "messages": [{"role": "user", "content": "hi"}],
            })
            report.check(
                "POST /v1/messages anthropic",
                r.status_code == 200 and "anthropic-ok" in r.text,
                r.text[:200],
            )

            r = c.post("/v1/messages/count_tokens", headers=auth, json={
                "model": "claude", "messages": [{"role": "user", "content": "hello world"}],
            })
            report.check(
                "POST /v1/messages/count_tokens",
                r.status_code == 200 and r.json().get("input_tokens", 0) >= 1,
            )

            r = c.post("/v1/chat/completions", headers=auth, json={
                "model": "smart", "messages": [{"role": "user", "content": "hi"}],
            })
            report.check(
                "POST /v1/chat/completions auto-select",
                r.status_code == 200 and ("ok-from-m1" in r.text or "ok-from-m2" in r.text),
                r.text[:200],
            )

            r = c.post("/v1/chat/completions", headers=auth, json={
                "model": "text-adapt",
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": "what is this?"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
                ]}],
            })
            report.check(
                "POST /v1/chat/completions adapter",
                r.status_code == 200 and "ok-from-text-model" in r.text,
                r.text[:240],
            )

            r = c.post("/v1/chat/completions", headers=auth, json={
                "model": "fuse", "messages": [{"role": "user", "content": "2+2?"}],
            })
            report.check(
                "POST /v1/chat/completions fusion",
                r.status_code == 200 and "X-Keyway-Fusion-Id" in r.headers,
                f"status={r.status_code} body={r.text[:200]} hdr={r.headers.get('X-Keyway-Fusion', '')}",
            )

            r = c.post("/v1/messages", headers=auth, json={
                "model": "fuse", "max_tokens": 16,
                "messages": [{"role": "user", "content": "hi"}],
            })
            report.check("POST /v1/messages fusion rejected", r.status_code == 400, r.text[:160])

            r = c.post("/v1/generations", headers=auth, json={
                "model": "img-gen", "input": {"prompt": "cat"},
            })
            report.check(
                "POST /v1/generations",
                r.status_code == 200 and "task-e2e" in r.text,
                r.text[:200],
            )

            # admin diagnostics against real mock upstream
            r = c.post("/admin/llm/test", headers=h, json={"alias": "chat"})
            report.check(
                "POST /admin/llm/test alias",
                r.status_code == 200 and r.json().get("test", {}).get("ok") is True,
                r.text[:200],
            )

            r = c.post("/admin/llm/e2e", headers=h)
            summary = r.json().get("summary", "") if r.status_code == 200 else r.text
            report.check(
                "POST /admin/llm/e2e",
                r.status_code == 200 and str(summary).startswith("PASS"),
                summary,
            )

            r = c.get("/admin/llm/health", headers=h, params={"group_id": "default"})
            report.check("GET /admin/llm/health", r.status_code == 200)

            r = c.get("/admin/llm/logs", headers=h, params={"limit": 50})
            logs = r.json().get("logs", []) if r.status_code == 200 else []
            report.check("GET /admin/llm/logs", r.status_code == 200 and len(logs) >= 1, f"n={len(logs)}")

        # desktop mode host override
        os.environ["KEYWAY_DESKTOP_MODE"] = "1"
        os.environ["KEYWAY_HOST"] = "0.0.0.0"
        app2 = create_app()
        report.check("desktop mode forces loopback host", app2.state.settings.host == "127.0.0.1")
        os.environ.pop("KEYWAY_DESKTOP_MODE", None)

        report.check(
            "anthropic url no double /v1",
            LLMRouter._anthropic_messages_url("https://api.anthropic.com/v1")
            == "https://api.anthropic.com/v1/messages",
        )

    finally:
        try:
            mock.shutdown()
        except Exception:
            pass
        try:
            tmp.cleanup()
        except Exception:
            pass

    print()
    print(f"Result: {report.passed} passed, {report.failed} failed")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
