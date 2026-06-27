# Keyway

**A lightweight self-hosted LLM routing gateway with OpenAI & Anthropic dual-protocol support.**

[English](#english) | [中文](#中文)

---

<a id="english"></a>

## English

Keyway lets you route LLM requests from any OpenAI/Anthropic-compatible client (Claude Code, Cursor, OpenAI SDK, etc.) to multiple upstream providers (DeepSeek, OpenAI, Anthropic, Volcengine, Zhipu GLM, Qwen, and more) — all through a single self-issued `db_sk_` API key.

### Features

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

### Quick Start

#### Option 1: pip install

```bash
pip install keyway-router

# Generate a secret and create .env
python -c "import secrets; print('KEYWAY_SECRET=' + secrets.token_urlsafe(48))" > .env
echo "KEYWAY_ADMIN_TOKEN=my-admin-token" >> .env

# Run
keyway
# → Server starts on http://localhost:9233
```

#### Option 2: Docker

```bash
cd docker
cp .env.example .env
# Edit .env: set KEYWAY_SECRET and KEYWAY_ADMIN_TOKEN
docker compose up -d
# → Server at http://localhost:9233
```

#### Option 3: From source

```bash
git clone https://github.com/keyway-gateway/keyway.git
cd keyway
pip install -e ".[dev]"

cp .env.example .env
# Edit .env: set KEYWAY_SECRET (required) and KEYWAY_ADMIN_TOKEN

python -m keyway
```

### Configuration

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

### Usage Guide

#### 1. Access the admin UI

Open `http://localhost:9233/` in your browser. Log in with your `KEYWAY_ADMIN_TOKEN`.

#### 2. Add an upstream provider

In the "default" group, scroll to "Upstream Providers", fill in:
- **ID**: e.g. `deepseek`
- **Name**: e.g. `DeepSeek`
- **Protocol**: `openai` or `anthropic`
- **Base URL**: e.g. `https://api.deepseek.com/v1`
- **API Key**: your upstream provider key

#### 3. Create a model route

Scroll to "Model Routes", fill in:
- **Alias**: the name clients will use, e.g. `deepseek-v4-pro`
- **Provider**: select the provider you just created
- **Upstream Model**: the real model name at the provider, e.g. `deepseek-chat`

#### 4. Create an API key

Scroll to "Self-issued API Keys", create a key. The plaintext `db_sk_...` is shown once — save it. You can re-retrieve it later from the key list.

#### 5. Connect your client

##### Claude Code

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

##### OpenAI SDK (Python)

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

### Usage Example: Multi-Provider Setup

This example configures four upstream models through Keyway, then connects Claude Code with the [CC Switch](https://github.com/farion1231/cc-switch) helper to switch between them on the fly.

#### Step 1: Add four providers

Open the admin UI (`http://localhost:9233/`), go to the "default" group, and create these providers:

| Provider ID | Name | Protocol | Base URL | Where to get API Key |
|---|---|---|---|---|
| `deepseek` | DeepSeek | openai | `https://api.deepseek.com/v1` | https://platform.deepseek.com/ |
| `zhipu` | Zhipu GLM | openai | `https://open.bigmodel.cn/api/paas/v4` | https://open.bigmodel.cn/ |
| `minimax` | MiniMax | openai | `https://api.minimaxi.com/v1` | https://platform.minimaxi.com/ |
| `moonshot` | Moonshot (Kimi) | openai | `https://api.moonshot.cn/v1` | https://platform.moonshot.cn/ |

#### Step 2: Create four model routes

In the same group, go to "Model Routes" and create:

| Alias (client-facing) | Provider | Upstream Model |
|---|---|---|
| `deepseek-v4-pro` | deepseek | `deepseek-chat` |
| `glm-5.2` | zhipu | `glm-4-plus` |
| `minimax-m3` | minimax | `MiniMax-M3` |
| `kimi-k2.7-code` | moonshot | `kimi-k2-0905-preview` |

> Model IDs change frequently — verify the exact upstream model name on each provider's console.

#### Step 3: Create an API key

Go to "Self-issued API Keys", create a key (e.g. named "claude-code"). You'll get a `db_sk_...` plaintext. Save it.

#### Step 4: Connect Claude Code

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

Switch models in-session with `/model glm-5.2` or `/model kimi-k2.7-code`.

#### Step 5 (optional): Use CC Switch for model switching

[CC Switch](https://github.com/farion1231/cc-switch) is a desktop GUI for managing Claude Code model profiles. With Keyway, you can create a profile per alias — all pointing to the same `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN`, just changing `ANTHROPIC_MODEL`:

| Profile | ANTHROPIC_MODEL |
|---|---|
| DeepSeek | `deepseek-v4-pro` |
| GLM | `glm-5.2` |
| MiniMax | `minimax-m3` |
| Kimi | `kimi-k2.7-code` |

Switch between them with one click in CC Switch — no server restart, no key rotation.

#### Step 6: Verify with curl

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

### API Reference

#### Proxy endpoints (Bearer `db_sk_` auth)

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/chat/completions` | OpenAI-compatible chat completions (stream + non-stream) |
| `GET` | `/v1/models` | OpenAI-compatible model list (returns enabled route aliases) |
| `POST` | `/v1/messages` | Anthropic Messages-compatible (stream + non-stream) |
| `POST` | `/v1/messages/count_tokens` | Anthropic token count estimate |
| `POST` | `/v1/generations` | Generic generation forwarding (image/video/3D) |

#### Admin endpoints (`X-Admin-Token` header or session cookie)

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

### Development

```bash
pip install -e ".[dev]"
pytest -q
```

### Architecture

- **Backend**: FastAPI + uvicorn, 5 pip dependencies (`fastapi`, `uvicorn`, `httpx`, `cryptography`, `pydantic`)
- **Storage**: SQLite (single file, `keyway.db`) — no external database
- **Auth**: Admin token (single-admin) + self-issued `db_sk_` API keys (group-scoped)
- **Encryption**: Fernet (from `cryptography`) — SHA-256 of `KEYWAY_SECRET` derives the key
- **Frontend**: Zero-dependency vanilla JS, served by FastAPI's StaticFiles

---

<a id="中文"></a>

## 中文

Keyway 是一个轻量级的可自部署 LLM 路由网关，支持 OpenAI 和 Anthropic 双协议。通过一条自签发的 `db_sk_` API Key，即可将 Claude Code、Cursor、OpenAI SDK 等客户端的请求路由到多个上游提供商（DeepSeek、OpenAI、Anthropic、火山方舟、智谱 GLM、千问等）。

### 功能特性

- **双协议代理**：OpenAI `/v1/chat/completions` + Anthropic `/v1/messages` —— 开箱即用
- **模型别名**：将客户端可见的名称（如 `deepseek-v4-pro`）映射到任意上游模型
- **分组隔离**：Key 绑定到组；客户端持有的 Key 只能访问该组的 provider/route
- **自签发 API Key**：为团队生成 `db_sk_` Key；管理员可随时取回明文
- **加密存储**：所有上游 API Key 和自签发 Key 明文均使用 Fernet 加密
- **内置工具**：Tavily 网络搜索自动注入 OpenAI 工具调用循环
- **请求日志**：每次上游调用均记录状态码、延迟和 token 数
- **端到端测试**：一键探测所有已启用路由
- **生成式转发**：通过可配置的 `upstream_path` 支持图片/视频/3D 端点
- **零外部依赖**：仅需 Python + SQLite —— 无需数据库服务器、无需 Redis
- **Web 管理界面**：包含完整的图形化 CRUD 管理

### 快速开始

#### 方式一：pip 安装

```bash
pip install keyway-router

# 生成密钥并创建 .env
python -c "import secrets; print('KEYWAY_SECRET=' + secrets.token_urlsafe(48))" > .env
echo "KEYWAY_ADMIN_TOKEN=my-admin-token" >> .env

# 启动
keyway
# → 服务启动在 http://localhost:9233
```

#### 方式二：Docker

```bash
cd docker
cp .env.example .env
# 编辑 .env：设置 KEYWAY_SECRET 和 KEYWAY_ADMIN_TOKEN
docker compose up -d
# → 服务在 http://localhost:9233
```

#### 方式三：从源码运行

```bash
git clone https://github.com/keyway-gateway/keyway.git
cd keyway
pip install -e ".[dev]"

cp .env.example .env
# 编辑 .env：设置 KEYWAY_SECRET（必填）和 KEYWAY_ADMIN_TOKEN

python -m keyway
```

### 配置项

所有配置通过环境变量（或 `.env` 文件）设置：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `KEYWAY_SECRET` | *(必填)* | Fernet 加密密钥，用于加密存储的秘密。用 `python -c "import secrets; print(secrets.token_urlsafe(48))"` 生成 |
| `KEYWAY_ADMIN_TOKEN` | *(自动生成)* | 管理界面 token。留空则启动时随机生成并打印到控制台 |
| `KEYWAY_HOST` | `127.0.0.1` | 监听地址 |
| `KEYWAY_PORT` | `9233` | 监听端口 |
| `KEYWAY_DATA_DIR` | `./data` | SQLite 数据库存放目录 |
| `KEYWAY_CORS_ORIGINS` | `http://127.0.0.1:9233,...` | CORS 允许的来源 |
| `KEYWAY_PUBLIC_BASE_URL` | *(自动推断)* | 管理界面中显示给用户的 Base URL |
| `KEYWAY_LOG_LEVEL` | `info` | 日志级别 |

### 使用指南

#### 1. 打开管理界面

浏览器访问 `http://localhost:9233/`，输入 `KEYWAY_ADMIN_TOKEN` 登录。

#### 2. 添加上游 Provider

在"default"组中，找到"Upstream Providers"，填写：
- **ID**：如 `deepseek`
- **名称**：如 `DeepSeek`
- **协议**：`openai` 或 `anthropic`
- **Base URL**：如 `https://api.deepseek.com/v1`
- **API Key**：你的上游提供商密钥

#### 3. 创建模型路由

找到"Model Routes"，填写：
- **Alias**：客户端使用的名称，如 `deepseek-v4-pro`
- **Provider**：选择刚创建的 provider
- **Upstream Model**：上游真实模型名，如 `deepseek-chat`

#### 4. 创建 API Key

找到"Self-issued API Keys"，创建 Key。明文 `db_sk_...` 仅显示一次——请妥善保存。管理员可随时从列表重新获取明文。

#### 5. 连接客户端

##### Claude Code

在项目根目录创建 `.claude/settings.local.json`：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:9233",
    "ANTHROPIC_AUTH_TOKEN": "db_sk_你的key",
    "ANTHROPIC_MODEL": "deepseek-v4-pro",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-v4-pro",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "deepseek-v4-pro",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "deepseek-v4-pro"
  }
}
```

##### OpenAI SDK（Python）

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:9233/v1",
    api_key="db_sk_你的key",
)

resp = client.chat.completions.create(
    model="deepseek-v4-pro",
    messages=[{"role": "user", "content": "你好！"}],
)
```

### 使用示例：多模型配置

本示例通过 Keyway 配置四个上游模型，然后用 Claude Code 配合 [CC Switch](https://github.com/farion1231/cc-switch) 辅助工具实现一键切换。

#### 第 1 步：添加四个 Provider

打开管理界面（`http://localhost:9233/`），进入"default"组，创建以下 Provider：

| Provider ID | 名称 | 协议 | Base URL | API Key 获取地址 |
|---|---|---|---|---|
| `deepseek` | DeepSeek | openai | `https://api.deepseek.com/v1` | https://platform.deepseek.com/ |
| `zhipu` | 智谱 GLM | openai | `https://open.bigmodel.cn/api/paas/v4` | https://open.bigmodel.cn/ |
| `minimax` | MiniMax | openai | `https://api.minimaxi.com/v1` | https://platform.minimaxi.com/ |
| `moonshot` | Moonshot (Kimi) | openai | `https://api.moonshot.cn/v1` | https://platform.moonshot.cn/ |

#### 第 2 步：创建四条模型路由

在同一组中找到"Model Routes"，创建：

| Alias（客户端使用） | Provider | 上游模型 |
|---|---|---|
| `deepseek-v4-pro` | deepseek | `deepseek-chat` |
| `glm-5.2` | zhipu | `glm-4-plus` |
| `minimax-m3` | minimax | `MiniMax-M3` |
| `kimi-k2.7-code` | moonshot | `kimi-k2-0905-preview` |

> 模型 ID 更新频繁，配置前请到各家控制台核对确切的上游模型名。

#### 第 3 步：创建 API Key

找到"Self-issued API Keys"，创建一个 Key（如命名为"claude-code"）。会得到 `db_sk_...` 明文，请妥善保存。

#### 第 4 步：接入 Claude Code

在项目根目录创建 `.claude/settings.local.json`（记得加入 `.gitignore`！）：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:9233",
    "ANTHROPIC_AUTH_TOKEN": "db_sk_你的key",
    "ANTHROPIC_MODEL": "deepseek-v4-pro",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "deepseek-v4-pro",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "deepseek-v4-pro",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "deepseek-v4-pro"
  }
}
```

> **本地 Base URL 说明**：
> - **Anthropic SDK / Claude Code**：`http://localhost:9233`（不带末尾斜杠；SDK 自动拼 `/v1/messages`）
> - **OpenAI SDK**：`http://localhost:9233/v1`（SDK 自动拼 `/chat/completions`）

在会话中用 `/model glm-5.2` 或 `/model kimi-k2.7-code` 切换模型。

#### 第 5 步（可选）：用 CC Switch 辅助切换

[CC Switch](https://github.com/farion1231/cc-switch) 是一个管理 Claude Code 模型配置的桌面 GUI。配合 Keyway，可以为每个 alias 创建一个 profile——都指向同一个 `ANTHROPIC_BASE_URL` 和 `ANTHROPIC_AUTH_TOKEN`，只需改 `ANTHROPIC_MODEL`：

| Profile | ANTHROPIC_MODEL |
|---|---|
| DeepSeek | `deepseek-v4-pro` |
| GLM | `glm-5.2` |
| MiniMax | `minimax-m3` |
| Kimi | `kimi-k2.7-code` |

在 CC Switch 中一键切换——无需重启服务、无需轮换 Key。

#### 第 6 步：用 curl 验证

```bash
# OpenAI 协议
curl http://localhost:9233/v1/chat/completions \
  -H "Authorization: Bearer db_sk_你的key" \
  -H "Content-Type: application/json" \
  -d '{"model":"glm-5.2","messages":[{"role":"user","content":"你好！"}],"max_tokens":16}'

# Anthropic 协议（仅限 Anthropic 协议的上游）
curl http://localhost:9233/v1/messages \
  -H "Authorization: Bearer db_sk_你的key" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-pro","messages":[{"role":"user","content":"你好！"}],"max_tokens":16}'
```

> **协议说明**：OpenAI 协议客户端（`/v1/chat/completions`）需要 OpenAI 协议的 Provider；Anthropic 协议客户端（`/v1/messages`）需要 Anthropic 协议的 Provider。本示例的四个 Provider 均为 OpenAI 协议，直接调用 API 时请用 OpenAI 端点（`/v1/chat/completions`）。Claude Code 走 Anthropic 端点（`/v1/messages`）——若要让 Claude Code 接入 OpenAI 协议上游，需添加一个 Anthropic 协议的 Provider（如 Anthropic 官方），然后用相同的 alias 创建路由。

### API 参考

#### 代理端点（Bearer `db_sk_` 鉴权）

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/chat/completions` | OpenAI 兼容聊天补全（流式 + 非流式） |
| `GET` | `/v1/models` | OpenAI 兼容模型列表（返回已启用的路由 alias） |
| `POST` | `/v1/messages` | Anthropic Messages 兼容（流式 + 非流式） |
| `POST` | `/v1/messages/count_tokens` | Anthropic token 计数估算 |
| `POST` | `/v1/generations` | 通用生成转发（图片/视频/3D） |

#### 管理端点（`X-Admin-Token` 头或 session cookie）

| Method | Path | Description |
|---|---|---|
| `POST` | `/admin/login` | 管理员 token 登录 → session cookie |
| `GET` | `/admin/session` | 验证会话 |
| `POST` | `/admin/logout` | 登出 |
| `GET` | `/admin/config` | 运行时配置（Base URL） |
| `GET/POST` | `/admin/llm/groups` | 列出/创建组 |
| `GET/PATCH/DELETE` | `/admin/llm/groups/{id}` | 查看/更新/删除组 |
| `POST` | `/admin/llm/groups/{id}/copy` | 深拷贝组（重新签发新 key） |
| `GET/POST` | `/admin/llm/groups/{id}/providers` | 列出/创建组内 Provider |
| `GET/PATCH/DELETE` | `/admin/llm/providers/{id}` | 查看/更新/删除 Provider |
| `GET/POST` | `/admin/llm/groups/{id}/routes` | 列出/创建组内路由 |
| `GET/PATCH/DELETE` | `/admin/llm/routes/{id}` | 查看/更新/删除路由 |
| `GET/POST` | `/admin/llm/groups/{id}/keys` | 列出/创建组内 API Key |
| `GET` | `/admin/llm/keys/{id}/plaintext` | 取回 Key 明文（仅管理员） |
| `PATCH/DELETE` | `/admin/llm/keys/{id}` | 更新/删除 API Key |
| `GET/POST` | `/admin/llm/groups/{id}/tool-providers` | 列出/创建工具 Provider |
| `PATCH/DELETE` | `/admin/llm/tool-providers/{id}` | 更新/删除工具 Provider |
| `GET` | `/admin/llm/logs` | 请求日志（按 api_key_id、group_id 过滤） |
| `GET` | `/admin/llm/stats` | 指定 Key 的统计 |
| `POST` | `/admin/llm/test` | 探测单个 Provider 或路由 |
| `POST` | `/admin/llm/e2e` | 所有已启用路由的端到端测试 |

### 开发

```bash
pip install -e ".[dev]"
pytest -q
```

### 架构

- **后端**：FastAPI + uvicorn，5 个 pip 依赖（`fastapi`、`uvicorn`、`httpx`、`cryptography`、`pydantic`）
- **存储**：SQLite（单文件 `keyway.db`）—— 无外部数据库
- **鉴权**：管理员 token（单管理员）+ 自签发 `db_sk_` API Key（分组隔离）
- **加密**：Fernet（来自 `cryptography`）—— 用 `KEYWAY_SECRET` 的 SHA-256 派生密钥
- **前端**：零依赖原生 JS，由 FastAPI StaticFiles 提供服务

## License

MIT — see [LICENSE](LICENSE).
