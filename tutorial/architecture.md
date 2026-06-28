# Architecture

[English](architecture.md) | [中文](architecture-zh.md)

---

## Tech Stack

- **Backend**: FastAPI + uvicorn, 5 pip dependencies (`fastapi`, `uvicorn`, `httpx`, `cryptography`, `pydantic`)
- **Storage**: SQLite (single file, `keyway.db`) — no external database
- **Auth**: Admin token (single-admin) + self-issued `db_sk_` API keys (group-scoped)
- **Encryption**: Fernet (from `cryptography`) — SHA-256 of `KEYWAY_SECRET` derives the key
- **Frontend**: Zero-dependency vanilla JS, served by FastAPI's StaticFiles

## Project Structure

```
src/keyway/
├── __init__.py          # version
├── __main__.py          # CLI entry point (uvicorn launcher)
├── app.py               # FastAPI app: endpoints, auth, request dispatch
├── config.py            # Settings from env vars
├── crypto.py            # Fernet encryption helpers
├── llm_keys.py          # db_sk_ key generation, hashing, prefix
├── llm_protocol.py      # Protocol detection helpers
├── llm_router.py        # LLMRouter: resolve, stream, complete, auto-select, probe
├── llm_store.py         # LLMStore: SQLite CRUD (8 tables)
├── llm_tools.py         # Builtin tools (Tavily search)
├── models.py            # Pydantic request schemas
├── modality.py          # ModalityDetector (image/tool detection)
├── adapters.py          # AdapterPipeline, ImageDescriber
├── fusion.py            # FusionOrchestrator, judge strategies
└── web/                 # Admin UI (static HTML/JS/CSS)
```

## Database Schema

8 SQLite tables:

| Table | Purpose |
|---|---|
| `llm_groups` | Routing groups (isolation boundary) |
| `llm_providers` | Upstream LLM providers (base_url, api_key, protocol) |
| `model_routes` | Alias → provider bindings (with mode, adapter_config, fusion_config) |
| `route_providers` | Multi-provider associations for auto-select/fusion (with priority) |
| `provider_health` | Circuit breaker state (consecutive_fails, circuit_open) |
| `llm_api_keys` | Self-issued db_sk_ keys (group-scoped, encrypted plaintext) |
| `llm_tool_providers` | Tool providers (e.g. Tavily) |
| `llm_request_logs` | Request logs (with fusion_id for fusion grouping) |

## Request Flow

```
Client (Bearer db_sk_...)
  │ POST /v1/chat/completions  or  /v1/messages
  ▼
app.py: resolve route by alias + group
  │ route.mode → dispatch
  │
  ├─ direct:     router.complete() / router.stream()
  ├─ auto-select: router.resolve_route_auto() → try candidates in order
  ├─ adapter:    AdapterPipeline.adapt() → then direct
  └─ fusion:     FusionOrchestrator.fuse() → parallel + judge
  ▼
Upstream Provider(s)
```

## Development

```bash
pip install -e ".[dev]"
pytest -q
```
