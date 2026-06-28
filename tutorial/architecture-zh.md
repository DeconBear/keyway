# 架构说明

[English](architecture.md) | [中文](architecture-zh.md)

---

## 技术栈

- **后端**：FastAPI + uvicorn，5 个 pip 依赖（`fastapi`、`uvicorn`、`httpx`、`cryptography`、`pydantic`）
- **存储**：SQLite（单文件 `keyway.db`）—— 无外部数据库
- **鉴权**：管理员 token（单管理员）+ 自签发 `db_sk_` API Key（分组隔离）
- **加密**：Fernet（来自 `cryptography`）—— 用 `KEYWAY_SECRET` 的 SHA-256 派生密钥
- **前端**：零依赖原生 JS，由 FastAPI StaticFiles 提供服务

## 项目结构

```
src/keyway/
├── __init__.py          # 版本号
├── __main__.py          # CLI 入口（uvicorn 启动器）
├── app.py               # FastAPI 应用：端点、鉴权、请求分发
├── config.py            # 从环境变量读取配置
├── crypto.py            # Fernet 加密辅助
├── llm_keys.py          # db_sk_ key 生成、哈希、前缀
├── llm_protocol.py      # 协议检测辅助
├── llm_router.py        # LLMRouter：解析、流式、完成、auto-select、探测
├── llm_store.py         # LLMStore：SQLite CRUD（8 张表）
├── llm_tools.py         # 内置工具（Tavily 搜索）
├── models.py            # Pydantic 请求模型
├── modality.py          # ModalityDetector（图像/工具检测）
├── adapters.py          # AdapterPipeline, ImageDescriber
├── fusion.py            # FusionOrchestrator, 评审策略
└── web/                 # 管理界面（静态 HTML/JS/CSS）
```

## 数据库 Schema

8 张 SQLite 表：

| 表 | 用途 |
|---|---|
| `llm_groups` | 路由分组（隔离边界） |
| `llm_providers` | 上游 LLM 提供商（base_url, api_key, protocol） |
| `model_routes` | 别名 → 提供商绑定（含 mode, adapter_config, fusion_config） |
| `route_providers` | auto-select/fusion 的多提供商关联（带优先级） |
| `provider_health` | 熔断器状态（consecutive_fails, circuit_open） |
| `llm_api_keys` | 自签发 db_sk_ key（分组隔离，加密明文） |
| `llm_tool_providers` | 工具提供商（如 Tavily） |
| `llm_request_logs` | 请求日志（含 fusion_id 用于 fusion 分组） |

## 请求流程

```
Client (Bearer db_sk_...)
  │ POST /v1/chat/completions  或  /v1/messages
  ▼
app.py: 按 alias + group 解析路由
  │ route.mode → 分发
  │
  ├─ direct:     router.complete() / router.stream()
  ├─ auto-select: router.resolve_route_auto() → 按序尝试候选
  ├─ adapter:    AdapterPipeline.adapt() → 然后 direct
  └─ fusion:     FusionOrchestrator.fuse() → 并行 + 评审
  ▼
上游 Provider(s)
```

## 开发

```bash
pip install -e ".[dev]"
pytest -q
```
