# Getting Started

[English](getting-started.md) | [中文](getting-started-zh.md)

---

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

## Step 1: Access the admin UI

Open `http://localhost:9233/` in your browser. Log in with your `KEYWAY_ADMIN_TOKEN`.

## Step 2: Add an upstream provider

In the "default" group, scroll to "Upstream Providers", fill in:
- **ID**: e.g. `deepseek`
- **Name**: e.g. `DeepSeek`
- **Protocol**: `openai` or `anthropic`
- **Base URL**: e.g. `https://api.deepseek.com/v1`
- **API Key**: your upstream provider key

## Step 3: Create a model route

Scroll to "Model Routes", fill in:
- **Alias**: the name clients will use, e.g. `deepseek-v4-pro`
- **Provider**: select the provider you just created
- **Upstream Model**: the real model name at the provider, e.g. `deepseek-chat`

## Step 4: Create an API key

Scroll to "Self-issued API Keys", create a key. The plaintext `db_sk_...` is shown once — save it. You can re-retrieve it later from the key list.

## Step 5: Connect your client

### Claude Code

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

### OpenAI SDK (Python)

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

> **Base URL rules** (local):
> - **Anthropic SDK / Claude Code**: `http://localhost:9233` (no trailing slash; SDK auto-appends `/v1/messages`)
> - **OpenAI SDK**: `http://localhost:9233/v1` (SDK appends `/chat/completions`)

## Verify with curl

```bash
# OpenAI protocol
curl http://localhost:9233/v1/chat/completions \
  -H "Authorization: Bearer db_sk_your-key" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-pro","messages":[{"role":"user","content":"Hello!"}],"max_tokens":16}'

# Anthropic protocol (for Anthropic-protocol upstreams only)
curl http://localhost:9233/v1/messages \
  -H "Authorization: Bearer db_sk_your-key" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-pro","messages":[{"role":"user","content":"Hello!"}],"max_tokens":16}'
```

> **Protocol note**: OpenAI-protocol clients (`/v1/chat/completions`) require OpenAI-protocol providers. Anthropic-protocol clients (`/v1/messages`) require Anthropic-protocol providers.
