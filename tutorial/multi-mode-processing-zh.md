# 多模式处理

[English](multi-mode-processing.md) | [中文](multi-mode-processing-zh.md)

---

Keyway 支持四种处理模式，全部通过 `/v1/chat/completions` 和 `/v1/messages` 端点统一分发。模式通过路由的 `mode` 字段设置（默认：`direct`）。

| 模式 | 用途 |
|---|---|
| `direct` | 别名 → 单一提供商 → 转发（默认） |
| `auto-select` | 按优先级尝试多个提供商；5xx/超时自动故障转移；熔断器保护 |
| `adapter` | 检测请求中的图像，通过视觉模型生成描述，转发纯文本请求 |
| `fusion` | 并行调度多个提供商，评审模型合成最终答案 |

---

## Direct 模式（默认）

无需特殊配置。这是标准的单提供商直通模式。所有已有路由默认为 `direct` —— 升级后行为不变。

---

## Auto-Select 模式

不将别名绑定到单一提供商，而是解析到多个候选提供商并按优先级依次尝试。如果提供商返回可重试错误（5xx、超时），Keyway 自动切换到下一个候选。

### 配置

1. 创建路由时设置 `mode = "auto-select"`。
2. 通过 **route-providers** 管理 API（或管理界面）为路由添加多个提供商。
3. 为每个关联设置 `priority` —— 数字越小越优先。

```bash
# 创建路由（主提供商作为兜底）
curl -X POST http://localhost:9233/admin/llm/groups/default/routes \
  -H "X-Admin-Token: my-admin-token" \
  -H "Content-Type: application/json" \
  -d '{"alias":"smart","provider_id":"p1","upstream_model":"m1","mode":"auto-select"}'

# 添加第二个提供商，优先级为 1
curl -X POST http://localhost:9233/admin/llm/routes/{route_id}/providers \
  -H "X-Admin-Token: my-admin-token" \
  -H "Content-Type: application/json" \
  -d '{"provider_id":"p2","upstream_model":"m2","priority":1}'
```

### 熔断器

每个提供商都有健康记录。**连续失败 3 次**后熔断器开启，该提供商在 **60 秒**内被跳过。成功后熔断器重置。

- 5xx 错误和超时 → 计为失败，触发故障转移
- 4xx 错误 → 不可重试，直接返回客户端（不故障转移）

通过管理 API 管理熔断器：

```bash
# 查看所有提供商健康状态
curl http://localhost:9233/admin/llm/health -H "X-Admin-Token: my-admin-token"

# 重置提供商熔断器
curl -X POST http://localhost:9233/admin/llm/health/p1/reset \
  -H "X-Admin-Token: my-admin-token"
```

### 流式

Auto-select 流式选择优先级最高的健康候选。流式传输过程中不支持故障转移（一旦开始发送数据，流即已提交）。

---

## Adapter 模式

Adapter 模式让**纯文本模型**能处理包含图像的请求。Keyway 检测图像内容，调用单独的视觉模型路由生成文字描述，将图像替换为 `[Image: <description>]` 后再转发。

### 配置

1. 创建一个视觉能力路由（如 alias `qwen-vl` → 视觉模型）。
2. 创建文本路由，设置 `mode = "adapter"`，配置 `adapter_config`：

```json
{
  "vision_alias": "qwen-vl",
  "fallback": "skip-image"
}
```

| 配置字段 | 说明 |
|---|---|
| `vision_alias` | 指向视觉模型的路由别名（图像适配必需） |
| `fallback` | `"skip-image"` — 视觉模型失败时用占位符替换图像；`"error"` — 传播错误（默认） |

### 行为

- **不含**图像的请求原样通过（零开销）。
- **含**图像的请求：每个图像块发送给视觉模型，描述以文本注入，修改后的请求再转发给文本模型。
- 兼容 OpenAI 风格（`image_url`）和 Anthropic 风格（`image` + `source`）的内容块。

---

## Fusion 模式

Fusion 模式将请求**并行调度到所有候选提供商**，收集响应后发送给**评审模型**合成最终答案。适用于对质量要求高的场景。

### 配置

1. 创建候选提供商并关联到路由（与 auto-select 相同）。
2. 创建单独的评审路由（如 alias `judge` → 强模型）。
3. 创建路由，设置 `mode = "fusion"`，配置 `fusion_config`：

```json
{
  "judge_alias": "judge",
  "strategy": "compare_and_synthesize",
  "min_candidates": 2,
  "timeout_seconds": 30
}
```

| 配置字段 | 默认值 | 说明 |
|---|---|---|
| `judge_alias` | *(必填)* | 指向评审模型的路由别名 |
| `strategy` | `compare_and_synthesize` | 评审策略（见下） |
| `min_candidates` | `2` | 最少健康候选数 |
| `timeout_seconds` | `30` | 单候选超时时间 |

### 评审策略

| 策略 | 说明 |
|---|---|
| `compare_and_synthesize` | 评审从每个候选中挑选最佳部分，合成综合答案 |
| `majority_vote` | 评审识别共识答案（适合事实性问答） |
| `ranked` | 评审对所有响应排序，原样返回最佳答案 |

### 行为

- 所有候选并行调用（`asyncio.gather`）。部分失败可容忍 —— 评审只处理成功的响应。
- 成功候选少于 `min_candidates` 时请求失败。
- Fusion 模式**不支持流式** —— 客户端需等待所有候选 + 评审完成。
- 每次 fusion 请求记录 N+1 条日志到 `llm_request_logs`，通过共享的 `fusion_id` 分组。
- 响应包含 `X-Keyway-Fusion`（逗号分隔的提供商列表）和 `X-Keyway-Fusion-Id` 头。

---

## Route Providers 管理 API

除 `direct` 外的所有模式都使用 `route_providers` 表将多个提供商关联到路由：

| Method | Path | 说明 |
|---|---|---|
| `GET` | `/admin/llm/routes/{route_id}/providers` | 列出提供商关联 |
| `POST` | `/admin/llm/routes/{route_id}/providers` | 添加提供商（带优先级） |
| `PATCH` | `/admin/llm/route-providers/{rp_id}` | 更新优先级/启用/上游模型 |
| `DELETE` | `/admin/llm/route-providers/{rp_id}` | 移除提供商关联 |
| `GET` | `/admin/llm/health` | 查看提供商熔断器状态 |
| `POST` | `/admin/llm/health/{provider_id}/reset` | 重置提供商熔断器 |

## 向后兼容

- 所有已有路由默认 `mode = "direct"` —— 升级后行为不变。
- `mode` 列通过 `_ensure_column()` 添加，对已有数据库是 no-op。
- `route_providers` 仅在 `mode != "direct"` 时被查询。
- 所有新端点均为新增 —— 不改变任何已有端点。
