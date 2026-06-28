"""Fusion mode: parallel multi-provider dispatch with judge synthesis.

When a route is in ``fusion`` mode, the orchestrator dispatches the
request to all candidate providers in parallel, collects the responses,
and sends them to a judge model that synthesizes a final answer using
one of several strategies.

Fusion does not support streaming — the client waits for all candidates
and the judge to complete. Each fusion request logs N+1 entries to
``llm_request_logs`` grouped by a shared ``fusion_id``.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from .llm_router import LLMRouter, UpstreamError


class FusionOrchestrator:
    """Dispatch to multiple providers in parallel, then judge and synthesize."""

    def __init__(self, router: LLMRouter) -> None:
        self.router = router

    async def fuse(
        self, req_body: dict[str, Any],
        candidates: list[tuple[dict[str, Any], dict[str, Any], str]],
        *, judge_alias: str, strategy: str = "compare_and_synthesize",
        group_id: str = "", api_key_id: str | None = None,
        min_candidates: int = 2, timeout_seconds: int = 30,
    ) -> dict[str, Any]:
        """Dispatch to all candidates in parallel, judge, return synthesized response.

        Returns a dict with ``result`` (the judge's response) and
        ``members`` (list of provider_ids that participated).
        Raises ``UpstreamError`` if too few candidates succeed.
        """
        fusion_id = uuid.uuid4().hex

        if len(candidates) < min_candidates:
            raise UpstreamError(
                f"fusion requires at least {min_candidates} candidates, got {len(candidates)}"
            )

        # 1. Parallel dispatch
        tasks = [
            self._call_candidate(req_body, route, provider, upstream_model,
                                 group_id, api_key_id, fusion_id, timeout_seconds)
            for route, provider, upstream_model in candidates
        ]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # 2. Filter out failures
        valid: list[tuple[str, str, dict[str, Any]]] = []  # (provider_id, upstream_model, response)
        members: list[str] = []
        for (route, provider, upstream_model), resp in zip(candidates, responses):
            if isinstance(resp, Exception):
                continue
            pid = provider.get("provider_id", "")
            valid.append((pid, upstream_model, resp))
            members.append(pid)

        if not valid:
            raise UpstreamError("all fusion candidates failed")

        # 3. Judge
        judge_fn = {
            "compare_and_synthesize": self._compare_and_synthesize,
            "majority_vote": self._majority_vote,
            "ranked": self._ranked,
        }.get(strategy, self._compare_and_synthesize)

        result = await judge_fn(req_body, valid, judge_alias, group_id, api_key_id, fusion_id)
        return {"result": result, "members": members, "fusion_id": fusion_id}

    async def _call_candidate(
        self, req_body: dict[str, Any], route: dict[str, Any],
        provider: dict[str, Any], upstream_model: str,
        group_id: str, api_key_id: str | None, fusion_id: str,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        """Call a single candidate provider. Records success/failure to health."""
        resolved = (route, provider)
        body = dict(req_body)
        try:
            result = await asyncio.wait_for(
                self.router.complete(body, api_key_id=api_key_id, protocol="openai",
                                     resolved=resolved),
                timeout=timeout_seconds,
            )
            return result
        except Exception as exc:
            # Health recording is handled by router.complete's internal error path
            raise

    # ---- judge strategies ----

    async def _compare_and_synthesize(
        self, req_body: dict[str, Any],
        valid: list[tuple[str, str, dict[str, Any]]],
        judge_alias: str, group_id: str,
        api_key_id: str | None, fusion_id: str,
    ) -> dict[str, Any]:
        """Judge picks the best parts from each response and synthesizes."""
        prompt = self._build_judge_prompt(
            req_body, valid,
            instruction=(
                "You are a judge. Below are candidate answers from multiple models "
                "to the same question. Synthesize the best possible answer by picking "
                "the best parts from each candidate. Return only your synthesized answer."
            ),
        )
        return await self._call_judge(prompt, judge_alias, group_id, api_key_id, fusion_id, valid)

    async def _majority_vote(
        self, req_body: dict[str, Any],
        valid: list[tuple[str, str, dict[str, Any]]],
        judge_alias: str, group_id: str,
        api_key_id: str | None, fusion_id: str,
    ) -> dict[str, Any]:
        """Judge picks the most common answer (good for factual Q&A)."""
        prompt = self._build_judge_prompt(
            req_body, valid,
            instruction=(
                "You are a judge. Below are candidate answers from multiple models "
                "to the same question. Identify the most common or consensus answer. "
                "If there is a clear majority, return that answer. Otherwise, return "
                "the best answer. Return only your final answer."
            ),
        )
        return await self._call_judge(prompt, judge_alias, group_id, api_key_id, fusion_id, valid)

    async def _ranked(
        self, req_body: dict[str, Any],
        valid: list[tuple[str, str, dict[str, Any]]],
        judge_alias: str, group_id: str,
        api_key_id: str | None, fusion_id: str,
    ) -> dict[str, Any]:
        """Judge ranks all responses and returns the top one."""
        prompt = self._build_judge_prompt(
            req_body, valid,
            instruction=(
                "You are a judge. Below are candidate answers from multiple models "
                "to the same question. Rank them from best to worst, then return only "
                "the best answer verbatim."
            ),
        )
        return await self._call_judge(prompt, judge_alias, group_id, api_key_id, fusion_id, valid)

    # ---- helpers ----

    @staticmethod
    def _build_judge_prompt(
        req_body: dict[str, Any],
        valid: list[tuple[str, str, dict[str, Any]]],
        instruction: str,
    ) -> dict[str, Any]:
        """Build the judge request body."""
        original_question = ""
        for msg in (req_body.get("messages") or [])[::-1]:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    original_question = content
                    break
                if isinstance(content, list):
                    parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                    original_question = " ".join(parts)
                    break

        candidate_texts: list[str] = []
        for i, (pid, model, resp) in enumerate(valid, 1):
            text = FusionOrchestrator._extract_response_text(resp)
            candidate_texts.append(f"--- Candidate {i} (provider: {pid}, model: {model}) ---\n{text}")

        judge_content = (
            f"{instruction}\n\n"
            f"Original question:\n{original_question}\n\n"
            f"\n".join(candidate_texts)
        )

        return {
            "model": "",  # filled by judge alias resolution
            "messages": [{"role": "user", "content": judge_content}],
            "max_tokens": 1024,
            "temperature": 0,
        }

    async def _call_judge(
        self, prompt_body: dict[str, Any], judge_alias: str,
        group_id: str, api_key_id: str | None, fusion_id: str,
        valid: list[tuple[str, str, dict[str, Any]]],
    ) -> dict[str, Any]:
        """Call the judge model and return its response."""
        prompt_body["model"] = judge_alias
        start = time.time()
        try:
            result = await self.router.complete(prompt_body, api_key_id=api_key_id, protocol="openai")
            latency = int((time.time() - start) * 1000)
            self.router._log(
                judge_alias, group_id, "judge", "judge-model",
                200, 0, 0, latency, "", api_key_id, fusion_id=fusion_id,
            )
            return result
        except Exception as exc:
            latency = int((time.time() - start) * 1000)
            error_msg = f"{type(exc).__name__}: {exc}"
            self.router._log(
                judge_alias, group_id, "judge", "judge-model",
                502, 0, 0, latency, error_msg, api_key_id, fusion_id=fusion_id,
            )
            raise UpstreamError(f"judge model failed: {exc}") from exc

    @staticmethod
    def _extract_response_text(resp: dict[str, Any]) -> str:
        """Extract text content from a chat completion response."""
        choices = resp.get("choices") or []
        if choices:
            content = (choices[0].get("message") or {}).get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                return " ".join(parts) if parts else str(content)
        content_blocks = resp.get("content") or []
        if content_blocks:
            parts = [b.get("text", "") for b in content_blocks if isinstance(b, dict) and b.get("type") == "text"]
            return " ".join(parts) if parts else ""
        return str(resp)
