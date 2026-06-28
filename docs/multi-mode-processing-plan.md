# Keyway Multi-Mode Processing — Implementation Plan

> Status: Planning document, not yet implemented
> Base version: Keyway v0.1.2
> Target version: v0.2.0 (Phase 1) → v0.3.0 (Phase 2) → v0.4.0 (Phase 3)

## 1. Overview

Keyway currently implements **direct forwarding only** (mode one): a client sends a request with a model alias, Keyway resolves it to a single upstream provider, and forwards the request as-is. This document plans three additional processing modes that build on top of the existing `LLMRouter`:

| Mode | Purpose | Status |
|---|---|---|
| **direct** | Alias → single provider → forward (current) | ✅ Implemented (v0.1.x) |
| **auto-select** | Automatically pick the best provider based on request content, health, and cost | 📋 Phase 1 (v0.2.0) |
| **adapter** | Pre-process the request so a text-only model can handle multimodal input (e.g. images) | 📋 Phase 2 (v0.3.0) |
| **fusion** | Dispatch to multiple providers in parallel, judge, and synthesize a final answer | 📋 Phase 3 (v0.4.0) |

All modes are accessed through the same `/v1/chat/completions` and `/v1/messages` endpoints. The mode is determined per-route via a new `mode` field on the route configuration, defaulting to `direct`.

## 2. Current Architecture (v0.1.x)

```
Client (Bearer db_sk_...)
  │ POST /v1/chat/completions
  ▼
app.py: v1_chat_completions()
  │ 1. _resolve_llm_api_key() → key_row (with group_id)
  │ 2. router.resolve_route(alias, group_id, required_protocol) → (route, provider)
  │ 3. if stream: router.stream(body, resolved)
  │    else:     router.complete(body, resolved)
  ▼
LLMRouter:
  │ resolve_route()  →  get_route_by_alias_in_group() + get_provider_with_key_in_group()
  │ stream()         →  _call_upstream_stream() → yield SSE bytes
  │ complete()       →  _call_upstream_non_stream() (+ tool-use loop for OpenAI)
  ▼
Upstream Provider
```

Key files:
- `src/keyway/llm_router.py` — `LLMRouter` class (resolve, stream, complete, probe, forward_to_path)
- `src/keyway/llm_store.py` — `LLMStore` class (SQLite CRUD for groups/providers/routes/keys/tools/logs)
- `src/keyway/app.py` — FastAPI endpoints, auth, request dispatch

## 3. Phase 1: Auto-Select Mode (v0.2.0)

### 3.1 Goal

Instead of binding an alias to a single provider, allow an alias to resolve to multiple candidate providers. Keyway selects the best one based on:
- **Health**: skip providers that recently failed (circuit breaker)
- **Protocol match**: only consider providers matching the client's protocol
- **Priority**: a `priority` field on the route-provider association (lower = higher priority)
- **Cost** (future): prefer cheaper providers when multiple are healthy

### 3.2 Database Changes

New table `route_providers` (many-to-many between routes and providers):

```sql
CREATE TABLE IF NOT EXISTS route_providers (
    rp_id        TEXT PRIMARY KEY,          -- UUID hex
    route_id     TEXT NOT NULL,
    provider_id  TEXT NOT NULL,
    upstream_model TEXT NOT NULL,           -- may differ per provider
    priority     INTEGER NOT NULL DEFAULT 0, -- lower = preferred
    enabled      INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL,
    FOREIGN KEY (route_id)    REFERENCES model_routes(route_id) ON DELETE CASCADE,
    FOREIGN KEY (provider_id) REFERENCES llm_providers(provider_id) ON DELETE CASCADE
);
CREATE INDEX idx_route_providers_route ON route_providers(route_id, priority);
```

Existing `model_routes.upstream_model` and `model_routes.provider_id` remain as the **primary** binding (backward compat). When `route_providers` rows exist for a route, auto-select mode kicks in.

New table `provider_health` (circuit breaker state):

```sql
CREATE TABLE IF NOT EXISTS provider_health (
    provider_id     TEXT PRIMARY KEY,
    group_id        TEXT NOT NULL DEFAULT 'default',
    consecutive_fails INTEGER NOT NULL DEFAULT 0,
    last_fail_at    TEXT,
    last_success_at TEXT,
    circuit_open    INTEGER NOT NULL DEFAULT 0,  -- 1 = skip this provider
    circuit_open_until TEXT,                      -- ISO timestamp for auto-reset
    FOREIGN KEY (provider_id) REFERENCES llm_providers(provider_id) ON DELETE CASCADE
);
```

### 3.3 Router Changes

New method in `LLMRouter`:

```python
def resolve_route_auto(
    self, alias: str, *, group_id: str = "", required_protocol: str | None = None,
) -> list[tuple[dict, dict]]:
    """Resolve an alias to a ranked list of (route, provider) candidates.

    Filters out: disabled routes, disabled providers, protocol mismatch,
    and providers with open circuits.
    Returns candidates sorted by priority (ascending).
    """
```

Circuit breaker logic:
- On upstream error (status >= 500, timeout, connection refused): `consecutive_fails += 1`
- After 3 consecutive fails: `circuit_open = 1`, `circuit_open_until = now + 60s`
- On success: `consecutive_fails = 0`, `circuit_open = 0`
- `resolve_route_auto` skips providers where `circuit_open = 1` and `now < circuit_open_until`

### 3.4 Request Flow (auto-select)

```
Client request (model="smart-alias")
  │
  ▼
resolve_route_auto("smart-alias", group_id, protocol)
  │ → candidates = [(route, provider_A, prio=0), (route, provider_B, prio=1)]
  │
  ▼
Try candidates in priority order:
  │ 1. Try provider_A → success? return response
  │ 2. If fail: record health, try provider_B → success? return response
  │ 3. If all fail: return 502
  │
  ▼
Response to client (with X-Keyway-Provider header for transparency)
```

### 3.5 Admin UI Changes

- Route form: add "Mode" dropdown (`direct` / `auto-select` / `adapter` / `fusion`)
- When mode = `auto-select`: show a multi-provider selector with priority fields
- New "Provider Health" panel showing circuit breaker state

### 3.6 API Changes

```python
# New admin endpoints
GET  /admin/llm/routes/{id}/providers          # list route-provider associations
POST /admin/llm/routes/{id}/providers          # add a provider to a route
PATCH /admin/llm/route-providers/{rp_id}       # update priority/enabled
DELETE /admin/llm/route-providers/{rp_id}      # remove a provider from a route

GET  /admin/llm/health                          # provider health overview
POST /admin/llm/health/{provider_id}/reset      # manually reset circuit breaker
```

### 3.7 Estimated Effort

| Task | Effort |
|---|---|
| DB schema + LLMStore methods | 0.5 day |
| Circuit breaker + resolve_route_auto | 1 day |
| app.py endpoint integration (try-next-on-fail) | 0.5 day |
| Admin UI (mode dropdown, multi-provider selector, health panel) | 1 day |
| Tests | 0.5 day |
| **Total** | **3.5 days** |

---

## 4. Phase 2: Adapter Mode (v0.3.0)

### 4.1 Goal

Allow a text-only model to handle requests that contain multimodal content (e.g. images). Keyway detects the input modality, runs a pre-processing step (e.g. describe the image using a vision model), and injects the result as text into the request before forwarding to the text model.

### 4.2 Architecture

```
Client request (model="text-alias", content contains image)
  │
  ▼
ModalityDetector
  │ → detects: input contains image blocks
  │
  ▼
AdapterPipeline
  │ → ImageDescriber: calls a vision model (separate route) to describe the image
  │ → replaces image blocks with text: "[Image: <description>]"
  │
  ▼
LLMRouter.complete() / stream()  (modified request, now text-only)
  │
  ▼
Upstream text model
```

### 4.3 New Modules

```
src/keyway/
├── modality.py          # ModalityDetector
├── adapters.py          # AdapterPipeline, ImageDescriber, future adapters
```

### 4.4 ModalityDetector

```python
class ModalityDetector:
    @staticmethod
    def detect(req_body: dict) -> set[str]:
        """Return a set of modalities found in the request body.
        Possible values: {"text"}, {"text", "image"}, {"text", "image", "tool_result"}, etc.
        """
        modalities = {"text"}
        for msg in req_body.get("messages", []):
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "image" or block.get("type") == "image_url":
                            modalities.add("image")
                        elif block.get("type") == "tool_result":
                            modalities.add("tool_result")
        return modalities
```

### 4.5 ImageDescriber

```python
class ImageDescriber:
    """Pre-processes image content by calling a vision-capable model to
    generate a text description, then replaces the image block with text."""

    def __init__(self, router: LLMRouter, vision_alias: str):
        self.router = router
        self.vision_alias = vision_alias  # a route alias pointing to a vision model

    async def adapt(self, req_body: dict, group_id: str) -> dict:
        """Transform request body: replace image blocks with text descriptions."""
        for msg in req_body.get("messages", []):
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            new_blocks = []
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

    async def _describe_image(self, image_block: dict, group_id: str) -> str:
        """Call a vision model to describe the image."""
        # Resolve the vision route, build a messages array with the image,
        # call router.complete(), extract text from response.
        ...
```

### 4.6 Route Configuration

New fields on `model_routes`:

```sql
ALTER TABLE model_routes ADD COLUMN mode TEXT NOT NULL DEFAULT 'direct';
-- mode values: 'direct', 'auto-select', 'adapter', 'fusion'

ALTER TABLE model_routes ADD COLUMN adapter_config TEXT NOT NULL DEFAULT '{}';
-- JSON config for the adapter, e.g.:
-- {"vision_alias": "qwen-vl", "fallback": "skip-image"}
```

### 4.7 Request Flow (adapter)

```
v1_chat_completions(body)
  │
  ▼
route = resolve_route(alias)
  │ route.mode == "adapter"
  │
  ▼
modalities = ModalityDetector.detect(body)
  │ if "image" in modalities:
  │   adapter = AdapterPipeline(route.adapter_config)
  │   body = await adapter.adapt(body, group_id)
  │
  ▼
router.complete(body, resolved)  # now text-only, safe for text model
```

### 4.8 Estimated Effort

| Task | Effort |
|---|---|
| ModalityDetector | 0.5 day |
| ImageDescriber + AdapterPipeline | 1.5 days |
| Route mode field + DB migration | 0.5 day |
| app.py integration (mode dispatch) | 0.5 day |
| Admin UI (adapter config) | 0.5 day |
| Tests (mock vision model) | 1 day |
| **Total** | **4.5 days** |

---

## 5. Phase 3: Fusion Mode (v0.4.0)

### 5.1 Goal

Dispatch a request to multiple providers in parallel, collect all responses, then use a judge model to synthesize a final answer. This is useful for quality-critical tasks where comparing multiple models produces better results.

### 5.2 Architecture

```
Client request (model="fusion-alias")
  │
  ▼
FusionOrchestrator
  │
  ├─ 1. Resolve panel: list of (provider, upstream_model) from route_providers
  │
  ├─ 2. Parallel dispatch: asyncio.gather() → call each provider concurrently
  │     ├─ provider_A → response_A
  │     ├─ provider_B → response_B
  │     └─ provider_C → response_C
  │
  ├─ 3. Judge: send all responses to a judge model
  │     "Here are 3 candidate answers. Pick the best and explain why."
  │     judge_model → synthesized_response
  │
  └─ 4. Return synthesized_response to client
```

### 5.3 New Module

```
src/keyway/
├── fusion.py            # FusionOrchestrator, JudgeStrategies
```

### 5.4 FusionOrchestrator

```python
class FusionOrchestrator:
    def __init__(self, router: LLMRouter):
        self.router = router

    async def fuse(
        self, req_body: dict, candidates: list[tuple[dict, dict]],
        *, judge_alias: str, strategy: str = "compare_and_synthesize",
        group_id: str = "",
    ) -> dict:
        """Dispatch to all candidates in parallel, judge, return synthesized response.

        Strategies:
        - compare_and_synthesize: judge picks best parts from each response
        - majority_vote: judge picks the most common answer (good for factual Q&A)
        - ranked: judge ranks all responses, returns the top one
        """
        # 1. Parallel dispatch
        tasks = [self._call_candidate(req_body, route, provider) for route, provider in candidates]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        # 2. Filter out failures
        valid = [(c, r) for c, r in zip(candidates, responses) if not isinstance(r, Exception)]

        # 3. Judge
        if strategy == "compare_and_synthesize":
            return await self._compare_and_synthesize(req_body, valid, judge_alias, group_id)
        elif strategy == "majority_vote":
            return await self._majority_vote(req_body, valid, judge_alias, group_id)
        elif strategy == "ranked":
            return await self._ranked(req_body, valid, judge_alias, group_id)
```

### 5.5 Route Configuration

New fields on `model_routes`:

```sql
ALTER TABLE model_routes ADD COLUMN fusion_config TEXT NOT NULL DEFAULT '{}';
-- JSON config, e.g.:
-- {
--   "judge_alias": "deepseek-v4-pro",
--   "strategy": "compare_and_synthesize",
--   "min_candidates": 2,
--   "timeout_seconds": 30
-- }
```

### 5.6 Preset Panels

Pre-defined fusion panels that users can reference by name:

| Panel | Members | Judge | Strategy |
|---|---|---|---|
| `quality` | All enabled candidates | Strongest model | compare_and_synthesize |
| `budget` | 2 cheapest candidates | Cheapest model | majority_vote |
| `auto` | All healthy candidates | First healthy candidate | ranked |

These are not DB rows — they are computed at request time from the route's `route_providers` + health state.

### 5.7 Request Flow (fusion)

```
v1_chat_completions(body)
  │
  ▼
route = resolve_route(alias)
  │ route.mode == "fusion"
  │
  ▼
candidates = resolve_route_auto(alias, group_id, protocol)
  │
  ▼
orchestrator = FusionOrchestrator(router)
result = await orchestrator.fuse(body, candidates, judge_alias=..., strategy=..., group_id=...)
  │
  ▼
Return result to client
  │ (response includes X-Keyway-Fusion header with member list)
```

### 5.8 Streaming Considerations

Fusion mode does not support streaming in the initial implementation — the client must wait for all candidates + judge to complete. A future enhancement could stream the judge's output.

### 5.9 Cost Tracking

Each fusion request logs N+1 entries (N candidates + 1 judge) to `llm_request_logs`. A new `fusion_id` column groups them:

```sql
ALTER TABLE llm_request_logs ADD COLUMN fusion_id TEXT;
```

### 5.10 Estimated Effort

| Task | Effort |
|---|---|
| FusionOrchestrator + judge strategies | 2 days |
| Parallel dispatch + error handling | 1 day |
| Route fusion_config field + DB | 0.5 day |
| app.py integration | 0.5 day |
| Cost tracking (fusion_id logging) | 0.5 day |
| Admin UI (fusion config, preset panel selector) | 1 day |
| Tests (mock candidates + judge) | 1 day |
| **Total** | **6.5 days** |

---

## 6. Unified Mode Dispatch

All four modes are dispatched from a single point in `app.py`:

```python
@app.post("/v1/chat/completions")
async def v1_chat_completions(request, key = Depends(_resolve_llm_api_key)):
    body = await request.json()
    alias = body.get("model", "")
    group_id = key.get("group_id", "")
    route, provider = router.resolve_route(alias, group_id=group_id, required_protocol="openai")

    mode = route.get("mode") or "direct"

    if mode == "direct":
        # Current behavior: single provider, stream or complete
        ...

    elif mode == "auto-select":
        candidates = router.resolve_route_auto(alias, group_id=group_id, required_protocol="openai")
        # Try each candidate until success
        ...

    elif mode == "adapter":
        modalities = ModalityDetector.detect(body)
        if modalities > {"text"}:
            body = await adapter_pipeline.adapt(body, group_id, route.get("adapter_config"))
        # Then proceed as direct
        ...

    elif mode == "fusion":
        candidates = router.resolve_route_auto(alias, group_id=group_id, required_protocol="openai")
        result = await fusion_orchestrator.fuse(body, candidates, **fusion_config)
        return JSONResponse(result)
```

## 7. Implementation Priority

| Phase | Version | Value | Effort |
|---|---|---|---|
| Phase 1: Auto-Select | v0.2.0 | High — failover is the most commonly needed feature | 3.5 days |
| Phase 2: Adapter | v0.3.0 | Medium — multimodal support for text models | 4.5 days |
| Phase 3: Fusion | v0.4.0 | Lower — advanced use case, higher cost | 6.5 days |
| **Total** | | | **14.5 days** |

## 8. Backward Compatibility

- All existing routes default to `mode = "direct"` — no behavior change on upgrade
- The `mode` column is added via `_ensure_column()`, which is a no-op for existing DBs
- Existing `model_routes.provider_id` and `model_routes.upstream_model` remain the primary binding for direct mode
- `route_providers` table is only consulted when `mode != "direct"`
- All new endpoints are additive — no existing endpoints change

## 9. Testing Strategy

| Phase | Test approach |
|---|---|
| Phase 1 | Mock upstream providers with controlled fail/succeed; verify circuit breaker opens/closes; verify fallback order |
| Phase 2 | Mock vision model returns canned descriptions; verify image blocks are replaced with text; verify text-only fallback |
| Phase 3 | Mock 3 candidate providers with different responses; mock judge; verify synthesis output; verify fusion_id logging |

All tests use `monkeypatch` to mock `httpx.AsyncClient` — no real API calls needed.
