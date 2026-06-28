# 入门指南

[English](getting-started.md) | [中文](getting-started-zh.md)

---

## 配置项

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

## 第 1 步：打开管理界面

浏览器访问 `http://localhost:9233/`，输入 `KEYWAY_ADMIN_TOKEN` 登录。

## 第 2 步：添加上游 Provider

在"default"组中，找到"Upstream Providers"，填写：
- **ID**：如 `deepseek`
- **名称**：如 `DeepSeek`
- **协议**：`openai` 或 `anthropic`
- **Base URL**：如 `https://api.deepseek.com/v1`
- **API Key**：你的上游提供商密钥

## 第 3 步：创建模型路由

找到"Model Routes"，填写：
- **Alias**：客户端使用的名称，如 `deepseek-v4-pro`
- **Provider**：选择刚创建的 provider
- **Upstream Model**：上游真实模型名，如 `deepseek-chat`

## 第 4 步：创建 API Key

找到"Self-issued API Keys"，创建 Key。明文 `db_sk_...` 仅显示一次——请妥善保存。管理员可随时从列表重新获取明文。

## 第 5 步：连接客户端

### Claude Code

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

### OpenAI SDK（Python）

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

> **本地 Base URL 说明**：
> - **Anthropic SDK / Claude Code**：`http://localhost:9233`（不带末尾斜杠；SDK 自动拼 `/v1/messages`）
> - **OpenAI SDK**：`http://localhost:9233/v1`（SDK 自动拼 `/chat/completions`）

## 用 curl 验证

```bash
# OpenAI 协议
curl http://localhost:9233/v1/chat/completions \
  -H "Authorization: Bearer db_sk_你的key" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-pro","messages":[{"role":"user","content":"你好！"}],"max_tokens":16}'

# Anthropic 协议（仅限 Anthropic 协议的上游）
curl http://localhost:9233/v1/messages \
  -H "Authorization: Bearer db_sk_你的key" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4-pro","messages":[{"role":"user","content":"你好！"}],"max_tokens":16}'
```

> **协议说明**：OpenAI 协议客户端（`/v1/chat/completions`）需要 OpenAI 协议的 Provider；Anthropic 协议客户端（`/v1/messages`）需要 Anthropic 协议的 Provider。
