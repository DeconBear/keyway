# API 参考

[English](api-reference.md) | [中文](api-reference-zh.md)

---

## 代理端点（Bearer `db_sk_` 鉴权）

| Method | Path | 说明 |
|---|---|---|
| `POST` | `/v1/chat/completions` | OpenAI 兼容聊天补全（流式 + 非流式） |
| `GET` | `/v1/models` | OpenAI 兼容模型列表（返回已启用的路由 alias） |
| `POST` | `/v1/messages` | Anthropic Messages 兼容（流式 + 非流式） |
| `POST` | `/v1/messages/count_tokens` | Anthropic token 计数估算 |
| `POST` | `/v1/generations` | 通用生成转发（图片/视频/3D） |

所有代理端点需要 `Authorization: Bearer db_sk_...` 头。Key 必须已启用且未过期。

## 管理端点（`X-Admin-Token` 头或 session cookie）

### 鉴权

| Method | Path | 说明 |
|---|---|---|
| `POST` | `/admin/login` | 管理员 token 登录 → session cookie |
| `GET` | `/admin/session` | 验证会话 |
| `POST` | `/admin/logout` | 登出 |
| `GET` | `/admin/config` | 运行时配置（Base URL） |

### 分组

| Method | Path | 说明 |
|---|---|---|
| `GET/POST` | `/admin/llm/groups` | 列出/创建组 |
| `GET/PATCH/DELETE` | `/admin/llm/groups/{id}` | 查看/更新/删除组 |
| `POST` | `/admin/llm/groups/{id}/copy` | 深拷贝组（重新签发新 key） |

### Provider

| Method | Path | 说明 |
|---|---|---|
| `GET/POST` | `/admin/llm/groups/{id}/providers` | 列出/创建组内 Provider |
| `GET/PATCH/DELETE` | `/admin/llm/providers/{id}` | 查看/更新/删除 Provider |

### 路由

| Method | Path | 说明 |
|---|---|---|
| `GET/POST` | `/admin/llm/groups/{id}/routes` | 列出/创建组内路由 |
| `GET/PATCH/DELETE` | `/admin/llm/routes/{id}` | 查看/更新/删除路由 |

路由创建/更新接受 `mode`（`direct`、`auto-select`、`adapter`、`fusion`）、`adapter_config`（JSON 字符串）和 `fusion_config`（JSON 字符串）。

### Route Providers（多提供商关联）

| Method | Path | 说明 |
|---|---|---|
| `GET` | `/admin/llm/routes/{route_id}/providers` | 列出路由的提供商关联 |
| `POST` | `/admin/llm/routes/{route_id}/providers` | 为路由添加提供商（带优先级） |
| `PATCH` | `/admin/llm/route-providers/{rp_id}` | 更新优先级/启用/上游模型 |
| `DELETE` | `/admin/llm/route-providers/{rp_id}` | 移除路由的提供商关联 |

### Provider Health（熔断器）

| Method | Path | 说明 |
|---|---|---|
| `GET` | `/admin/llm/health` | Provider 健康概览（可选 `?group_id=` 过滤） |
| `POST` | `/admin/llm/health/{provider_id}/reset` | 手动重置熔断器 |

### API Key

| Method | Path | 说明 |
|---|---|---|
| `GET/POST` | `/admin/llm/groups/{id}/keys` | 列出/创建组内 API Key |
| `GET` | `/admin/llm/keys/{id}/plaintext` | 取回 Key 明文（仅管理员） |
| `PATCH/DELETE` | `/admin/llm/keys/{id}` | 更新/删除 API Key |

### 工具 Provider

| Method | Path | 说明 |
|---|---|---|
| `GET/POST` | `/admin/llm/groups/{id}/tool-providers` | 列出/创建工具 Provider |
| `PATCH/DELETE` | `/admin/llm/tool-providers/{id}` | 更新/删除工具 Provider |

### 日志与测试

| Method | Path | 说明 |
|---|---|---|
| `GET` | `/admin/llm/logs` | 请求日志（按 `?api_key_id=`、`?group_id=` 过滤） |
| `GET` | `/admin/llm/stats` | 指定 Key 的统计 |
| `POST` | `/admin/llm/test` | 探测单个 Provider 或路由 |
| `POST` | `/admin/llm/e2e` | 所有已启用路由的端到端测试 |
