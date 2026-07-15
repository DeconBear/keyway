# Upstream Key Pool & User Key Quotas

[中文](key-pool-zh.md) | [English](key-pool.md)

---

Keyway can pool multiple upstream API keys behind one Provider, then issue many `db_sk_` keys to users with optional quotas — inspired by sub2api’s pool → distribute shape, without billing/payment.

## Architecture

```
Upstream keys (N)  →  Provider credential pool  →  Model route (alias)
                                                      ↓
User keys (M × db_sk_)  ←  group-scoped issue + quota/concurrency/RPM
```

- **Credential pool**: same `base_url` / `protocol`, many keys
- **Scheduling**: priority bands + round-robin; failover on 429 / 5xx / transport errors
- **User keys**: existing `db_sk_` with optional `max_requests`, `max_tokens`, `concurrency_limit`, `rpm_limit`

Not in v1: sticky sessions, USD billing, payments, OAuth accounts, multi-tenant user portal.

## Configure an upstream pool

1. Create a Provider as usual (first key becomes the primary credential).
2. In Admin → Providers → **Keys**, add more upstream API keys (label + priority).
3. Point a Model Route at that Provider (`direct` is enough for same-model pooling).

`auto-select` / `fusion` still pick **which Provider**; the pool picks **which key inside** that Provider.

## Issue user keys

Create `db_sk_` keys under the group. Optional limits:

| Field | Effect |
|---|---|
| `max_requests` | Hard stop after N requests |
| `max_tokens` | Hard stop after estimated tokens |
| `concurrency_limit` | In-process concurrent requests |
| `rpm_limit` | Sliding 60s request window |

Exceeded limits return HTTP `429`.

## Admin API

```bash
# List / add credentials
GET  /admin/llm/providers/{id}/credentials
POST /admin/llm/providers/{id}/credentials
PATCH /admin/llm/credentials/{credential_id}
DELETE /admin/llm/credentials/{credential_id}

# User key with quota
POST /admin/llm/groups/{gid}/keys
# body may include max_requests, max_tokens, concurrency_limit, rpm_limit
```

## vs sub2api

| | Keyway v1 | sub2api |
|---|---|---|
| Upstream key pool | Yes | Yes (accounts) |
| User API keys | Yes (`db_sk_`) | Yes |
| Failover / RR | Yes | Yes (+ sticky) |
| Quotas | Requests / tokens / conc / RPM | Richer windows + USD |
| Billing / payment | No | Yes |
| OAuth subscriptions | No | Yes |
