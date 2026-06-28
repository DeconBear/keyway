# Multi-Mode Processing

[English](multi-mode-processing.md) | [中文](multi-mode-processing-zh.md)

---

Keyway supports four processing modes, all dispatched through the same `/v1/chat/completions` and `/v1/messages` endpoints. The mode is set per-route via the `mode` field (default: `direct`).

| Mode | Purpose |
|---|---|
| `direct` | Alias → single provider → forward (default) |
| `auto-select` | Try multiple providers in priority order; fail over on 5xx/timeout; circuit breaker protection |
| `adapter` | Detect images in the request, describe them via a vision model, forward text-only request |
| `fusion` | Dispatch to multiple providers in parallel, judge synthesizes a final answer |

---

## Direct Mode (default)

No special configuration needed. This is the standard single-provider passthrough. All existing routes default to `direct` — upgrading is a no-op.

---

## Auto-Select Mode

Instead of binding an alias to a single provider, auto-select resolves to multiple candidate providers and tries them in priority order. If a provider fails with a retryable error (5xx, timeout), Keyway automatically fails over to the next candidate.

### Setup

1. Create a route with `mode = "auto-select"`.
2. Add multiple providers to the route via the **route-providers** admin API (or UI).
3. Set a `priority` on each — lower number = tried first.

```bash
# Create the route (primary provider is the fallback)
curl -X POST http://localhost:9233/admin/llm/groups/default/routes \
  -H "X-Admin-Token: my-admin-token" \
  -H "Content-Type: application/json" \
  -d '{"alias":"smart","provider_id":"p1","upstream_model":"m1","mode":"auto-select"}'

# Add a second provider with priority 1
curl -X POST http://localhost:9233/admin/llm/routes/{route_id}/providers \
  -H "X-Admin-Token: my-admin-token" \
  -H "Content-Type: application/json" \
  -d '{"provider_id":"p2","upstream_model":"m2","priority":1}'
```

### Circuit Breaker

Each provider has a health record. After **3 consecutive failures**, the circuit opens and the provider is skipped for **60 seconds**. On success, the circuit resets.

- 5xx errors and timeouts → counted as failures, trigger failover
- 4xx errors → not retryable, returned to client immediately (no failover)

Manage circuit breakers via admin API:

```bash
# View all provider health
curl http://localhost:9233/admin/llm/health -H "X-Admin-Token: my-admin-token"

# Reset a provider's circuit breaker
curl -X POST http://localhost:9233/admin/llm/health/p1/reset \
  -H "X-Admin-Token: my-admin-token"
```

### Streaming

Auto-select streaming picks the highest-priority healthy candidate. Mid-stream failover is not supported (once bytes are sent, the stream is committed).

---

## Adapter Mode

Adapter mode lets a **text-only model** handle requests that contain images. Keyway detects image content, calls a separate vision model route to generate a text description, and replaces the image with `[Image: <description>]` before forwarding.

### Setup

1. Create a vision-capable route (e.g. alias `qwen-vl` → vision model).
2. Create a text route with `mode = "adapter"` and configure `adapter_config`:

```json
{
  "vision_alias": "qwen-vl",
  "fallback": "skip-image"
}
```

| Config field | Description |
|---|---|
| `vision_alias` | Route alias pointing to a vision-capable model (required for image adaptation) |
| `fallback` | `"skip-image"` — replace image with placeholder on failure; `"error"` — propagate the error (default) |

### Behavior

- Requests **without** images pass through unchanged (zero overhead).
- Requests **with** images: each image block is sent to the vision model, the description is injected as text, then the modified request is forwarded to the text model.
- Works with both OpenAI-style (`image_url`) and Anthropic-style (`image` + `source`) content blocks.

---

## Fusion Mode

Fusion mode dispatches a request to **all candidate providers in parallel**, collects the responses, and sends them to a **judge model** that synthesizes a final answer. Useful for quality-critical tasks.

### Setup

1. Create candidate providers and associate them with the route (same as auto-select).
2. Create a separate judge route (e.g. alias `judge` → a strong model).
3. Create a route with `mode = "fusion"` and configure `fusion_config`:

```json
{
  "judge_alias": "judge",
  "strategy": "compare_and_synthesize",
  "min_candidates": 2,
  "timeout_seconds": 30
}
```

| Config field | Default | Description |
|---|---|---|
| `judge_alias` | *(required)* | Route alias pointing to the judge model |
| `strategy` | `compare_and_synthesize` | Judge strategy (see below) |
| `min_candidates` | `2` | Minimum healthy candidates required |
| `timeout_seconds` | `30` | Per-candidate timeout |

### Judge Strategies

| Strategy | Description |
|---|---|
| `compare_and_synthesize` | Judge picks the best parts from each candidate and synthesizes a combined answer |
| `majority_vote` | Judge identifies the consensus answer (good for factual Q&A) |
| `ranked` | Judge ranks all responses and returns the top one verbatim |

### Behavior

- All candidates are called in parallel (`asyncio.gather`). Partial failures are tolerated — the judge runs on whatever survived.
- If fewer than `min_candidates` succeed, the request fails.
- **Streaming is not supported** in fusion mode — the client waits for all candidates + judge.
- Each fusion request logs N+1 entries to `llm_request_logs`, grouped by a shared `fusion_id`.
- Responses include `X-Keyway-Fusion` (comma-separated provider list) and `X-Keyway-Fusion-Id` headers.

---

## Admin API for Route Providers

All modes except `direct` use the `route_providers` table to associate multiple providers with a route:

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/llm/routes/{route_id}/providers` | List provider associations |
| `POST` | `/admin/llm/routes/{route_id}/providers` | Add a provider (with priority) |
| `PATCH` | `/admin/llm/route-providers/{rp_id}` | Update priority / enabled / upstream_model |
| `DELETE` | `/admin/llm/route-providers/{rp_id}` | Remove a provider association |
| `GET` | `/admin/llm/health` | View provider circuit breaker state |
| `POST` | `/admin/llm/health/{provider_id}/reset` | Reset a provider's circuit breaker |

## Backward Compatibility

- All existing routes default to `mode = "direct"` — no behavior change on upgrade.
- The `mode` column is added via `_ensure_column()`, which is a no-op for existing databases.
- `route_providers` is only consulted when `mode != "direct"`.
- All new endpoints are additive — no existing endpoints change.
