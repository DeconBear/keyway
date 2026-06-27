# Keyway

**A lightweight self-hosted LLM routing gateway with OpenAI & Anthropic dual-protocol support.**

[English](README.md) | [中文](README-zh.md)

---

Keyway lets you route LLM requests from any OpenAI/Anthropic-compatible client (Claude Code, Cursor, OpenAI SDK, etc.) to multiple upstream providers (DeepSeek, OpenAI, Anthropic, Volcengine, Zhipu GLM, Qwen, and more) — all through a single self-issued `db_sk_` API key.

## Features

- **Dual-protocol proxy**: OpenAI `/v1/chat/completions` + Anthropic `/v1/messages` — both work out of the box
- **Model aliases**: map a client-facing name (e.g. `deepseek-v4-pro`) to any upstream model
- **Group isolation**: keys are bound to groups; a client's key can only access its group's providers/routes
- **Self-issued API keys**: generate `db_sk_` keys for your team; plaintext is retrievable by admin
- **Encrypted at rest**: all upstream API keys and self-issued key plaintexts are Fernet-encrypted
- **Built-in tools**: Tavily web search auto-injected into OpenAI tool-use loops
- **Request logging**: every upstream call is logged with status, latency, and token counts
- **E2E testing**: one-click probe of all enabled routes
- **Generation forwarding**: image/video/3D endpoints via configurable `upstream_path`
- **No external dependencies**: just Python + SQLite — no database server, no Redis
- **Web admin UI**: full CRUD management interface included

## Quick Start

### Option 1: pip install

```bash
pip install keyway-router

# Generate a secret and create .env
python -c "import secrets; print('KEYWAY_SECRET=' + secrets.token_urlsafe(48))" > .env
echo "KEYWAY_ADMIN_TOKEN=my-admin-token" >> .env

# Run
keyway
# → Server starts on http://localhost:9233
```

### Option 2: Docker

```bash
cd docker
cp .env.example .env
# Edit .env: set KEYWAY_SECRET and KEYWAY_ADMIN_TOKEN
docker compose up -d
# → Server at http://localhost:9233
```

### Option 3: From source

```bash
git clone https://github.com/DeconBear/keyway.git
cd keyway
pip install -e ".[dev]"

cp .env.example .env
# Edit .env: set KEYWAY_SECRET (required) and KEYWAY_ADMIN_TOKEN

python -m keyway
```

## Configuration

All settings are via environment variables (or `.env` file):

| Variable | Default | Description |
|---|---|---|
| `KEYWAY_SECRET` | *(required)* | Fernet encryption key for at-rest secrets. Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `KEYWAY_ADMIN_TOKEN` | *(auto-generated)* | Admin token for the management UI. If empty, a random token is printed to console on startup |
| `KEYWAY_HOST` | `127.0.0.1` | Bind address |
| `KEYWAY_PORT` | `9233` | Bind port |
| `KEYWAY_DATA_DIR` | `./data` | SQLite database location |
| `KEYWAY_CORS_ORIGINS` | `http://127.0.0.1:9233,...` | CORS allowed origins |
| `KEYWAY_PUBLIC_BASE_URL` | *(auto-inferred)* | Base URL shown in admin UI for key setup |
| `KEYWAY_LOG_LEVEL` | `info` | Log level |

## Usage Guide

### 1. Access the admin UI

Open `http://localhost:9233/` in your browser. Log in with your `KEYWAY_ADMIN_TOKEN`.

### 2. Add an upstream provider

In the "default" group, scroll to "Upstream Providers", fill in:
- **ID**: e.g. `deepseek`
- **Name**: e.g. `DeepSeek`
- **Protocol**: `openai` or `anthropic`
- **Base URL**: e.g. `https://api.deepseek.com/v1`
- **API Key**: your upstream provider key

### 3. Create a model route

Scroll to "Model Routes", fill in:
- **Alias**: the name clients will use, e.g. `deepseek-v4-pro`
- **Provider**: select the provider you just created
- **Upstream Model**: the real model name at the provider, e.g. `deepseek-chat`

### 4. Create an API key

Scroll to "Self-issued API Keys", create a key. The plaintext `db_sk_...` is shown once — save it. You can re-retrieve it later from the key list.

### 5. Connect your client

#### Claude Code

Create `.claude/settings.local.json` in your project:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:9233",
    "ANTHROPIC_AUTH_TOKEN": "db_sk_your-key-here",
    "ANTHROPIC_MODEL": "deepseek-v4-pro",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-v4-pro",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "deepseek-v4-pro",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "deepseek-v4-pro"
  }
}
```

#### OpenAI SDK (Python)

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:9233/v1",
    api_key="db_sk_your-key-here",
)

resp = client.chat.completions.create(
    model="deepseek-v4-pro",
    messages=[{"role": "user", "content": "Hello!"}],
)
```

## Usage Example: Multi-Provider Setup

This example configures four upstream models through Keyway, then connects Claude Code to switch between them using the `/model` command.

### Step 1: Add four providers

Open the admin UI (`http://localhost:9233/`), go to the "default" group, and create these providers:

| Provider ID | Name | Protocol | Base URL | Where to get API Key |
|---|---|---|---|---|
| `deepseek` | DeepSeek | openai | `https://api.deepseek.com/v1` | https://platform.deepseek.com/ |
| `zhipu` | Zhipu GLM | openai | `https://open.bigmodel.cn/api/paas/v4` | https://open.bigmodel.cn/ |
| `minimax` | MiniMax | openai | `https://api.minimaxi.com/v1` | https://platform.minimaxi.com/ |
| `moonshot` | Moonshot (Kimi) | openai | `https://api.moonshot.cn/v1` | https://platform.moonshot.cn/ |

### Step 2: Create four model routes

In the same group, go to "Model Routes" and create:

| Alias (client-facing) | Provider | Upstream Model |
|---|---|---|
| `deepseek-v4-pro` | deepseek | `deepseek-chat` |
| `glm-5.2` | zhipu | `glm-4-plus` |
| `minimax-m3` | minimax | `MiniMax-M3` |
| `kimi-k2.7-code` | moonshot | `kimi-k2-0905-preview` |

> Model IDs change frequently — verify the exact upstream model name on each provider's console.

### Step 3: Create an API key

Go to "Self-issued API Keys", create a key (e.g. named "claude-code"). You'll get a `db_sk_...` plaintext. Save it.

### Step 4: Connect Claude Code

Create `.claude/settings.local.json` in your project root (add it to `.gitignore`!):

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:9233",
    "ANTHROPIC_AUTH_TOKEN": "db_sk_your-key-here",
    "ANTHROPIC_MODEL": "deepseek-v4-pro",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-v4-pro",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "deepseek-v4-pro",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "deepseek-v4-pro"
  }
}
```

> **Base URL rules** (local):
> - **Anthropic SDK / Claude Code**: `http://localhost:9233` (no trailing slash; SDK auto-appends `/v1/messages`)
> - **OpenAI SDK**: `http://localhost:9233/v1` (SDK appends `/chat/completions`)

### Step 5: Switch models with `/model`

Once the four routes are configured, you can switch between them **directly inside Claude Code** at any time — no restart, no config change:

```
/model deepseek-v4-pro
/model glm-5.2
/model minimax-m3
/model kimi-k2.7-code
```

The `ANTHROPIC_MODEL` in your settings is just the default; `/model` overrides it for the current session. All four aliases route through the same `db_sk_` key and the same Keyway server.

### Step 6 (optional): Use CC Switch for profile management

[CC Switch](https://github.com/farion1231/cc-switch) is a desktop GUI that helps you manage and organize Claude Code configuration profiles. If you maintain multiple projects or environments (e.g. different Keyway servers, different default models), CC Switch lets you pre-create a profile per alias so you can switch the **default** model without editing `.claude/settings.local.json` by hand:

| Profile | ANTHROPIC_MODEL |
|---|---|
| DeepSeek | `deepseek-v4-pro` |
| GLM | `glm-5.2` |
| MiniMax | `minimax-m3` |
| Kimi | `kimi-k2.7-code` |

All profiles share the same `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN` — only `ANTHROPIC_MODEL` differs. Note that CC Switch changes the **default** model that Claude Code starts with; you can still use `/model` in-session to switch on the fly.

### Step 7: Verify with curl

```bash
# OpenAI protocol
curl http://localhost:9233/v1/chat/completions \
  -H "Authorization: Bearer db_sk_your-key" \
  -H "Content-Type: application/json" \
  -d '{"model":"glm-5.2","messages":[{"role":"user","content":"Hello!"}],"max_tokens":16}'

# Anthropic protocol (for Anthropic-protocol upstreams only)
curl http://localhost:9233/v1/messages \
  -H "Authorization: Bearer db_sk_your-key" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-pro","messages":[{"role":"user","content":"Hello!"}],"max_tokens":16}'
```

> **Protocol note**: OpenAI-protocol clients (`/v1/chat/completions`) require OpenAI-protocol providers. Anthropic-protocol clients (`/v1/messages`) require Anthropic-protocol providers. All four providers in this example use OpenAI protocol, so use the OpenAI endpoint (`/v1/chat/completions`) for direct API calls. Claude Code uses the Anthropic endpoint (`/v1/messages`) — to use Claude Code with OpenAI-protocol upstreams, add an Anthropic-protocol provider (e.g. Anthropic itself) and create routes with the same aliases.

## API Reference

### Proxy endpoints (Bearer `db_sk_` auth)

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat completions (stream + non-stream) |
| `GET` | `/v1/models` | OpenAI-compatible model list (returns enabled route aliases) |
| `POST` | `/v1/messages` | Anthropic Messages-compatible (stream + non-stream) |
| `POST` | `/v1/messages/count_tokens` | Anthropic token count estimate |
| `POST` | `/v1/generations` | Generic generation forwarding (image/video/3D) |

### Admin endpoints (`X-Admin-Token` header or session cookie)

| Method | Path | Description |
|---|---|---|
| `POST` | `/admin/login` | Login with admin token → session cookie |
| `GET` | `/admin/session` | Verify session |
| `POST` | `/admin/logout` | Logout |
| `GET` | `/admin/config` | Runtime config (base URL for key setup) |
| `GET/POST` | `/admin/llm/groups` | List / create groups |
| `GET/PATCH/DELETE` | `/admin/llm/groups/{id}` | Get / update / delete a group |
| `POST` | `/admin/llm/groups/{id}/copy` | Deep-copy a group (re-issues new keys) |
| `GET/POST` | `/admin/llm/groups/{id}/providers` | List / create providers in a group |
| `GET/PATCH/DELETE` | `/admin/llm/providers/{id}` | Get / update / delete a provider |
| `GET/POST` | `/admin/llm/groups/{id}/routes` | List / create routes in a group |
| `GET/PATCH/DELETE` | `/admin/llm/routes/{id}` | Get / update / delete a route |
| `GET/POST` | `/admin/llm/groups/{id}/keys` | List / create API keys in a group |
| `GET` | `/admin/llm/keys/{id}/plaintext` | Retrieve key plaintext (admin only) |
| `PATCH/DELETE` | `/admin/llm/keys/{id}` | Update / delete an API key |
| `GET/POST` | `/admin/llm/groups/{id}/tool-providers` | List / create tool providers |
| `PATCH/DELETE` | `/admin/llm/tool-providers/{id}` | Update / delete a tool provider |
| `GET` | `/admin/llm/logs` | Request logs (filter by api_key_id, group_id) |
| `GET` | `/admin/llm/stats` | Stats for a specific key |
| `POST` | `/admin/llm/test` | Probe a single provider or route |
| `POST` | `/admin/llm/e2e` | End-to-end test of all enabled routes |

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

## Architecture

- **Backend**: FastAPI + uvicorn, 5 pip dependencies (`fastapi`, `uvicorn`, `httpx`, `cryptography`, `pydantic`)
- **Storage**: SQLite (single file, `keyway.db`) — no external database
- **Auth**: Admin token (single-admin) + self-issued `db_sk_` API keys (group-scoped)
- **Encryption**: Fernet (from `cryptography`) — SHA-256 of `KEYWAY_SECRET` derives the key
- **Frontend**: Zero-dependency vanilla JS, served by FastAPI's StaticFiles

## License

MIT — see [LICENSE](LICENSE).
