/**
 * Keyway UI i18n — default English, optional Chinese (zh).
 * Usage: t('key'), applyI18n(root), setLanguage('zh')
 */
(function (global) {
  const STORAGE_KEY = "keyway_lang";

  const STRINGS = {
    en: {
      "nav.docs": "Docs",
      "nav.settings": "Settings",
      "nav.logout": "Logout",
      "nav.home": "Home",
      "brand.sub": "LLM Router",
      "gate.title": "Authentication required",
      "gate.body": "Please log in with your admin token.",
      "gate.login": "log in",
      "home.title": "Routing Groups",
      "home.newGroup": "+ New Group",
      "overview.title": "Gateway Status",
      "overview.meta": "Server health, open circuits, and recent upstream errors at a glance.",
      "overview.refresh": "Refresh",
      "overview.noErrors": "No recent upstream errors",
      "overview.serverOk": "server ok",
      "overview.serverDown": "server down",
      "overview.desktop": "desktop",
      "overview.server": "server",
      "overview.groups": "{n} groups",
      "overview.circuitsOk": "circuits ok",
      "overview.circuitsOpen": "{n} circuit open",
      "group.enabled": "enabled",
      "group.disabled": "disabled",
      "group.default": "default",
      "group.edit": "Edit",
      "group.copy": "Copy",
      "group.delete": "Delete",
      "group.stats": "{p} providers · {r} routes · {k} keys · {t} tools",
      "providers.title": "Upstream Providers",
      "providers.meta": "Each provider is an upstream service (e.g. DeepSeek / OpenAI / Anthropic). API key is shown once on creation; as admin you can view/copy it later.",
      "label.id": "ID (slug)",
      "label.name": "Name",
      "label.protocol": "Protocol",
      "label.baseUrl": "Base URL",
      "label.apiKey": "API Key",
      "label.note": "Note (optional)",
      "proto.openai": "OpenAI compatible (chat/completions + Bearer)",
      "proto.anthropic": "Anthropic compatible (/v1/messages + x-api-key)",
      "btn.addProvider": "Add Provider",
      "btn.cancel": "Cancel",
      "btn.test": "Test",
      "btn.save": "Save Changes",
      "routes.title": "Model Routes",
      "routes.meta": "An alias is the user-facing model name, routed to this group's provider upstream model. Modes: direct, auto-select, adapter, fusion.",
      "label.alias": "Alias (client-facing)",
      "label.provider": "Provider",
      "label.upstreamModel": "Upstream Model",
      "label.mode": "Mode",
      "label.enabled": "Enabled",
      "label.upstreamPath": "Upstream Path (for generation endpoints)",
      "label.yes": "Yes",
      "label.no": "No",
      "adapter.title": "Adapter Config",
      "adapter.visionAlias": "Vision Alias",
      "adapter.fallback": "Fallback",
      "adapter.advanced": "Advanced JSON",
      "fusion.title": "Fusion Config",
      "fusion.judgeAlias": "Judge Alias",
      "fusion.strategy": "Strategy",
      "fusion.minCandidates": "Min Candidates",
      "fusion.timeout": "Timeout (seconds)",
      "fusion.advanced": "Advanced JSON",
      "btn.addRoute": "Add Route",
      "rp.title": "Route Providers",
      "rp.meta": "Extra providers for auto-select / fusion. Priority: lower number = higher priority.",
      "label.priority": "Priority",
      "btn.addProviderRp": "Add Provider",
      "health.title": "Provider Health",
      "health.meta": "Circuit breaker status for this group. Open circuits are skipped by auto-select / fusion until reset or cooldown ends.",
      "health.refresh": "Refresh",
      "health.reset": "Reset",
      "health.empty": "No health records yet",
      "tools.title": "Tool Providers (built-in tool keys)",
      "tools.meta": "Provide keys for built-in tools (e.g. Tavily) exposed to LLMs in this group. When enabled, the router auto-injects tool schemas into OpenAI chat requests.",
      "label.toolId": "Tool ID",
      "btn.add": "Add",
      "keys.title": "Self-issued API Keys (db_sk_)",
      "keys.meta": "Keys for clients (Claude Code, Cursor, OpenAI SDK). The model field uses the alias above. Plaintext is shown once; admin can re-retrieve it. Keys are bound to this group.",
      "label.expires": "Expires (ISO, empty = never)",
      "btn.createKey": "Create Key",
      "keys.saveNow": "Save this now",
      "keys.copy": "Copy",
      "keys.maxRequests": "Max requests (optional)",
      "keys.maxTokens": "Max tokens (optional)",
      "keys.concurrency": "Concurrency limit",
      "keys.rpm": "RPM limit",
      "creds.title": "Upstream Key Pool",
      "creds.meta": "Multiple API keys for the same provider. Round-robin within priority; failover on 429/5xx.",
      "creds.label": "Label",
      "creds.priority": "Priority",
      "creds.add": "Add Key",
      "logs.title": "Request Logs",
      "logs.meta": "Recent upstream calls per key (alias / provider / status / latency / tokens). Across all groups.",
      "logs.e2e": "Run E2E Test",
      "logs.key": "Key:",
      "logs.refresh": "Refresh",
      "logs.th.time": "Time",
      "logs.th.alias": "alias",
      "logs.th.provider": "provider",
      "logs.th.upstream": "upstream",
      "logs.th.status": "status",
      "logs.th.latency": "latency",
      "logs.th.tokens": "tokens",
      "logs.th.error": "error",
      "logs.empty": "No records",
      "modal.newGroup": "New Routing Group",
      "modal.sub": "A group bundles providers, routes, tool keys and self-issued API keys.",
      "modal.groupId": "Group ID (slug)",
      "modal.groupIdHint": "Lowercase alphanumeric, - and _. Used as the URL path segment.",
      "modal.displayName": "Display name",
      "modal.create": "Create Group",
      "settings.title": "Settings",
      "settings.meta": "Application preferences for this Keyway instance.",
      "settings.language": "Language",
      "settings.languageHelp": "Default is English. Choose Chinese to switch the admin UI.",
      "settings.lang.en": "English",
      "settings.lang.zh": "中文 (Chinese)",
      "settings.save": "Save settings",
      "settings.saved": "Saved",
      "settings.back": "← Back to groups",
      "login.title": "Admin Login",
      "login.subtitle": "Enter your admin token to access the management UI.",
      "login.token": "Admin Token",
      "login.placeholder": "Paste your KEYWAY_ADMIN_TOKEN here",
      "login.submit": "Login",
      "login.hint": "The admin token is set via KEYWAY_ADMIN_TOKEN in your .env. If not set, a random token is generated and printed to the console on startup. Desktop mode skips this screen on loopback.",
      "login.tagline": "LLM Routing Gateway",
      "common.copied": "Copied",
      "common.copyFailed": "Copy failed",
      "common.refreshed": "Refreshed",
      "common.empty": "(empty)",
      "common.yes": "Yes",
      "common.no": "No",
    },
    zh: {
      "nav.docs": "文档",
      "nav.settings": "设置",
      "nav.logout": "退出",
      "nav.home": "首页",
      "brand.sub": "LLM 路由",
      "gate.title": "需要登录",
      "gate.body": "请使用管理员令牌登录。",
      "gate.login": "登录",
      "home.title": "路由分组",
      "home.newGroup": "+ 新建分组",
      "overview.title": "网关状态",
      "overview.meta": "一眼查看服务健康、熔断状态与最近上游错误。",
      "overview.refresh": "刷新",
      "overview.noErrors": "暂无最近上游错误",
      "overview.serverOk": "服务正常",
      "overview.serverDown": "服务异常",
      "overview.desktop": "桌面端",
      "overview.server": "服务端",
      "overview.groups": "{n} 个分组",
      "overview.circuitsOk": "熔断正常",
      "overview.circuitsOpen": "{n} 个熔断打开",
      "group.enabled": "启用",
      "group.disabled": "禁用",
      "group.default": "默认",
      "group.edit": "编辑",
      "group.copy": "复制",
      "group.delete": "删除",
      "group.stats": "{p} 个供应商 · {r} 条路由 · {k} 把密钥 · {t} 个工具",
      "providers.title": "上游供应商",
      "providers.meta": "每个供应商对应一个上游服务（如 DeepSeek / OpenAI / Anthropic）。创建时展示一次 API Key，管理员之后仍可查看/复制。",
      "label.id": "ID（短标识）",
      "label.name": "名称",
      "label.protocol": "协议",
      "label.baseUrl": "Base URL",
      "label.apiKey": "API Key",
      "label.note": "备注（可选）",
      "proto.openai": "OpenAI 兼容（chat/completions + Bearer）",
      "proto.anthropic": "Anthropic 兼容（/v1/messages + x-api-key）",
      "btn.addProvider": "添加供应商",
      "btn.cancel": "取消",
      "btn.test": "测试",
      "btn.save": "保存更改",
      "routes.title": "模型路由",
      "routes.meta": "别名是客户端看到的模型名，会转发到本分组供应商的上游模型。模式：direct / auto-select / adapter / fusion。",
      "label.alias": "别名（客户端可见）",
      "label.provider": "供应商",
      "label.upstreamModel": "上游模型",
      "label.mode": "模式",
      "label.enabled": "启用",
      "label.upstreamPath": "上游路径（生成类接口）",
      "label.yes": "是",
      "label.no": "否",
      "adapter.title": "适配器配置",
      "adapter.visionAlias": "视觉模型别名",
      "adapter.fallback": "失败回退",
      "adapter.advanced": "高级 JSON",
      "fusion.title": "融合配置",
      "fusion.judgeAlias": "裁判模型别名",
      "fusion.strategy": "策略",
      "fusion.minCandidates": "最少候选数",
      "fusion.timeout": "超时（秒）",
      "fusion.advanced": "高级 JSON",
      "btn.addRoute": "添加路由",
      "rp.title": "路由供应商",
      "rp.meta": "用于 auto-select / fusion 的额外供应商。优先级：数字越小越高。",
      "label.priority": "优先级",
      "btn.addProviderRp": "添加供应商",
      "health.title": "供应商健康",
      "health.meta": "本分组熔断状态。打开的熔断会在冷却结束或重置前被 auto-select / fusion 跳过。",
      "health.refresh": "刷新",
      "health.reset": "重置",
      "health.empty": "暂无健康记录",
      "tools.title": "工具供应商（内置工具密钥）",
      "tools.meta": "为内置工具（如 Tavily）配置密钥。启用后，路由器会在 OpenAI 聊天请求中自动注入工具 schema。",
      "label.toolId": "工具 ID",
      "btn.add": "添加",
      "keys.title": "自签发 API Key（db_sk_）",
      "keys.meta": "供 Claude Code、Cursor、OpenAI SDK 等客户端使用。模型字段填别名。明文只显示一次，管理员可再次取回。密钥绑定本分组。",
      "label.expires": "过期时间（ISO，空=永不过期）",
      "btn.createKey": "创建密钥",
      "keys.saveNow": "请立即保存",
      "keys.copy": "复制",
      "keys.maxRequests": "最大请求数（可选）",
      "keys.maxTokens": "最大 Token 数（可选）",
      "keys.concurrency": "并发上限",
      "keys.rpm": "每分钟请求上限",
      "creds.title": "上游 Key 池",
      "creds.meta": "同一 Provider 下挂多把上游 API Key。同优先级轮询；429/5xx 自动换号。",
      "creds.label": "标签",
      "creds.priority": "优先级",
      "creds.add": "添加 Key",
      "logs.title": "请求日志",
      "logs.meta": "按密钥查看最近上游调用（别名 / 供应商 / 状态 / 延迟 / tokens），跨全部分组。",
      "logs.e2e": "运行 E2E 测试",
      "logs.key": "密钥：",
      "logs.refresh": "刷新",
      "logs.th.time": "时间",
      "logs.th.alias": "别名",
      "logs.th.provider": "供应商",
      "logs.th.upstream": "上游",
      "logs.th.status": "状态",
      "logs.th.latency": "延迟",
      "logs.th.tokens": "tokens",
      "logs.th.error": "错误",
      "logs.empty": "暂无记录",
      "modal.newGroup": "新建路由分组",
      "modal.sub": "分组捆绑供应商、路由、工具密钥与自签发 API Key。",
      "modal.groupId": "分组 ID（短标识）",
      "modal.groupIdHint": "小写字母数字、. _ -，用作路径段。",
      "modal.displayName": "显示名称",
      "modal.create": "创建分组",
      "settings.title": "设置",
      "settings.meta": "本 Keyway 实例的界面偏好。",
      "settings.language": "语言",
      "settings.languageHelp": "默认英文。选择中文可切换管理界面语言。",
      "settings.lang.en": "English",
      "settings.lang.zh": "中文 (Chinese)",
      "settings.save": "保存设置",
      "settings.saved": "已保存",
      "settings.back": "← 返回分组列表",
      "login.title": "管理员登录",
      "login.subtitle": "输入管理员令牌以进入管理界面。",
      "login.token": "管理员令牌",
      "login.placeholder": "粘贴 KEYWAY_ADMIN_TOKEN",
      "login.submit": "登录",
      "login.hint": "管理员令牌通过 .env 中的 KEYWAY_ADMIN_TOKEN 设置。未设置时，启动会在控制台打印随机令牌。桌面端在本机回环地址可跳过登录。",
      "login.tagline": "LLM 路由网关",
      "common.copied": "已复制",
      "common.copyFailed": "复制失败",
      "common.refreshed": "已刷新",
      "common.empty": "（空）",
      "common.yes": "是",
      "common.no": "否",
    },
  };

  let currentLang = "en";

  function normalizeLang(lang) {
    const v = String(lang || "en").toLowerCase();
    return v === "zh" || v === "zh-cn" || v === "zh-hans" ? "zh" : "en";
  }

  function getLanguage() {
    return currentLang;
  }

  function t(key, vars) {
    const table = STRINGS[currentLang] || STRINGS.en;
    let s = table[key] ?? STRINGS.en[key] ?? key;
    if (vars && typeof vars === "object") {
      Object.keys(vars).forEach((k) => {
        s = s.replace(new RegExp("\\{" + k + "\\}", "g"), String(vars[k]));
      });
    }
    return s;
  }

  function applyI18n(root) {
    const scope = root || document;
    scope.querySelectorAll("[data-i18n]").forEach((el) => {
      const key = el.getAttribute("data-i18n");
      if (!key) return;
      const attr = el.getAttribute("data-i18n-attr");
      if (attr) {
        el.setAttribute(attr, t(key));
      } else {
        el.textContent = t(key);
      }
    });
    scope.querySelectorAll("[data-i18n-html]").forEach((el) => {
      const key = el.getAttribute("data-i18n-html");
      if (key) el.innerHTML = t(key);
    });
    scope.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
      const key = el.getAttribute("data-i18n-placeholder");
      if (key) el.setAttribute("placeholder", t(key));
    });
    document.documentElement.lang = currentLang === "zh" ? "zh-CN" : "en";
  }

  function setLanguage(lang, { persist = true } = {}) {
    currentLang = normalizeLang(lang);
    if (persist) {
      try {
        localStorage.setItem(STORAGE_KEY, currentLang);
      } catch (_) {}
    }
    applyI18n(document);
    return currentLang;
  }

  function loadStoredLanguage() {
    try {
      return normalizeLang(localStorage.getItem(STORAGE_KEY) || "en");
    } catch (_) {
      return "en";
    }
  }

  // bootstrap from localStorage immediately
  currentLang = loadStoredLanguage();

  global.KeywayI18n = {
    t,
    applyI18n,
    setLanguage,
    getLanguage,
    loadStoredLanguage,
    normalizeLang,
    STORAGE_KEY,
    STRINGS,
  };
})(window);
