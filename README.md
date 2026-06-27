# Keyway

**A lightweight self-hosted LLM routing gateway with OpenAI & Anthropic dual-protocol support.**

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
- **Single binary / Docker**: no database server, no Redis, no external dependencies — just Python + SQLite
- **Web admin UI**: full CRUD management interface included

## Quick Start

### Option 1: pip install

```bash
pip install keyway

# Create .env
cat > .env <<'EOF'
KEYWAY_SECRET=$(python -c "import secrets; print(secrets.token_urlsafe(48))")
KEYWAY_ADMIN_TOKEN=my-admin-token
EOF

# Actually set the secret (the above is illustrative):
python -c "import secrets; print('KEYWAY_SECRET=' + secrets.token_urlsafe(48))" >> .env

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
git clone https://github.com/your-org/keyway.git
cd keyway
pip install -e ".[dev]"

# Set up environment
cp .env.example .env
# Edit .env: set KEYWAY_SECRET (required) and KEYWAY_ADMIN_TOKEN

# Run
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
