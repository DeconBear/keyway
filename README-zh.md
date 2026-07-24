# Keyway

**一个轻量级的可自部署 LLM 路由网关，支持 OpenAI 和 Anthropic 双协议。**

[English](README.md) | [中文](README-zh.md)

---

Keyway 通过一条自签发的 `db_sk_` API Key，即可将 Claude Code、Cursor、OpenAI SDK 等客户端的请求路由到多个上游提供商。

## 快速开始

### pip 安装

```bash
pip install keyway-router

# 生成密钥并创建 .env
python -c "import secrets; print('KEYWAY_SECRET=' + secrets.token_urlsafe(48))" > .env
echo "KEYWAY_ADMIN_TOKEN=my-admin-token" >> .env

# 启动
keyway
# → http://localhost:9233
```

### Docker

```bash
cd docker
cp .env.example .env   # 编辑：设置 KEYWAY_SECRET 和 KEYWAY_ADMIN_TOKEN
docker compose up -d
# → http://localhost:9233
```

### 从源码运行

```bash
git clone https://github.com/DeconBear/keyway.git
cd keyway
pip install -e ".[dev]"
cp .env.example .env   # 编辑：设置 KEYWAY_SECRET（必填）和 KEYWAY_ADMIN_TOKEN
python -m keyway
```

### 桌面端（Windows）

```bash
pip install -e ".[dev]"
pip install -r keyway-desktop/requirements.txt
python keyway-desktop/main.py
# 或：cd keyway-desktop && pyinstaller Keyway.spec  → dist/Keyway.exe
```

数据与密钥保存在 `%APPDATA%\Keyway`。详见 [keyway-desktop/README.md](keyway-desktop/README.md)。

## 后续教程

文档站：https://deconbear.github.io/keyway/

- **首次配置**（添加 Provider、路由、Key）：[入门指南](tutorial/getting-started-zh.md)
- **多模型 + Claude Code 实战**：[多 Provider 配置](tutorial/multi-provider-setup-zh.md)
- **自动选择、适配器、融合模式**：[多模式处理](tutorial/multi-mode-processing-zh.md)
- **上游 Key 池 + 用户配额**：[Key 池方案](tutorial/key-pool-zh.md)
- **完整 API 参考**：[API 参考](tutorial/api-reference-zh.md)
- **架构与开发**：[架构说明](tutorial/architecture-zh.md)

## License

MIT — see [LICENSE](LICENSE).
