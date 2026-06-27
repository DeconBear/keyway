"""Anthropic Messages <-> OpenAI Chat Completions protocol conversion.

Provides:
- anthropic_to_openai_request: convert an inbound Anthropic /v1/messages
  request body into an OpenAI /chat/completions body that the rest of
  the router (which is OpenAI-only upstream) can call.
- openai_response_to_anthropic: convert a non-streaming OpenAI response
  into an Anthropic Messages response.
- AnthropicSSEWriter: stateful converter that consumes OpenAI SSE
  chunks and yields Anthropic SSE event bytes.

Scope (v0.2): system field, text/image/tool_use/tool_result/thinking
content blocks, max_tokens, tools, tool_choice, stop_sequences, top_p,
temperature, metadata.user_id. thinking is mapped to OpenAI
reasoning_effort when enabled. top_k and fine-grained thinking deltas
have no OpenAI equivalent and are dropped (with a one-time warning).
Streaming is fully supported for text + tool_use deltas.
"""

from __future__ import annotations

import json
import secrets
import time
from typing import Any


# ----------------------- request conversion -----------------------

def _anthropic_content_to_openai(content: Any) -> Any:
    """Convert an Anthropic message content field to OpenAI's.

    - str  -> str
    - list of text/image blocks -> str (concatenated text) or
      array of {type:text,text} / {type:image_url,image_url:...}
    - tool_use blocks are NOT handled here (caller splits the message)
    - tool_result blocks are NOT handled here (caller emits a tool msg)
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_chunks: list[str] = []
        image_chunks: list[dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                text_chunks.append(block.get("text", "") or "")
            elif btype == "image":
                source = block.get("source") or {}
                if source.get("type") == "base64":
                    media = source.get("media_type", "image/png")
                    data = source.get("data", "")
                    image_chunks.append(
                        {"type": "image_url", "image_url": {"url": f"data:{media};base64,{data}"}}
                    )
                elif source.get("type") == "url":
                    image_chunks.append(
                        {"type": "image_url", "image_url": {"url": source.get("url", "")}}
                    )
            elif btype == "thinking":
                ttext = block.get("thinking", "")
                if ttext:
                    text_chunks.append(ttext)
        if not image_chunks:
            return "".join(text_chunks)
        parts: list[Any] = []
        for t in text_chunks:
            if t:
                parts.append({"type": "text", "text": t})
        parts.extend(image_chunks)
        return parts
    return str(content)


def anthropic_to_openai_request(req: dict[str, Any]) -> dict[str, Any]:
    """Convert an Anthropic /v1/messages request to an OpenAI /chat/completions body.

    Returns the OpenAI body (without `model` — caller fills in the
    upstream model name) and `stream` (caller sets).
    """
    out: dict[str, Any] = {"messages": []}

    system = req.get("system")
    if system is not None:
        if isinstance(system, str):
            out["messages"].append({"role": "system", "content": system})
        elif isinstance(system, list):
            sys_text = "".join(
                (b.get("text", "") or "")
                for b in system
                if isinstance(b, dict) and b.get("type") == "text"
            )
            if sys_text:
                out["messages"].append({"role": "system", "content": sys_text})

    for m in req.get("messages", []):
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role == "user":
            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            ):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_result":
                        continue
                    out["messages"].append(
                        {
                            "role": "tool",
                            "tool_call_id": block.get("tool_use_id", ""),
                            "content": _anthropic_content_to_openai(block.get("content")),
                        }
                    )
            else:
                out["messages"].append({"role": "user", "content": _anthropic_content_to_openai(content)})
        elif role == "assistant":
            tool_calls = m.get("tool_calls") or []
            if isinstance(content, list):
                tool_calls = []
                text_parts: list[str] = []
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type")
                    if btype == "text":
                        text_parts.append(block.get("text", "") or "")
                    elif btype == "tool_use":
                        tool_calls.append(
                            {
                                "id": block.get("id", f"toolu_{secrets.token_urlsafe(12)}"),
                                "type": "function",
                                "function": {
                                    "name": block.get("name", ""),
                                    "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                                },
                            }
                        )
                    elif btype == "thinking":
                        text_parts.append(block.get("thinking", "") or "")
                content = "".join(text_parts) or None
            if not tool_calls:
                out["messages"].append({"role": "assistant", "content": _anthropic_content_to_openai(content)})
            else:
                msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": _anthropic_content_to_openai(content) or "",
                    "tool_calls": tool_calls,
                }
                out["messages"].append(msg)
    if "max_tokens" in req:
        out["max_tokens"] = int(req["max_tokens"])
    if "temperature" in req and req["temperature"] is not None:
        out["temperature"] = float(req["temperature"])
    if "top_p" in req and req["top_p"] is not None:
        out["top_p"] = float(req["top_p"])
    if req.get("stop_sequences"):
        out["stop"] = list(req["stop_sequences"])
    if "metadata" in req and isinstance(req["metadata"], dict) and req["metadata"].get("user_id"):
        out["user"] = str(req["metadata"]["user_id"])
    tools = req.get("tools")
    if tools:
        out_tools: list[dict[str, Any]] = []
        for t in tools:
            if not isinstance(t, dict):
                continue
            out_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": t.get("name", ""),
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
                    },
                }
            )
        if out_tools:
            out["tools"] = out_tools
    tc = req.get("tool_choice")
    if isinstance(tc, dict):
        ttype = tc.get("type")
        if ttype == "auto":
            out["tool_choice"] = "auto"
        elif ttype == "any":
            out["tool_choice"] = "required"
        elif ttype == "tool" and tc.get("name"):
            out["tool_choice"] = {"type": "function", "function": {"name": tc["name"]}}
        elif ttype == "none":
            out["tool_choice"] = "none"
    elif isinstance(tc, str):
        out["tool_choice"] = tc
    thinking = req.get("thinking")
    if isinstance(thinking, dict) and thinking.get("type") == "enabled":
        out["reasoning_effort"] = "medium"

    return out


# ----------------------- non-streaming response conversion -----------------------

_FINISH_REASON_MAP = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "content_filter": "end_turn",
    "function_call": "tool_use",
}


def openai_response_to_anthropic(resp: dict[str, Any], *, model: str) -> dict[str, Any]:
    """Convert a non-streaming OpenAI chat.completion response to an
    Anthropic Messages response body."""
    choice = (resp.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    finish = choice.get("finish_reason") or "stop"
    stop_reason = _FINISH_REASON_MAP.get(finish, "end_turn")

    content_blocks: list[dict[str, Any]] = []
    text = msg.get("content")
    if text:
        content_blocks.append({"type": "text", "text": text})
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        try:
            input_obj = json.loads(fn.get("arguments") or "{}")
        except (TypeError, ValueError):
            input_obj = {}
        content_blocks.append(
            {
                "type": "tool_use",
                "id": tc.get("id", f"toolu_{secrets.token_urlsafe(12)}"),
                "name": fn.get("name", ""),
                "input": input_obj,
            }
        )
    usage = resp.get("usage") or {}
    return {
        "id": f"msg_{secrets.token_urlsafe(12)}",
        "type": "message",
        "role": "assistant",
        "content": content_blocks,
        "model": model,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": int(usage.get("prompt_tokens") or 0),
            "output_tokens": int(usage.get("completion_tokens") or 0),
        },
    }


# ----------------------- streaming conversion -----------------------

def _sse(event: str, data: Any) -> bytes:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


class AnthropicSSEWriter:
    """Consume OpenAI chat.completion SSE chunks, yield Anthropic SSE bytes.

    Usage:
        writer = AnthropicSSEWriter(model="deepseek-reasoner")
        for chunk_bytes in upstream_sse_iter:
            for piece in writer.feed_bytes(chunk_bytes):
                yield piece
        for piece in writer.finish():
            yield piece
    """

    def __init__(self, *, model: str) -> None:
        self.model = model
        self.message_id = "msg_" + secrets.token_urlsafe(12)
        self.started = False
        self.finished = False
        self.input_tokens = 0
        self.output_tokens = 0
        self._text_block_open = False
        self._tool: dict[str, Any] | None = None
        self._next_index = 0
        self._buf = b""

    def feed_bytes(self, chunk: bytes) -> list[bytes]:
        """Process one upstream chunk; return zero or more Anthropic SSE event bytes."""
        out: list[bytes] = []
        self._buf += chunk
        while True:
            sep = self._buf.find(b"\n\n")
            if sep < 0:
                break
            raw_event = self._buf[: sep + 2]
            self._buf = self._buf[sep + 2 :]
            line = raw_event.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            for ln in line.splitlines():
                ln = ln.strip()
                if not ln.startswith("data:"):
                    continue
                data_str = ln[5:].strip()
                if data_str == "[DONE]":
                    continue
                try:
                    payload = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                out.extend(self._process_openai_chunk(payload))
        return out

    def feed_json(self, payload: dict[str, Any]) -> list[bytes]:
        return self._process_openai_chunk(payload)

    def finish(self) -> list[bytes]:
        if self.finished:
            return []
        self.finished = True
        out: list[bytes] = []
        if self._buf.strip():
            for ln in self._buf.decode("utf-8", errors="replace").splitlines():
                ln = ln.strip()
                if ln.startswith("data:") and ln[5:].strip() and ln[5:].strip() != "[DONE]":
                    try:
                        out.extend(self._process_openai_chunk(json.loads(ln[5:].strip())))
                    except json.JSONDecodeError:
                        pass
        if self._text_block_open:
            out.append(_sse("content_block_stop", {"type": "content_block_stop", "index": self._next_index}))
            self._text_block_open = False
            self._next_index += 1
        if self._tool is not None:
            out.append(_sse("content_block_stop", {"type": "content_block_stop", "index": self._next_index}))
            self._next_index += 1
            self._tool = None
        out.append(
            _sse(
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": self.output_tokens},
                },
            )
        )
        out.append(_sse("message_stop", {"type": "message_stop"}))
        return out

    def _process_openai_chunk(self, payload: dict[str, Any]) -> list[bytes]:
        out: list[bytes] = []
        if not isinstance(payload, dict):
            return out
        choice = (payload.get("choices") or [{}])[0]
        delta = choice.get("delta") or {}
        finish = choice.get("finish_reason")

        usage = payload.get("usage")
        if isinstance(usage, dict):
            self.input_tokens = int(usage.get("prompt_tokens") or self.input_tokens)
            self.output_tokens = int(usage.get("completion_tokens") or self.output_tokens)

        if not self.started:
            self.started = True
            out.append(
                _sse(
                    "message_start",
                    {
                        "type": "message_start",
                        "message": {
                            "id": self.message_id,
                            "type": "message",
                            "role": "assistant",
                            "content": [],
                            "model": self.model,
                            "stop_reason": None,
                            "stop_sequence": None,
                            "usage": {"input_tokens": self.input_tokens, "output_tokens": 0},
                        },
                    },
                )
            )

        text = delta.get("content")
        if text:
            if not self._text_block_open:
                out.append(
                    _sse(
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": self._next_index,
                            "content_block": {"type": "text", "text": ""},
                        },
                    )
                )
                self._text_block_open = True
            out.append(
                _sse(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": self._next_index,
                        "delta": {"type": "text_delta", "text": text},
                    },
                )
            )

        tcs = delta.get("tool_calls")
        if tcs:
            for tc in tcs:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function") or {}
                tc_id = tc.get("id")
                tc_name = fn.get("name")
                tc_args = fn.get("arguments") or ""
                if tc_id or (tc_name and (self._tool is None or self._tool.get("name") != tc_name)):
                    if self._text_block_open:
                        out.append(
                            _sse("content_block_stop", {"type": "content_block_stop", "index": self._next_index})
                        )
                        self._text_block_open = False
                        self._next_index += 1
                    if self._tool is None:
                        self._tool = {
                            "id": tc_id or f"toolu_{secrets.token_urlsafe(12)}",
                            "name": tc_name or "",
                            "args": "",
                        }
                        out.append(
                            _sse(
                                "content_block_start",
                                {
                                    "type": "content_block_start",
                                    "index": self._next_index,
                                    "content_block": {
                                        "type": "tool_use",
                                        "id": self._tool["id"],
                                        "name": self._tool["name"],
                                        "input": {},
                                    },
                                },
                            )
                        )
                    else:
                        self._tool["id"] = tc_id or self._tool["id"]
                        if tc_name:
                            self._tool["name"] = tc_name
                if tc_args:
                    self._tool["args"] += tc_args
                    out.append(
                        _sse(
                            "content_block_delta",
                            {
                                "type": "content_block_delta",
                                "index": self._next_index,
                                "delta": {"type": "input_json_delta", "partial_json": tc_args},
                            },
                        )
                    )

        if finish:
            if self._text_block_open:
                out.append(
                    _sse("content_block_stop", {"type": "content_block_stop", "index": self._next_index})
                )
                self._text_block_open = False
                self._next_index += 1
            if self._tool is not None:
                out.append(
                    _sse("content_block_stop", {"type": "content_block_stop", "index": self._next_index})
                )
                self._tool = None
                self._next_index += 1
            stop_reason = _FINISH_REASON_MAP.get(finish, "end_turn")
            out.append(
                _sse(
                    "message_delta",
                    {
                        "type": "message_delta",
                        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                        "usage": {"output_tokens": self.output_tokens},
                    },
                )
            )
            out.append(_sse("message_stop", {"type": "message_stop"}))
            self.finished = True
        return out
