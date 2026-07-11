"""Modality detection for adapter mode.

Detects whether a request body contains multimodal content (images,
tool results) so the adapter pipeline can pre-process it before
forwarding to a text-only model.
"""

from __future__ import annotations

from typing import Any


class ModalityDetector:
    """Inspect a request body and report the set of modalities present.

    Possible values in the returned set: ``"text"``, ``"image"``,
    ``"tool_result"``.
    """

    @staticmethod
    def detect(req_body: dict[str, Any]) -> set[str]:
        modalities: set[str] = {"text"}
        for msg in req_body.get("messages", []) or []:
            if not isinstance(msg, dict):
                continue
            # OpenAI tool-result messages
            if msg.get("role") == "tool":
                modalities.add("tool_result")
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        btype = block.get("type", "")
                        if btype in ("image", "image_url"):
                            modalities.add("image")
                        elif btype == "tool_result":
                            modalities.add("tool_result")
        return modalities

    @staticmethod
    def has_image(req_body: dict[str, Any]) -> bool:
        return "image" in ModalityDetector.detect(req_body)

    @staticmethod
    def has_tool_result(req_body: dict[str, Any]) -> bool:
        return "tool_result" in ModalityDetector.detect(req_body)

    @staticmethod
    def needs_adaptation(req_body: dict[str, Any]) -> bool:
        mods = ModalityDetector.detect(req_body)
        return "image" in mods or "tool_result" in mods
