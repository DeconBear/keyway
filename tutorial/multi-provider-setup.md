# Multi-Provider Setup

[English](multi-provider-setup.md) | [中文](multi-provider-setup-zh.md)

---

This walkthrough configures four upstream models through Keyway, then connects Claude Code to switch between them using the `/model` command.

## Step 1: Add four providers

Open the admin UI (`http://localhost:9233/`), go to the "default" group, and create these providers:

| Provider ID | Name | Protocol | Base URL | Where to get API Key |
|---|---|---|---|---|
| `deepseek` | DeepSeek | openai | `https://api.deepseek.com/v1` | https://platform.deepseek.com/ |
| `zhipu` | Zhipu GLM | openai | `https://open.bigmodel.cn/api/paas/v4` | https://open.bigmodel.cn/ |
| `minimax` | MiniMax | openai | `https://api.minimaxi.com/v1` | https://platform.minimaxi.com/ |
| `moonshot` | Moonshot (Kimi) | openai | `https://api.moonshot.cn/v1` | https://platform.moonshot.cn/ |

## Step 2: Create four model routes

In the same group, go to "Model Routes" and create:

| Alias (client-facing) | Provider | Upstream Model |
|---|---|---|
| `deepseek-v4-pro` | deepseek | `deepseek-chat` |
| `glm-5.2` | zhipu | `glm-4-plus` |
| `minimax-m3` | minimax | `MiniMax-M3` |
| `kimi-k2.7-code` | moonshot | `kimi-k2-0905-preview` |

> Model IDs change frequently — verify the exact upstream model name on each provider's console.

## Step 3: Create an API key

Go to "Self-issued API Keys", create a key (e.g. named "claude-code"). You'll get a `db_sk_...` plaintext. Save it.

## Step 4: Connect Claude Code

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

## Step 5: Switch models with `/model`

Once the four routes are configured, you can switch between them **directly inside Claude Code** at any time — no restart, no config change:

```
/model deepseek-v4-pro
/model glm-5.2
/model minimax-m3
/model kimi-k2.7-code
```

The `ANTHROPIC_MODEL` in your settings is just the default; `/model` overrides it for the current session. All four aliases route through the same `db_sk_` key and the same Keyway server.

## Step 6 (optional): Use CC Switch for profile management

[CC Switch](https://github.com/farion1231/cc-switch) is a desktop GUI that helps you manage and organize Claude Code configuration profiles. If you maintain multiple projects or environments (e.g. different Keyway servers, different default models), CC Switch lets you pre-create a profile per alias so you can switch the **default** model without editing `.claude/settings.local.json` by hand:

| Profile | ANTHROPIC_MODEL |
|---|---|
| DeepSeek | `deepseek-v4-pro` |
| GLM | `glm-5.2` |
| MiniMax | `minimax-m3` |
| Kimi | `kimi-k2.7-code` |

All profiles share the same `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN` — only `ANTHROPIC_MODEL` differs. Note that CC Switch changes the **default** model that Claude Code starts with; you can still use `/model` in-session to switch on the fly.

## Protocol note

All four providers in this example use OpenAI protocol, so use the OpenAI endpoint (`/v1/chat/completions`) for direct API calls. Claude Code uses the Anthropic endpoint (`/v1/messages`) — to use Claude Code with OpenAI-protocol upstreams, add an Anthropic-protocol provider (e.g. Anthropic itself) and create routes with the same aliases.
