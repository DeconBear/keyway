"""Adapter pipeline for multimodal-to-text pre-processing.

When a route is in ``adapter`` mode, the pipeline detects image / tool
content in the request, optionally calls a vision model for images, and
flattens tool results to text before forwarding to a text-only model.
"""

from __future__ import annotations

import json
from typing import Any

from .llm_router import LLMRouter, UpstreamError
from .modality import ModalityDetector


class ImageDescriber:
    """Calls a vision-capable model route to describe an image, then
    replaces the image block with a text block containing the description.
    """

    def __init__(self, router: LLMRouter, vision_alias: str) -> None:
        self.router = router
        self.vision_alias = vision_alias

    async def adapt(self, req_body: dict[str, Any], group_id: str = "") -> dict[str, Any]:
        """Transform request body: replace image blocks with text descriptions.

        Works for both OpenAI-style (``image_url``) and Anthropic-style
        (``image`` with ``source``) content blocks.
        """
        for msg in req_body.get("messages", []) or []:
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            new_blocks: list[dict[str, Any]] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") in ("image", "image_url"):
                    description = await self._describe_image(block, group_id)
                    new_blocks.append({
                        "type": "text",
                        "text": f"[Image: {description}]",
                    })
                else:
                    new_blocks.append(block)
            msg["content"] = new_blocks
        return req_body

    async def _describe_image(self, image_block: dict[str, Any], group_id: str) -> str:
        """Call a vision model route to describe the image.

        Builds a minimal chat request containing the image and a prompt
        asking the vision model to describe it, then extracts the text
        from the response.
        """
        vision_req = self._build_vision_request(image_block, self.vision_alias)
        resolved = self.router.resolve_route(
            self.vision_alias, group_id=group_id, required_protocol="openai",
        )
        if not resolved:
            raise UpstreamError(
                f"vision alias '{self.vision_alias}' not found or not openai "
                f"in group '{group_id or 'default'}'"
            )
        try:
            resp = await self.router.complete(
                vision_req, protocol="openai", resolved=resolved,
            )
        except UpstreamError:
            raise
        except Exception as exc:
            raise UpstreamError(f"vision describe failed: {exc}") from exc
        return self._extract_text(resp)

    @staticmethod
    def _build_vision_request(image_block: dict[str, Any], vision_alias: str) -> dict[str, Any]:
        """Build a chat-completions request that asks the vision model
        to describe the given image block."""
        # Normalize the image block into an OpenAI-style image_url block.
        if image_block.get("type") == "image_url":
            url = (image_block.get("image_url") or {}).get("url", "")
            image_content: dict[str, Any] = {
                "type": "image_url",
                "image_url": {"url": url},
            }
        elif image_block.get("type") == "image":
            # Anthropic-style: {"type": "image", "source": {"type": "base64", ...}}
            image_content = {"type": "image", "source": image_block.get("source", {})}
            # Convert to OpenAI-style for the vision call (which goes through
            # the OpenAI-protocol path). If it's a base64 source, build a
            # data URI; if it's a URL source, pass through.
            source = image_block.get("source") or {}
            if source.get("type") == "base64":
                media_type = source.get("media_type", "image/png")
                data = source.get("data", "")
                image_content = {
                    "type": "image_url",
                    "image_url": {"url": f"data:{media_type};base64,{data}"},
                }
            elif source.get("type") == "url":
                image_content = {
                    "type": "image_url",
                    "image_url": {"url": source.get("url", "")},
                }
        else:
            image_content = image_block

        return {
            "model": vision_alias,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        image_content,
                        {"type": "text", "text": "Describe this image concisely."},
                    ],
                }
            ],
            "max_tokens": 300,
        }

    @staticmethod
    def _extract_text(resp: dict[str, Any]) -> str:
        """Extract text from a chat completion response."""
        # OpenAI format
        choices = resp.get("choices") or []
        if choices:
            content = (choices[0].get("message") or {}).get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                return " ".join(parts) if parts else str(content)
        # Anthropic format
        content_blocks = resp.get("content") or []
        if content_blocks:
            parts = []
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            return " ".join(parts) if parts else ""
        return ""


class ToolResultFlattener:
    """Flatten tool-result messages/blocks into plain text for text-only models.

    - OpenAI: ``role: tool`` messages → ``role: user`` with ``[Tool result: …]``
    - Anthropic: ``type: tool_result`` content blocks → ``type: text`` blocks
    """

    @staticmethod
    def adapt(req_body: dict[str, Any]) -> dict[str, Any]:
        messages = req_body.get("messages") or []
        if not messages:
            return req_body

        new_messages: list[dict[str, Any]] = []
        for msg in messages:
            if not isinstance(msg, dict):
                new_messages.append(msg)
                continue

            if msg.get("role") == "tool":
                text = ToolResultFlattener._openai_tool_text(msg)
                new_messages.append({"role": "user", "content": text})
                continue

            # OpenAI: an assistant message carrying tool_calls must have the
            # calls flattened as well — once role:tool messages become user
            # messages, a bare tool_calls field is an orphan that upstreams
            # reject with a 400.
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                calls_text = ToolResultFlattener._openai_tool_calls_text(msg["tool_calls"])
                msg = {k: v for k, v in msg.items() if k != "tool_calls"}
                content = msg.get("content")
                if isinstance(content, str) and content.strip():
                    msg["content"] = content + "\n" + calls_text
                elif isinstance(content, list):
                    # Multipart assistant content (text blocks + tool_calls) —
                    # preserve text parts; do not drop them for call text alone.
                    parts: list[str] = []
                    for block in content:
                        if isinstance(block, str) and block.strip():
                            parts.append(block)
                        elif isinstance(block, dict):
                            text = block.get("text")
                            if isinstance(text, str) and text.strip():
                                parts.append(text)
                    prefix = "\n".join(parts)
                    msg["content"] = f"{prefix}\n{calls_text}" if prefix else calls_text
                else:
                    msg["content"] = calls_text
                new_messages.append(msg)
                continue

            content = msg.get("content")
            if isinstance(content, list):
                new_blocks: list[dict[str, Any]] = []
                changed = False
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        new_blocks.append({
                            "type": "text",
                            "text": ToolResultFlattener._anthropic_tool_text(block),
                        })
                        changed = True
                    elif isinstance(block, dict) and block.get("type") == "tool_use":
                        # Anthropic: tool_use without a matching tool_result
                        # (flattened above) is likewise an orphan -> 400.
                        new_blocks.append({
                            "type": "text",
                            "text": ToolResultFlattener._anthropic_tool_use_text(block),
                        })
                        changed = True
                    else:
                        new_blocks.append(block)
                if changed:
                    msg = {**msg, "content": new_blocks}
            new_messages.append(msg)

        out = dict(req_body)
        out["messages"] = new_messages
        return out

    @staticmethod
    def _openai_tool_text(msg: dict[str, Any]) -> str:
        tool_call_id = msg.get("tool_call_id") or msg.get("name") or ""
        content = msg.get("content", "")
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif isinstance(block, str):
                    parts.append(block)
            content = " ".join(parts)
        elif not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        prefix = f"tool_call_id={tool_call_id}" if tool_call_id else "tool"
        return f"[Tool result ({prefix}): {content}]"

    @staticmethod
    def _openai_tool_calls_text(tool_calls: list[Any]) -> str:
        parts: list[str] = []
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            fn = tc.get("function") or {}
            name = fn.get("name", "")
            args = fn.get("arguments", "")
            if not isinstance(args, str):
                args = json.dumps(args, ensure_ascii=False)
            parts.append(f"[Tool call: {name}({args})]")
        return "\n".join(parts)

    @staticmethod
    def _anthropic_tool_use_text(block: dict[str, Any]) -> str:
        name = block.get("name", "")
        inp = block.get("input", {})
        try:
            args = json.dumps(inp, ensure_ascii=False)
        except Exception:
            args = str(inp)
        return f"[Tool call: {name}({args})]"

    @staticmethod
    def _anthropic_tool_text(block: dict[str, Any]) -> str:
        tool_use_id = block.get("tool_use_id") or ""
        content = block.get("content", "")
        if isinstance(content, list):
            parts = []
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text":
                    parts.append(b.get("text", ""))
                elif isinstance(b, str):
                    parts.append(b)
            content = " ".join(parts)
        elif not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        prefix = f"tool_use_id={tool_use_id}" if tool_use_id else "tool"
        return f"[Tool result ({prefix}): {content}]"


class AdapterPipeline:
    """Orchestrates modality detection and pre-processing adapters.

    Config (JSON stored in ``model_routes.adapter_config``):

    - ``vision_alias``: route alias pointing to a vision-capable model.
      Required for image adaptation.
    - ``fallback``: what to do if the vision model fails. ``"skip-image"``
      replaces the image with a placeholder text; ``"error"`` (default)
      propagates the error to the client.
    """

    def __init__(self, router: LLMRouter, config: dict[str, Any] | str | None = None) -> None:
        self.router = router
        if isinstance(config, str):
            try:
                config = json.loads(config) if config else {}
            except (json.JSONDecodeError, TypeError):
                config = {}
        self.config: dict[str, Any] = config or {}

    async def adapt(self, req_body: dict[str, Any], group_id: str = "") -> dict[str, Any]:
        """Detect modalities and apply the appropriate adapters.

        Flattens tool results always. Adapts images when a vision_alias
        is configured (or strips them on skip-image fallback).
        """
        modalities = ModalityDetector.detect(req_body)

        if "tool_result" in modalities:
            req_body = ToolResultFlattener.adapt(req_body)

        if "image" not in modalities:
            return req_body

        vision_alias = self.config.get("vision_alias", "")
        if not vision_alias:
            fallback = self.config.get("fallback", "error")
            if fallback == "skip-image":
                return self._strip_images(req_body)
            return req_body

        describer = ImageDescriber(self.router, vision_alias)
        try:
            return await describer.adapt(req_body, group_id=group_id)
        except Exception:
            fallback = self.config.get("fallback", "error")
            if fallback == "skip-image":
                return self._strip_images(req_body)
            raise

    @staticmethod
    def _strip_images(req_body: dict[str, Any]) -> dict[str, Any]:
        """Replace image blocks with a placeholder text block."""
        for msg in req_body.get("messages", []) or []:
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            new_blocks: list[dict[str, Any]] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") in ("image", "image_url"):
                    new_blocks.append({
                        "type": "text",
                        "text": "[Image: <unavailable>]",
                    })
                else:
                    new_blocks.append(block)
            msg["content"] = new_blocks
        return req_body
