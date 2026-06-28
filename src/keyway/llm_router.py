"""LLM routing core (grouped, pure-passthrough): resolves model alias
within a key's group -> provider, calls upstream OpenAI/Anthropic endpoint
unchanged, runs tool-use loop for OpenAI only, logs to request_logs.

Scope:
- No protocol translation. OpenAI inbound -> OpenAI provider; Anthropic
  inbound -> Anthropic provider. Cross-protocol requests return 404.
- Tools (e.g. Tavily) are scoped to the same group as the route. They are
  injected into the upstream request ONLY for OpenAI-protocol calls.
- Streaming: pass upstream SSE bytes through to the client as-is for both
  protocols.
- Non-streaming: OpenAI calls run a full tool loop (max MAX_TOOL_ITERATIONS
  iterations). Anthropic calls return the upstream response directly.
- Generation forwarding: generic passthrough for image/video/3D generation
  endpoints, based on route's upstream_path.
"""

from __future__ import annotations

import json
import time
from typing import Any, AsyncGenerator

import httpx

from .llm_store import LLMStore
from .llm_tools import (
    BUILTIN_TOOLS,
    execute_tool,
    parse_tool_arguments,
)


MAX_TOOL_ITERATIONS = 5


class UpstreamError(RuntimeError):
    """Raised when an upstream provider returns an error or is unreachable.

    ``status_code`` is the HTTP status from the upstream (0 for transport
    errors such as timeout / connection refused). ``retryable`` indicates
    whether the caller should attempt the next candidate (5xx and transport
    errors are retryable; 4xx are not).
    """

    def __init__(self, message: str, status_code: int = 0) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = status_code == 0 or status_code >= 500


class LLMRouter:
    def __init__(self, store: LLMStore) -> None:
        self.store = store

    # -------- route resolution (group-scoped) --------
    def resolve_route(
        self, alias: str, *, group_id: str = "", required_protocol: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """Resolve an alias within a group. If ``required_protocol`` is
        set ("openai" or "anthropic"), the provider's protocol must match.

        Falls back to flat (ungrouped) resolution when group_id is empty.
        """
        if group_id:
            route = self.store.get_route_by_alias_in_group(alias, group_id=group_id)
        else:
            route = self.store.get_route_by_alias(alias)
        if not route or not route.get("enabled"):
            return None
        if group_id:
            provider = self.store.get_provider_with_key_in_group(route["provider_id"], group_id)
        else:
            provider = self.store.get_provider_with_key(route["provider_id"])
        if not provider or not provider.get("enabled"):
            return None
        if required_protocol and (provider.get("protocol") or "openai") != required_protocol:
            return None
        return route, provider

    def resolve_route_auto(
        self, alias: str, *, group_id: str = "", required_protocol: str | None = None,
    ) -> list[tuple[dict[str, Any], dict[str, Any], str]]:
        """Resolve an alias to a ranked list of (route, provider, upstream_model)
        candidates for auto-select / fusion modes.

        Candidates come from the ``route_providers`` table (priority-ordered).
        When no ``route_providers`` rows exist, the route's primary binding is
        used as a single-element fallback so auto-select degrades gracefully.

        Filters out: disabled routes, disabled providers, protocol mismatch,
        and providers with open circuits.
        Returns candidates sorted by priority (ascending).
        """
        if group_id:
            route = self.store.get_route_by_alias_in_group(alias, group_id=group_id)
        else:
            route = self.store.get_route_by_alias(alias)
        if not route or not route.get("enabled"):
            return []

        candidates: list[tuple[dict[str, Any], dict[str, Any], str, int]] = []
        rps = self.store.list_route_providers(route["route_id"])
        for rp in rps:
            if not rp.get("enabled"):
                continue
            if group_id:
                provider = self.store.get_provider_with_key_in_group(rp["provider_id"], group_id)
            else:
                provider = self.store.get_provider_with_key(rp["provider_id"])
            if not provider or not provider.get("enabled"):
                continue
            if required_protocol and (provider.get("protocol") or "openai") != required_protocol:
                continue
            if self.store.is_circuit_open(provider.get("provider_id", "")):
                continue
            candidates.append((route, provider, rp["upstream_model"], int(rp.get("priority", 0))))

        if not candidates:
            # Fallback to primary binding (single-provider direct mode compat)
            if group_id:
                provider = self.store.get_provider_with_key_in_group(route["provider_id"], group_id)
            else:
                provider = self.store.get_provider_with_key(route["provider_id"])
            if provider and provider.get("enabled"):
                if not required_protocol or (provider.get("protocol") or "openai") == required_protocol:
                    if not self.store.is_circuit_open(provider.get("provider_id", "")):
                        candidates.append((route, provider, route["upstream_model"], 0))

        candidates.sort(key=lambda c: c[3])
        return [(r, p, m) for r, p, m, _ in candidates]

    def get_tool_definitions(self, group_id: str = "") -> list[dict[str, Any]]:
        """Return builtin tool schemas to inject into OpenAI calls."""
        if group_id:
            enabled = [p for p in self.store.list_tool_providers_in_group(group_id=group_id)
                       if p.get("enabled") and p.get("api_key_set")]
        else:
            enabled = {p["tool_id"] for p in self.store.list_tool_providers() if p.get("enabled") and p.get("api_key_set")}
        if not enabled and not group_id:
            return []
        if not group_id:
            return [schema for tid, schema in BUILTIN_TOOLS.items() if tid in enabled]
        return list(BUILTIN_TOOLS.values())

    # -------- upstream HTTP helpers --------
    async def _call_upstream_stream(
        self, provider: dict[str, Any], model: str, body: dict[str, Any]
    ) -> AsyncGenerator[bytes, None]:
        url = provider["base_url"].rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {provider['api_key']}",
            "Content-Type": "application/json",
        }
        body = {**body, "model": model, "stream": True}
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=300, write=30, pool=10)) as client:
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                if resp.status_code >= 400:
                    body_bytes = await resp.aread()
                    raise UpstreamError(
                        f"upstream {resp.status_code}: {body_bytes.decode('utf-8', errors='replace')[:300]}",
                        status_code=resp.status_code,
                    )
                async for chunk in resp.aiter_bytes():
                    yield chunk

    async def _call_upstream_non_stream(
        self, provider: dict[str, Any], model: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        url = provider["base_url"].rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {provider['api_key']}",
            "Content-Type": "application/json",
        }
        body = {**body, "model": model, "stream": False}
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=300, write=30, pool=10)) as client:
            resp = await client.post(url, json=body, headers=headers)
        if resp.status_code >= 400:
            raise UpstreamError(f"upstream {resp.status_code}: {resp.text[:300]}", status_code=resp.status_code)
        return resp.json()

    async def _call_upstream_anthropic_stream(
        self, provider: dict[str, Any], body: dict[str, Any]
    ) -> AsyncGenerator[bytes, None]:
        url = provider["base_url"].rstrip("/") + "/v1/messages"
        headers = {
            "x-api-key": provider["api_key"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = {**body, "stream": True}
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=300, write=30, pool=10)) as client:
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                if resp.status_code >= 400:
                    body_bytes = await resp.aread()
                    raise UpstreamError(
                        f"upstream {resp.status_code}: {body_bytes.decode('utf-8', errors='replace')[:300]}",
                        status_code=resp.status_code,
                    )
                async for chunk in resp.aiter_bytes():
                    yield chunk

    async def _call_upstream_anthropic_non_stream(
        self, provider: dict[str, Any], body: dict[str, Any]
    ) -> dict[str, Any]:
        url = provider["base_url"].rstrip("/") + "/v1/messages"
        headers = {
            "x-api-key": provider["api_key"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = {**body, "stream": False}
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=300, write=30, pool=10)) as client:
            resp = await client.post(url, json=body, headers=headers)
        if resp.status_code >= 400:
            raise UpstreamError(f"upstream {resp.status_code}: {resp.text[:300]}", status_code=resp.status_code)
        return resp.json()

    # -------- generic forwarding for generation endpoints --------
    async def forward_to_path(
        self, body: dict[str, Any], resolved: tuple[dict[str, Any], dict[str, Any]],
        api_key_id: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Forward a request to an upstream provider at a custom path.
        Used for generation endpoints (image, video, 3D, etc.).
        Pure passthrough — no tool loop, no streaming manipulation.

        ``extra_headers`` carries caller-supplied upstream-specific headers
        (e.g. ``X-DashScope-Async: enable``) that the generation endpoint
        whitelist-filters from the inbound request. Auth/Content-Type set
        below are authoritative — they win over any ``extra_headers`` key, so a
        caller can never override the provider credential.
        """
        route, provider = resolved
        upstream_path = (route.get("upstream_path") or "").strip()
        if not upstream_path:
            raise ValueError("upstream_path is required for generation forwarding")
        url = provider["base_url"].rstrip("/") + "/" + upstream_path.lstrip("/")
        proto = provider.get("protocol") or "openai"
        if proto == "anthropic":
            headers = {
                "x-api-key": provider["api_key"],
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
        else:
            headers = {
                "Authorization": f"Bearer {provider['api_key']}",
                "Content-Type": "application/json",
            }
        if extra_headers:
            for k, v in extra_headers.items():
                headers.setdefault(k, v)
        forward_body = dict(body)
        forward_body["model"] = route["upstream_model"]

        start = time.time()
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=300, write=30, pool=10)) as client:
                resp = await client.post(url, json=forward_body, headers=headers)
            if resp.status_code >= 400:
                raise UpstreamError(f"upstream {resp.status_code}: {resp.text[:300]}", status_code=resp.status_code)
            result = resp.json()
            latency = int((time.time() - start) * 1000)
            self._log(route["alias"], provider.get("group_id") or "",
                      provider.get("provider_id", ""), route["upstream_model"],
                      200, 0, 0, latency, "", api_key_id)
            return result
        except Exception as exc:
            latency = int((time.time() - start) * 1000)
            error_msg = f"{type(exc).__name__}: {exc}"
            self._log(route["alias"], provider.get("group_id") or "",
                      provider.get("provider_id", ""), route["upstream_model"],
                      502, 0, 0, latency, error_msg, api_key_id)
            raise

    # -------- admin-only diagnostic probe --------
    async def probe(self, provider: dict[str, Any], upstream_model: str | None = None) -> dict[str, Any]:
        """Lightweight connectivity probe (admin-only).
        If ``upstream_model`` is given: sends a 1-token chat completion.
        If absent: tries GET /models first, falls back to a chat.
        """
        base = provider["base_url"].rstrip("/")
        proto = provider.get("protocol") or "openai"
        if proto == "anthropic":
            anthropic_headers = {
                "x-api-key": provider["api_key"],
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
            openai_headers = None
        else:
            openai_headers = {
                "Authorization": f"Bearer {provider['api_key']}",
                "Content-Type": "application/json",
            }
            anthropic_headers = None
        start = time.time()
        result: dict[str, Any] = {"ok": False, "status": 0, "latency_ms": 0,
                                  "upstream_model": upstream_model, "message": ""}

        def _elapsed() -> int:
            return int((time.time() - start) * 1000)

        async def _try_chat(upstream: str) -> dict[str, Any]:
            if proto == "anthropic":
                body = {"model": upstream, "messages": [{"role": "user", "content": "Reply with OK."}],
                        "max_tokens": 16}
                try:
                    resp_json = await self._call_upstream_anthropic_non_stream(provider, body)
                except RuntimeError as exc:
                    return {"ok": False, "status": 502, "latency_ms": _elapsed(),
                            "upstream_model": upstream, "message": str(exc)[:300]}
                msg = ""
                try:
                    content = (resp_json.get("content") or [{}])[0].get("text", "")
                    msg = f"chat OK ({len(content)} chars)"
                except Exception:
                    msg = "chat OK"
                return {"ok": True, "status": 200, "latency_ms": _elapsed(),
                        "upstream_model": upstream, "message": msg}
            body = {"messages": [{"role": "user", "content": "Reply with OK."}],
                    "temperature": 0, "max_tokens": 16}
            try:
                resp_json = await self._call_upstream_non_stream(provider, upstream, body)
            except RuntimeError as exc:
                return {"ok": False, "status": 502, "latency_ms": _elapsed(),
                        "upstream_model": upstream, "message": str(exc)[:300]}
            msg = ""
            try:
                content = (resp_json.get("choices") or [{}])[0].get("message", {}).get("content", "")
                msg = f"chat OK ({len(content)} chars)"
            except Exception:
                msg = "chat OK"
            return {"ok": True, "status": 200, "latency_ms": _elapsed(),
                    "upstream_model": upstream, "message": msg}

        if upstream_model:
            return await _try_chat(upstream_model)

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10, read=30, write=10, pool=5)) as client:
                resp = await client.get(base + "/models", headers=openai_headers or anthropic_headers)
            if resp.status_code < 400:
                result["ok"] = True
                result["status"] = resp.status_code
                result["latency_ms"] = _elapsed()
                result["message"] = f"GET /models OK ({resp.status_code})"
                return result
            models_err = f"/models {resp.status_code}: {resp.text[:200]}"
        except httpx.RequestError as exc:
            models_err = f"/models {type(exc).__name__}: {exc}"
        except Exception as exc:
            models_err = f"/models {type(exc).__name__}: {exc}"

        for r in self.store.list_routes():
            if r.get("provider_id") == provider.get("provider_id"):
                fb = await _try_chat(r["upstream_model"])
                if fb["ok"]:
                    fb["message"] = (
                        f"chat fallback OK via route '{r['alias']}' "
                        f"(upstream_model={r['upstream_model']}, "
                        f"GET /models unavailable: {models_err[:120]})"
                    )
                    fb["fallback_route"] = r["alias"]
                return fb

        result["latency_ms"] = _elapsed()
        result["message"] = f"{models_err}. Add a route under this provider to enable chat fallback."
        return result

    # -------- streaming (pure pass-through for both protocols) --------
    async def stream(
        self, req_body: dict[str, Any], api_key_id: str | None = None,
        protocol: str | None = None,
        resolved: tuple[dict[str, Any], dict[str, Any]] | None = None,
    ) -> AsyncGenerator[bytes, None]:
        if resolved is None:
            alias = req_body.get("model", "")
            resolved = self.resolve_route(alias)
        if not resolved:
            err = {
                "error": {"message": f"unknown or disabled model alias: {req_body.get('model','')}", "type": "invalid_request_error"}
            }
            yield f"data: {json.dumps(err)}\n\n".encode("utf-8")
            yield b"data: [DONE]\n\n"
            return

        route, provider = resolved
        upstream_model = route["upstream_model"]
        body = dict(req_body)
        body["model"] = upstream_model
        body["stream"] = True

        start = time.time()
        status_code = 0
        req_tokens = 0
        resp_tokens = 0
        error_msg = ""
        try:
            proto = provider.get("protocol") or "openai"
            if proto == "anthropic":
                async for chunk in self._call_upstream_anthropic_stream(provider, body):
                    yield chunk
            else:
                async for chunk in self._call_upstream_stream(provider, upstream_model, body):
                    yield chunk
        except UpstreamError as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            status_code = exc.status_code or 502
            if exc.retryable:
                self.store.record_provider_failure(provider.get("provider_id", ""),
                                                   provider.get("group_id") or "")
            err = {"error": {"message": error_msg, "type": "router_error"}}
            try:
                yield f"data: {json.dumps(err)}\n\n".encode("utf-8")
                yield b"data: [DONE]\n\n"
            except Exception:
                pass
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            err = {"error": {"message": error_msg, "type": "router_error"}}
            try:
                yield f"data: {json.dumps(err)}\n\n".encode("utf-8")
                yield b"data: [DONE]\n\n"
            except Exception:
                pass
            status_code = 502
        finally:
            latency = int((time.time() - start) * 1000)
            self._log(route["alias"], provider.get("group_id") or "",
                      provider.get("provider_id", ""), upstream_model, status_code,
                      req_tokens, resp_tokens, latency, error_msg, api_key_id)

    # -------- non-streaming --------
    async def complete(
        self, req_body: dict[str, Any], api_key_id: str | None = None,
        protocol: str | None = None,
        resolved: tuple[dict[str, Any], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if resolved is None:
            alias = req_body.get("model", "")
            resolved = self.resolve_route(alias)
        if not resolved:
            raise ValueError(f"unknown or disabled model alias: {req_body.get('model','')}")

        route, provider = resolved
        upstream_model = route["upstream_model"]
        proto = provider.get("protocol") or "openai"
        group_id = provider.get("group_id") or ""

        tool_defs = self.get_tool_definitions(group_id) if proto == "openai" else []
        if tool_defs:
            body = dict(req_body)
            body.setdefault("tools", [])
            existing_names = {self._tool_name(t) for t in body.get("tools", [])}
            for td in tool_defs:
                if self._tool_name(td) not in existing_names:
                    body["tools"].append(td)
        else:
            body = dict(req_body)

        start = time.time()
        status_code = 0
        req_tokens = 0
        resp_tokens = 0
        error_msg = ""
        try:
            for _ in range(MAX_TOOL_ITERATIONS):
                iter_start = time.time()
                body["model"] = upstream_model
                body["stream"] = False
                try:
                    if proto == "anthropic":
                        resp_json = await self._call_upstream_anthropic_non_stream(provider, body)
                        usage = resp_json.get("usage") or {}
                        self._log(
                            route["alias"], group_id, provider.get("provider_id", ""),
                            upstream_model, 200,
                            int(usage.get("input_tokens") or 0),
                            int(usage.get("output_tokens") or 0),
                            int((time.time() - iter_start) * 1000), "", api_key_id,
                        )
                        self.store.record_provider_success(provider.get("provider_id", ""), group_id)
                        return resp_json
                    resp_json = await self._call_upstream_non_stream(provider, upstream_model, body)
                except UpstreamError as exc:
                    iter_error = str(exc)
                    self._log(
                        route["alias"], group_id, provider.get("provider_id", ""),
                        upstream_model, exc.status_code or 502,
                        0, 0, int((time.time() - iter_start) * 1000), iter_error, api_key_id,
                    )
                    if exc.retryable:
                        self.store.record_provider_failure(provider.get("provider_id", ""), group_id)
                    raise
                iter_status = 200
                usage = resp_json.get("usage") or {}
                iter_req = int(usage.get("prompt_tokens") or 0)
                iter_resp = int(usage.get("completion_tokens") or 0)
                self._log(
                    route["alias"], group_id, provider.get("provider_id", ""),
                    upstream_model, iter_status,
                    iter_req, iter_resp, int((time.time() - iter_start) * 1000), "", api_key_id,
                )
                self.store.record_provider_success(provider.get("provider_id", ""), group_id)

                choice = (resp_json.get("choices") or [{}])[0]
                message = choice.get("message") or {}
                tool_calls = message.get("tool_calls") or []
                if not tool_calls:
                    return resp_json

                body.setdefault("messages", []).append(message)
                tool_providers = self.store.list_tool_providers_in_group(group_id=group_id) if group_id else {
                    p["tool_id"]: p
                    for p in self.store.list_tool_providers()
                    if p.get("enabled") and p.get("api_key_set")
                }
                for tc in tool_calls:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    args = parse_tool_arguments(fn.get("arguments"))
                    result_str = await execute_tool(name, args, tool_providers)
                    body["messages"].append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", ""),
                        "content": result_str,
                    })
            return resp_json
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}" if not error_msg else error_msg
            raise

    # -------- auto-select (failover across candidates) --------
    async def complete_auto_select(
        self, req_body: dict[str, Any], *,
        candidates: list[tuple[dict[str, Any], dict[str, Any], str]],
        api_key_id: str | None = None, protocol: str | None = None,
    ) -> dict[str, Any]:
        """Try candidates in priority order until one succeeds.

        Retryable errors (5xx, transport) trigger failover to the next
        candidate. Non-retryable errors (4xx) are raised immediately.
        Raises ``UpstreamError`` if all candidates fail.
        """
        if not candidates:
            raise ValueError(f"no candidates for model alias: {req_body.get('model','')}")
        last_exc: Exception | None = None
        for route, provider, upstream_model in candidates:
            resolved = (route, provider)
            try:
                body = dict(req_body)
                return await self.complete(
                    body, api_key_id=api_key_id, protocol=protocol, resolved=resolved,
                )
            except UpstreamError as exc:
                last_exc = exc
                if not exc.retryable:
                    raise
                continue
            except ValueError:
                raise
        raise last_exc if last_exc else UpstreamError("all candidates failed")

    async def stream_auto_select(
        self, req_body: dict[str, Any], *,
        candidates: list[tuple[dict[str, Any], dict[str, Any], str]],
        api_key_id: str | None = None, protocol: str | None = None,
    ) -> AsyncGenerator[bytes, None]:
        """Stream from the highest-priority healthy candidate.

        Streaming failover is limited: once bytes have been sent to the
        client we cannot retry on a mid-stream failure. We stream from the
        first candidate; the underlying ``stream`` method formats upstream
        errors as SSE events for the client.
        """
        if not candidates:
            err = {
                "error": {"message": f"no candidates for model alias: {req_body.get('model','')}",
                           "type": "invalid_request_error"}
            }
            yield f"data: {json.dumps(err)}\n\n".encode("utf-8")
            yield b"data: [DONE]\n\n"
            return
        route, provider, upstream_model = candidates[0]
        resolved = (route, provider)
        body = dict(req_body)
        async for chunk in self.stream(
            body, api_key_id=api_key_id, protocol=protocol, resolved=resolved,
        ):
            yield chunk

    # -------- models list --------
    def list_models(self, group_id: str | None = None) -> dict[str, Any]:
        rows = self.store.list_routes_in_group(group_id) if group_id else self.store.list_routes()
        return {
            "object": "list",
            "data": [
                {
                    "id": r["alias"],
                    "object": "model",
                    "created": int(time.time()),
                    "owned_by": r.get("provider_id", "keyway"),
                }
                for r in rows
                if r.get("enabled")
            ],
        }

    # -------- helpers --------
    @staticmethod
    def _tool_name(tool_def: dict[str, Any]) -> str:
        if tool_def.get("type") == "function":
            return (tool_def.get("function") or {}).get("name", "")
        return tool_def.get("name", "")

    def _log(
        self,
        route_alias: str,
        group_id: str,
        provider_id: str,
        upstream_model: str,
        status_code: int,
        request_tokens: int,
        response_tokens: int,
        latency_ms: int,
        error: str,
        api_key_id: str | None,
    ) -> None:
        try:
            self.store.log_request(
                group_id=group_id or "default",
                api_key_id=api_key_id,
                route_alias=route_alias,
                provider_id=provider_id or "",
                upstream_model=upstream_model,
                status_code=status_code,
                request_tokens=request_tokens,
                response_tokens=response_tokens,
                latency_ms=latency_ms,
                error=error or "",
            )
        except Exception:
            pass
