# 上游 Key 池与用户 Key 配额

[English](key-pool.md) | [中文](key-pool-zh.md)

---

Keyway 支持：多把上游 API Key 入池 → 聚合调度 → 再签发多把 `db_sk_` 给用户（可配配额）。形态参考 sub2api，但不做支付/计费平台。

## 架构

```
上游 Key（N） → Provider 凭证池 → 模型路由（alias）
                                    ↓
用户 Key（M × db_sk_）← 按组分发 + 配额/并发/RPM
```

- **凭证池**：同一 `base_url` / `protocol`，多把 Key
- **调度**：优先级 + 同级轮询；429 / 5xx / 传输错误换号
- **用户 Key**：原有 `db_sk_`，可选请求数 / Token / 并发 / RPM 上限

v1 不做：粘性会话、美元计费、支付、OAuth 订阅号、用户自助门户。

## 配置上游池

1. 照常创建 Provider（第一把 Key 成为 primary credential）
2. 管理界面 → Providers → **Keys**，继续添加上游 Key（标签 + 优先级）
3. 路由指向该 Provider（同模型池化用 `direct` 即可）

`auto-select` / `fusion` 仍负责选 **哪个 Provider**；池负责选 **该 Provider 用哪把 Key**。

## 签发用户 Key

在分组下创建 `db_sk_`，可选：

| 字段 | 作用 |
|---|---|
| `max_requests` | 请求次数硬上限 |
| `max_tokens` | Token 估算硬上限 |
| `concurrency_limit` | 进程内并发 |
| `rpm_limit` | 60 秒滑动窗口 |

超限返回 HTTP `429`。

## 与 sub2api 对比

| | Keyway v1 | sub2api |
|---|---|---|
| 上游 Key 池 | 有 | 有（账号池） |
| 用户 API Key | 有（`db_sk_`） | 有 |
| 故障切换 / 轮询 | 有 | 有（另含粘性） |
| 配额 | 请求/Token/并发/RPM | 更细窗口 + 美元 |
| 计费 / 支付 | 无 | 有 |
| OAuth 订阅号 | 无 | 有 |
