# 多 Provider 配置

[English](multi-provider-setup.md) | [中文](multi-provider-setup-zh.md)

---

本教程通过 Keyway 配置四个上游模型，然后在 Claude Code 中用 `/model` 命令自由切换。

## 第 1 步：添加四个 Provider

打开管理界面（`http://localhost:9233/`），进入"default"组，创建以下 Provider：

| Provider ID | 名称 | 协议 | Base URL | API Key 获取地址 |
|---|---|---|---|---|
| `deepseek` | DeepSeek | openai | `https://api.deepseek.com/v1` | https://platform.deepseek.com/ |
| `zhipu` | 智谱 GLM | openai | `https://open.bigmodel.cn/api/paas/v4` | https://open.bigmodel.cn/ |
| `minimax` | MiniMax | openai | `https://api.minimaxi.com/v1` | https://platform.minimaxi.com/ |
| `moonshot` | Moonshot (Kimi) | openai | `https://api.moonshot.cn/v1` | https://platform.moonshot.cn/ |

## 第 2 步：创建四条模型路由

在同一组中找到"Model Routes"，创建：

| Alias（客户端使用） | Provider | 上游模型 |
|---|---|---|
| `deepseek-v4-pro` | deepseek | `deepseek-chat` |
| `glm-5.2` | zhipu | `glm-4-plus` |
| `minimax-m3` | minimax | `MiniMax-M3` |
| `kimi-k2.7-code` | moonshot | `kimi-k2-0905-preview` |

> 模型 ID 更新频繁，配置前请到各家控制台核对确切的上游模型名。

## 第 3 步：创建 API Key

找到"Self-issued API Keys"，创建一个 Key（如命名为"claude-code"）。会得到 `db_sk_...` 明文，请妥善保存。

## 第 4 步：接入 Claude Code

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

## 第 5 步：用 `/model` 切换模型

四个路由配置好之后，你就可以**在 Claude Code 会话中随时切换**——无需重启、无需改配置：

```
/model deepseek-v4-pro
/model glm-5.2
/model minimax-m3
/model kimi-k2.7-code
```

设置里的 `ANTHROPIC_MODEL` 只是默认模型；`/model` 命令会在当前会话中覆盖它。四个 alias 都通过同一条 `db_sk_` key 和同一个 Keyway 服务路由。

## 第 6 步（可选）：用 CC Switch 管理配置档案

[CC Switch](https://github.com/farion1231/cc-switch) 是一个桌面 GUI，帮助你管理和组织 Claude Code 的配置档案。如果你有多个项目或多个环境（如不同的 Keyway 服务器、不同的默认模型），CC Switch 可以为每个 alias 预创建一个 profile，这样切换**默认**模型时无需手动编辑 `.claude/settings.local.json`：

| Profile | ANTHROPIC_MODEL |
|---|---|
| DeepSeek | `deepseek-v4-pro` |
| GLM | `glm-5.2` |
| MiniMax | `minimax-m3` |
| Kimi | `kimi-k2.7-code` |

所有 profile 共享同一个 `ANTHROPIC_BASE_URL` 和 `ANTHROPIC_AUTH_TOKEN`——只有 `ANTHROPIC_MODEL` 不同。注意 CC Switch 改的是 Claude Code 启动时的**默认**模型；会话中仍然可以用 `/model` 随时切换。

## 协议说明

本示例的四个 Provider 均为 OpenAI 协议，直接调用 API 时请用 OpenAI 端点（`/v1/chat/completions`）。Claude Code 走 Anthropic 端点（`/v1/messages`）——若要让 Claude Code 接入 OpenAI 协议上游，需添加一个 Anthropic 协议的 Provider（如 Anthropic 官方），然后用相同的 alias 创建路由。
