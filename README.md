# Keyway

**A lightweight self-hosted LLM routing gateway with OpenAI & Anthropic dual-protocol support.**

[English](README.md) | [中文](README-zh.md)

---

Keyway routes LLM requests from any OpenAI/Anthropic-compatible client (Claude Code, Cursor, OpenAI SDK, etc.) to multiple upstream providers — all through a single self-issued `db_sk_` API key.

## Quick Start

### pip

```bash
pip install keyway-router

# Generate a secret and create .env
python -c "import secrets; print('KEYWAY_SECRET=' + secrets.token_urlsafe(48))" > .env
echo "KEYWAY_ADMIN_TOKEN=my-admin-token" >> .env

# Run
keyway
# → http://localhost:9233
```

### Docker

```bash
cd docker
cp .env.example .env   # edit: set KEYWAY_SECRET and KEYWAY_ADMIN_TOKEN
docker compose up -d
# → http://localhost:9233
```

### From source

```bash
git clone https://github.com/DeconBear/keyway.git
cd keyway
pip install -e ".[dev]"
cp .env.example .env   # edit: set KEYWAY_SECRET (required) and KEYWAY_ADMIN_TOKEN
python -m keyway
```

## Next Steps

- **First-time setup** (add providers, routes, keys): see [Getting Started](tutorial/getting-started.md)
- **Multi-provider + Claude Code walkthrough**: see [Multi-Provider Setup](tutorial/multi-provider-setup.md)
- **Auto-select, adapter, fusion modes**: see [Multi-Mode Processing](tutorial/multi-mode-processing.md)
- **Full API reference**: see [API Reference](tutorial/api-reference.md)
- **Architecture & development**: see [Architecture](tutorial/architecture.md)

## License

MIT — see [LICENSE](LICENSE).
