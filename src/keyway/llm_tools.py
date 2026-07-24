"""Built-in tool providers exposed to LLMs via the router.

Tools are looked up by OpenAI function name. When the upstream LLM emits
``tool_calls``, the router intercepts, dispatches to the registered
handler, and injects the result as a ``role: tool`` message.

Keyed tools (e.g. Tavily) require an ``llm_tool_providers`` row with an
API key. Keyless tools (datetime, http_fetch) are always injectable.

Custom tools can be registered at runtime via ``register_builtin_tool``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx

ToolHandler = Callable[[dict[str, Any], dict[str, Any]], Awaitable[str]]


TAVILY_SEARCH_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "tavily_search",
        "description": (
            "Search the web for current information using Tavily. "
            "Returns a list of relevant results with title, url, and content snippets."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {
                    "type": "integer",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20,
                },
            },
            "required": ["query"],
        },
    },
}

DATETIME_NOW_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "datetime_now",
        "description": (
            "Return the current UTC date and time in ISO-8601 format. "
            "Use when the user asks what time or date it is."
        ),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

HTTP_FETCH_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "http_fetch",
        "description": (
            "Fetch a public HTTP(S) URL and return truncated text content. "
            "Use for reading documentation pages or simple APIs. "
            "Does not follow authentication; max 50KB of text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Absolute http(s) URL to fetch"},
                "max_chars": {
                    "type": "integer",
                    "default": 4000,
                    "minimum": 200,
                    "maximum": 20000,
                },
            },
            "required": ["url"],
        },
    },
}


async def _tavily_search(query: str, api_key: str, max_results: int = 5) -> dict[str, Any]:
    async with httpx.AsyncClient(trust_env=False, timeout=30) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def _handle_tavily(arguments: dict[str, Any], provider: dict[str, Any]) -> str:
    api_key = provider.get("api_key")
    if not api_key:
        return json.dumps({"error": "tavily provider not configured"}, ensure_ascii=False)
    try:
        result = await _tavily_search(
            query=arguments.get("query", ""),
            api_key=api_key,
            max_results=int(arguments.get("max_results", 5) or 5),
        )
    except Exception as exc:
        return json.dumps({"error": f"tavily search failed: {exc}"}, ensure_ascii=False)
    results = (result.get("results") or [])[: int(arguments.get("max_results", 5) or 5)]
    simplified = [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": (r.get("content") or "")[:500],
        }
        for r in results
    ]
    return json.dumps(
        {"results": simplified, "answer": result.get("answer", "")},
        ensure_ascii=False,
    )


async def _handle_datetime_now(arguments: dict[str, Any], provider: dict[str, Any]) -> str:
    now = datetime.now(timezone.utc).isoformat()
    return json.dumps({"utc_now": now}, ensure_ascii=False)


async def _handle_http_fetch(arguments: dict[str, Any], provider: dict[str, Any]) -> str:
    url = str(arguments.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return json.dumps({"error": "url must start with http:// or https://"}, ensure_ascii=False)
    try:
        max_chars = int(arguments.get("max_chars", 4000) or 4000)
    except (TypeError, ValueError):
        return json.dumps(
            {"error": f"max_chars must be an integer, got {arguments.get('max_chars')!r}"},
            ensure_ascii=False,
        )
    max_chars = max(200, min(20000, max_chars))
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=20, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Keyway-http_fetch/0.1"})
        text = resp.text[: max_chars + 1]
        truncated = len(text) > max_chars
        return json.dumps(
            {
                "status_code": resp.status_code,
                "url": str(resp.url),
                "truncated": truncated,
                "content": text[:max_chars],
            },
            ensure_ascii=False,
        )
    except Exception as exc:
        return json.dumps({"error": f"http_fetch failed: {exc}"}, ensure_ascii=False)


# tool_id -> metadata
# requires_key: needs an enabled llm_tool_providers row with api_key
# function_name: OpenAI tool function name (may differ from tool_id)
_BUILTIN_REGISTRY: dict[str, dict[str, Any]] = {
    "tavily": {
        "schema": TAVILY_SEARCH_TOOL,
        "function_name": "tavily_search",
        "requires_key": True,
        "handler": _handle_tavily,
    },
    "datetime_now": {
        "schema": DATETIME_NOW_TOOL,
        "function_name": "datetime_now",
        "requires_key": False,
        "handler": _handle_datetime_now,
    },
    "http_fetch": {
        "schema": HTTP_FETCH_TOOL,
        "function_name": "http_fetch",
        "requires_key": False,
        "handler": _handle_http_fetch,
    },
}

# Back-compat: tool_id -> OpenAI schema
BUILTIN_TOOLS: dict[str, dict[str, Any]] = {
    tid: meta["schema"] for tid, meta in _BUILTIN_REGISTRY.items()
}

# function_name -> tool_id
_FUNCTION_TO_TOOL_ID: dict[str, str] = {
    meta["function_name"]: tid for tid, meta in _BUILTIN_REGISTRY.items()
}


def register_builtin_tool(
    tool_id: str,
    schema: dict[str, Any],
    handler: ToolHandler,
    *,
    requires_key: bool = False,
    function_name: str | None = None,
) -> None:
    """Register or replace a builtin tool (runtime extension point)."""
    if not tool_id:
        raise ValueError("tool_id required")
    fname = function_name or (schema.get("function") or {}).get("name") or tool_id
    # drop old function mapping if replacing
    old = _BUILTIN_REGISTRY.get(tool_id)
    if old:
        _FUNCTION_TO_TOOL_ID.pop(old.get("function_name", ""), None)
    _BUILTIN_REGISTRY[tool_id] = {
        "schema": schema,
        "function_name": fname,
        "requires_key": requires_key,
        "handler": handler,
    }
    BUILTIN_TOOLS[tool_id] = schema
    _FUNCTION_TO_TOOL_ID[fname] = tool_id


def list_builtin_tool_ids() -> list[str]:
    return sorted(_BUILTIN_REGISTRY.keys())


def tool_requires_key(tool_id: str) -> bool:
    meta = _BUILTIN_REGISTRY.get(tool_id) or {}
    return bool(meta.get("requires_key"))


def schemas_for_enabled(
    enabled_keyed_ids: set[str],
    *,
    include_keyless: bool = True,
) -> list[dict[str, Any]]:
    """Return OpenAI tool schemas for keyless builtins + enabled keyed ones."""
    out: list[dict[str, Any]] = []
    for tid, meta in _BUILTIN_REGISTRY.items():
        if meta.get("requires_key"):
            if tid in enabled_keyed_ids:
                out.append(meta["schema"])
        elif include_keyless:
            out.append(meta["schema"])
    return out


def parse_tool_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if not isinstance(arguments, str):
        return {}
    try:
        return json.loads(arguments)
    except (TypeError, ValueError):
        return {}


async def execute_tool(
    tool_name: str,
    arguments: dict[str, Any],
    tool_providers: dict[str, dict[str, Any]],
) -> str:
    """Run a tool by OpenAI function name. Returns a JSON-serialized result string."""
    tool_id = _FUNCTION_TO_TOOL_ID.get(tool_name, tool_name)
    meta = _BUILTIN_REGISTRY.get(tool_id)
    if not meta:
        return json.dumps({"error": f"unknown tool: {tool_name}"}, ensure_ascii=False)
    provider = tool_providers.get(tool_id) or {}
    handler: ToolHandler = meta["handler"]
    return await handler(arguments, provider)
