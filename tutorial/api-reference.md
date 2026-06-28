# API Reference

[English](api-reference.md) | [中文](api-reference-zh.md)

---

## Proxy Endpoints (Bearer `db_sk_` auth)

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat completions (stream + non-stream) |
| `GET` | `/v1/models` | OpenAI-compatible model list (returns enabled route aliases) |
| `POST` | `/v1/messages` | Anthropic Messages-compatible (stream + non-stream) |
| `POST` | `/v1/messages/count_tokens` | Anthropic token count estimate |
| `POST` | `/v1/generations` | Generic generation forwarding (image/video/3D) |

All proxy endpoints require `Authorization: Bearer db_sk_...` header. The key must be enabled and not expired.

## Admin Endpoints (`X-Admin-Token` header or session cookie)

### Auth

| Method | Path | Description |
|---|---|---|
| `POST` | `/admin/login` | Login with admin token → session cookie |
| `GET` | `/admin/session` | Verify session |
| `POST` | `/admin/logout` | Logout |
| `GET` | `/admin/config` | Runtime config (base URL for key setup) |

### Groups

| Method | Path | Description |
|---|---|---|
| `GET/POST` | `/admin/llm/groups` | List / create groups |
| `GET/PATCH/DELETE` | `/admin/llm/groups/{id}` | Get / update / delete a group |
| `POST` | `/admin/llm/groups/{id}/copy` | Deep-copy a group (re-issues new keys) |

### Providers

| Method | Path | Description |
|---|---|---|
| `GET/POST` | `/admin/llm/groups/{id}/providers` | List / create providers in a group |
| `GET/PATCH/DELETE` | `/admin/llm/providers/{id}` | Get / update / delete a provider |

### Routes

| Method | Path | Description |
|---|---|---|
| `GET/POST` | `/admin/llm/groups/{id}/routes` | List / create routes in a group |
| `GET/PATCH/DELETE` | `/admin/llm/routes/{id}` | Get / update / delete a route |

Route create/update accepts `mode` (`direct`, `auto-select`, `adapter`, `fusion`), `adapter_config` (JSON string), and `fusion_config` (JSON string).

### Route Providers (multi-provider associations)

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/llm/routes/{route_id}/providers` | List provider associations for a route |
| `POST` | `/admin/llm/routes/{route_id}/providers` | Add a provider to a route (with priority) |
| `PATCH` | `/admin/llm/route-providers/{rp_id}` | Update priority / enabled / upstream_model |
| `DELETE` | `/admin/llm/route-providers/{rp_id}` | Remove a provider from a route |

### Provider Health (circuit breaker)

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/llm/health` | Provider health overview (optional `?group_id=` filter) |
| `POST` | `/admin/llm/health/{provider_id}/reset` | Manually reset circuit breaker |

### API Keys

| Method | Path | Description |
|---|---|---|
| `GET/POST` | `/admin/llm/groups/{id}/keys` | List / create API keys in a group |
| `GET` | `/admin/llm/keys/{id}/plaintext` | Retrieve key plaintext (admin only) |
| `PATCH/DELETE` | `/admin/llm/keys/{id}` | Update / delete an API key |

### Tool Providers

| Method | Path | Description |
|---|---|---|
| `GET/POST` | `/admin/llm/groups/{id}/tool-providers` | List / create tool providers |
| `PATCH/DELETE` | `/admin/llm/tool-providers/{id}` | Update / delete a tool provider |

### Logs & Testing

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/llm/logs` | Request logs (filter by `?api_key_id=` and `?group_id=`) |
| `GET` | `/admin/llm/stats` | Stats for a specific key |
| `POST` | `/admin/llm/test` | Probe a single provider or route |
| `POST` | `/admin/llm/e2e` | End-to-end test of all enabled routes |
