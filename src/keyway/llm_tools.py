"""Built-in tool providers exposed to LLMs via the router.

Tools are looked up by name. When the upstream LLM emits a `tool_calls`
(OpenAI format), the router intercepts, looks up the tool, dispatches
to the registered tool provider's external API, and injects the
result back as a `role: tool` message before the next LLM iteration.

Currently ships with `tavily_search` only; more tools can be added by
registering an `llm_tool_providers` row and listing the corresponding
OpenAI-format tool schema in BUILTIN_TOOLS.
"""

from __future__ import annotations

import json
from typing import Any

import httpx


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


BUILTIN_TOOLS: dict[str, dict[str, Any]] = {
    "tavily_search": TAVILY_SEARCH_TOOL,
}


async def _tavily_search(query: str, api_key: str, max_results: int = 5) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
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


def parse_tool_arguments(arguments: Any) -> dict[str, Any]:
    if isinstance(arguments, dict):
        return arguments
    if not isinstance(arguments, str):
        return {}
    try:
        return json.loads(arguments)
    except (TypeError, ValueError):
        return {}


async def execute_tool(tool_name: str, arguments: dict[str, Any], tool_providers: dict[str, dict[str, Any]]) -> str:
    """Run a tool by name with parsed arguments. Returns a JSON-serialized result string."""
    if tool_name == "tavily_search":
        provider = tool_providers.get("tavily") or {}
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
    return json.dumps({"error": f"unknown tool: {tool_name}"}, ensure_ascii=False)
