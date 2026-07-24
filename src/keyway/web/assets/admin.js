// Keyway admin UI. Session-cookie auth (login via /admin/login).
// Hash-based views:
//   #/                → dashboard
//   #/groups          → group list
//   #/groups/<gid>    → group detail (tabbed)
//   #/logs            → request logs + E2E
//   #/settings        → preferences

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const t = (key, vars) => (window.KeywayI18n ? KeywayI18n.t(key, vars) : key);

// ---------- api & feedback ----------
async function api(path, opts = {}) {
  const resp = await fetch(path, { credentials: "include", ...opts });
  let data = null;
  try { data = await resp.json(); } catch {}
  if (!resp.ok) {
    const detail = data && data.detail;
    const msg = typeof detail === "string" ? detail : (detail?.message || data?.message || `${resp.status}`);
    const err = new Error(msg);
    err.status = resp.status;
    throw err;
  }
  return data;
}

function friendlyError(e) {
  if (e && (e.status === 401 || /401|unauthor/i.test(e.message || ""))) return t("err.auth");
  return (e && e.message) || String(e);
}

function toast(msg, kind = "info", ms = 3800) {
  const wrap = $("#toast-wrap");
  if (!wrap) return;
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.textContent = msg;
  wrap.appendChild(el);
  setTimeout(() => {
    el.classList.add("leaving");
    setTimeout(() => el.remove(), 200);
  }, ms);
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast(t("common.copied"), "ok", 2000);
    return true;
  } catch {
    toast(t("common.copyFailed"), "err");
    return false;
  }
}

function confirmDialog(body, { danger = true } = {}) {
  return new Promise((resolve) => {
    const overlay = $("#confirm-modal");
    $("#confirm-body").textContent = body;
    const okBtn = $("#confirm-ok");
    const cancelBtn = $("#confirm-cancel");
    okBtn.className = danger ? "btn btn-danger-solid" : "btn btn-primary";
    overlay.classList.add("open");
    const done = (val) => {
      overlay.classList.remove("open");
      okBtn.onclick = cancelBtn.onclick = overlay.onclick = null;
      resolve(val);
    };
    okBtn.onclick = () => done(true);
    cancelBtn.onclick = () => done(false);
    overlay.onclick = (e) => { if (e.target === overlay) done(false); };
  });
}

async function withLoading(btn, fn) {
  if (!btn) return fn();
  const old = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="spin"></span> ${esc(old)}`;
  try {
    return await fn();
  } finally {
    btn.disabled = false;
    btn.innerHTML = old;
  }
}

// ---------- formatting ----------
const fmtTime = (iso) => (iso ? String(iso).replace("T", " ").slice(0, 19) : "—");
const fmtNum = (n) => Number(n || 0).toLocaleString();

// ---------- theme ----------
const THEME_KEY = "keyway_theme";
function getTheme() {
  try { return localStorage.getItem(THEME_KEY) || "auto"; } catch { return "auto"; }
}
function setTheme(v) {
  try {
    if (v === "auto") localStorage.removeItem(THEME_KEY);
    else localStorage.setItem(THEME_KEY, v);
  } catch {}
  if (v === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", v);
  const foot = $("#foot-theme"); if (foot) foot.value = v;
  const st = $("#settings-theme"); if (st) st.value = v;
}

// ---------- state ----------
const state = {
  desktop: false,
  baseUrl: null,
  groups: [],
  group: null,          // current group meta (detail view)
  tab: "providers",
  providers: [],
  routes: [],
  keys: [],
  plaintextCache: {},   // key_id -> plaintext
  snippet: null,        // { groupId, alias, protocol, tab }
  editingKey: null,
};

async function getBaseUrl() {
  if (state.baseUrl) return state.baseUrl;
  try {
    const { config } = await api("/admin/config");
    state.baseUrl = (config && config.app_base_url) || window.location.origin;
  } catch {
    state.baseUrl = window.location.origin;
  }
  return state.baseUrl.replace(/\/+$/, "");
}

// ---------- router ----------
function parseRoute() {
  const h = (location.hash || "").replace(/^#\/?/, "");
  const parts = h.split("/").filter(Boolean);
  if (parts[0] === "groups" && parts[1]) return { view: "group", gid: decodeURIComponent(parts.slice(1).join("/")) };
  if (parts[0] === "groups") return { view: "groups" };
  if (parts[0] === "logs") return { view: "logs" };
  if (parts[0] === "settings") return { view: "settings" };
  return { view: "dashboard" };
}

function navigate(view, gid) {
  if (view === "group" && gid) location.hash = "#/groups/" + encodeURIComponent(gid);
  else if (view === "groups") location.hash = "#/groups";
  else if (view === "logs") location.hash = "#/logs";
  else if (view === "settings") location.hash = "#/settings";
  else location.hash = "#/";
}

const VIEWS = ["dashboard", "groups", "group", "logs", "settings"];
function showView(view) {
  VIEWS.forEach((v) => {
    const el = $("#view-" + v);
    if (el) el.style.display = v === view ? "" : "none";
  });
  $$(".side-link[data-nav]").forEach((a) => {
    const nav = a.getAttribute("data-nav");
    a.classList.toggle("active", nav === view || (view === "group" && nav === "groups"));
  });
}

async function render() {
  const { view, gid } = parseRoute();
  if (view === "group" && gid) {
    await renderGroupDetail(gid);
  } else {
    state.group = null;
    showView(view);
    if (view === "dashboard") await loadDashboard();
    else if (view === "groups") await loadGroups();
    else if (view === "logs") await initLogsView();
    else if (view === "settings") await loadSettings();
  }
  if (window.KeywayI18n) KeywayI18n.applyI18n(document);
}
window.addEventListener("hashchange", render);

// ---------- dashboard ----------
async function loadDashboard() {
  const [healthRes, overviewRes, logsRes, groupsRes] = await Promise.allSettled([
    fetch("/health"),
    api("/admin/llm/overview"),
    api("/admin/llm/logs?limit=500"),
    api("/admin/llm/groups"),
  ]);
  const healthOk = healthRes.status === "fulfilled" && healthRes.value.ok;
  const overview = overviewRes.status === "fulfilled" ? (overviewRes.value.overview || {}) : {};
  const logs = logsRes.status === "fulfilled" ? (logsRes.value.logs || []) : [];
  const groups = groupsRes.status === "fulfilled" ? (groupsRes.value.groups || []) : [];
  state.groups = groups;

  // gateway stat cards
  const circuits = overview.open_circuits || 0;
  const circuitProv = (overview.circuit_providers || []).join(", ");
  $("#dash-gateway").innerHTML = [
    statCard(t("stat.server"), healthOk ? t("stat.serverOk") : t("stat.serverDown"), healthOk ? "ok" : "err", overview.data_dir || ""),
    statCard(t("stat.mode"), overview.desktop_mode ? t("stat.desktop") : t("stat.serverMode"), "", ""),
    statCard(t("stat.groups"), fmtNum(overview.groups ?? groups.length), "", ""),
    statCard(t("stat.circuits"), circuits ? fmtNum(circuits) : t("stat.circuitsOk"), circuits ? "err" : "ok", circuitProv),
  ].join("");

  // usage aggregation
  const total = logs.length;
  const okCount = logs.filter((l) => Number(l.status_code) === 200).length;
  const avgLat = total ? Math.round(logs.reduce((s, l) => s + (l.latency_ms || 0), 0) / total) : 0;
  const tokens = logs.reduce((s, l) => s + (l.request_tokens || 0) + (l.response_tokens || 0), 0);
  $("#dash-usage-title").textContent = t("dash.usage", { n: total });
  $("#dash-usage").innerHTML = [
    statCard(t("stat.requests"), fmtNum(total)),
    statCard(t("stat.successRate"), total ? Math.round((okCount / total) * 100) + "%" : "—", total && okCount / total < 0.9 ? "err" : "ok"),
    statCard(t("stat.avgLatency"), total ? fmtNum(avgLat) + " ms" : "—"),
    statCard(t("stat.tokens"), fmtNum(tokens)),
  ].join("");

  // per-route bars (top 8)
  const byAlias = {};
  logs.forEach((l) => { const a = l.route_alias || "—"; byAlias[a] = (byAlias[a] || 0) + 1; });
  const entries = Object.entries(byAlias).sort((a, b) => b[1] - a[1]).slice(0, 8);
  const max = entries.length ? entries[0][1] : 0;
  $("#dash-bars").innerHTML = entries.length
    ? entries.map(([alias, n]) => `
      <div class="bar-row">
        <span class="bar-label" title="${esc(alias)}">${esc(alias)}</span>
        <span class="bar-track"><span class="bar-fill" style="width:${Math.max(2, Math.round((n / max) * 100))}%"></span></span>
        <span class="bar-val">${fmtNum(n)}</span>
      </div>`).join("")
    : `<div class="empty-state">${esc(t("dash.noData"))}</div>`;

  // recent errors
  const errs = logs.filter((l) => l.error).slice(0, 6);
  $("#dash-errors").innerHTML = errs.length
    ? errs.map((e) => `
      <div class="item">
        <div class="item-main">
          <div class="item-title" style="font-weight:500;">
            <span class="mono" style="font-size:0.78rem;">${esc(e.route_alias || "—")}</span>
            <span class="pill pill-err">${esc(e.status_code || "—")}</span>
            <span class="muted" style="font-size:0.75rem;font-weight:400;">${esc(fmtTime(e.created_at))}</span>
          </div>
          <div class="item-sub" style="color:var(--err);">${esc(String(e.error).slice(0, 140))}</div>
        </div>
      </div>`).join("")
    : `<div class="empty-state">${esc(t("dash.noErrors"))}</div>`;

  // recent requests table
  const recent = logs.slice(0, 10);
  $("#dash-recent").innerHTML = recent.length
    ? recent.map((l) => `
      <tr>
        <td class="mono">${esc(fmtTime(l.created_at))}</td>
        <td class="mono">${esc(l.route_alias || "—")}</td>
        <td class="mono">${esc(l.provider_id || "—")}</td>
        <td>${Number(l.status_code) === 200 ? `<span class="pill pill-ok">${esc(l.status_code)}</span>` : `<span class="pill pill-err">${esc(l.status_code || "—")}</span>`}</td>
        <td>${l.latency_ms != null ? esc(l.latency_ms) + " ms" : "—"}</td>
        <td>${fmtNum((l.request_tokens || 0) + (l.response_tokens || 0))}</td>
      </tr>`).join("")
    : `<tr><td colspan="6" class="muted" style="text-align:center;">${esc(t("dash.noRequests"))}</td></tr>`;

  renderWizard(groups);
}

function statCard(label, value, kind = "", sub = "") {
  return `<div class="stat-card">
    <div class="stat-label">${esc(label)}</div>
    <div class="stat-value ${kind}">${esc(value)}</div>
    ${sub ? `<div class="stat-sub" title="${esc(sub)}">${esc(sub)}</div>` : ""}
  </div>`;
}

// ---------- onboarding wizard ----------
const WIZARD_HIDE_KEY = "keyway_wizard_hidden";

function wizardProgress(groups) {
  const sum = (f) => groups.reduce((s, g) => s + (g[f] || 0), 0);
  return {
    group: groups.length > 0,
    provider: sum("provider_count") > 0,
    route: sum("route_count") > 0,
    key: sum("key_count") > 0,
  };
}

function renderWizard(groups) {
  const card = $("#wizard-card");
  if (!card) return;
  const p = wizardProgress(groups);
  const allDone = p.provider && p.route && p.key;
  let hidden = false;
  try { hidden = localStorage.getItem(WIZARD_HIDE_KEY) === "1"; } catch {}
  if (allDone || hidden) { card.style.display = "none"; return; }
  card.style.display = "";

  const firstGroup = (groups[0] || {}).group_id || "default";
  const groupWith = (f) => (groups.find((g) => (g[f] || 0) > 0) || {}).group_id || firstGroup;

  const steps = [
    { done: true, title: t("wizard.s1.t"), desc: t("wizard.s1.d") },
    {
      done: p.provider, title: t("wizard.s2.t"), desc: t("wizard.s2.d"),
      action: { label: t("wizard.s2.go"), run: () => openGroupTab(firstGroup, "providers", { openForm: "provider" }) },
    },
    {
      done: p.route, title: t("wizard.s3.t"), desc: t("wizard.s3.d"),
      action: p.provider ? { label: t("wizard.s3.go"), run: () => openGroupTab(groupWith("provider_count"), "routes", { openForm: "route" }) } : null,
    },
    {
      done: p.key, title: t("wizard.s4.t"), desc: t("wizard.s4.d"),
      action: p.route ? { label: t("wizard.s4.go"), run: () => openGroupTab(groupWith("route_count"), "keys", { openForm: "key" }) } : null,
    },
    {
      done: false, title: t("wizard.s5.t"), desc: t("wizard.s5.d"),
      action: p.key ? { label: t("wizard.s5.go"), run: () => openFirstRouteSnippet(groups) } : null,
    },
  ];

  $("#wizard-steps").innerHTML = steps.map((s, i) => `
    <div class="step ${s.done ? "done" : ""}">
      <span class="step-num">${s.done ? "✓" : i + 1}</span>
      <div class="step-body">
        <div class="step-title">${esc(s.title)}</div>
        <div class="step-desc">${esc(s.desc)}</div>
      </div>
      ${!s.done && s.action ? `<button class="btn btn-primary btn-sm" data-wstep="${i}" type="button">${esc(s.action.label)}</button>` : ""}
    </div>`).join("");

  $$("#wizard-steps [data-wstep]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const s = steps[Number(btn.getAttribute("data-wstep"))];
      if (s && s.action) s.action.run();
    });
  });
}

async function openGroupTab(gid, tab, { openForm = null } = {}) {
  if (!state.group || state.group.group_id !== gid) {
    navigate("group", gid);
    // wait for hashchange render to finish loading the group
    await new Promise((resolve) => {
      const check = () => (state.group && state.group.group_id === gid ? resolve() : setTimeout(check, 60));
      check();
      setTimeout(resolve, 3000);
    });
  }
  showTab(tab);
  if (openForm === "provider") showProviderForm(false);
  else if (openForm === "route") showRouteForm(false);
  else if (openForm === "key") showKeyForm();
}

async function openFirstRouteSnippet(groups) {
  for (const g of groups) {
    if ((g.route_count || 0) > 0) {
      try {
        const { routes } = await api(`/admin/llm/groups/${encodeURIComponent(g.group_id)}/routes`);
        const route = routes.find((r) => r.enabled) || routes[0];
        if (route) {
          const { providers } = await api(`/admin/llm/groups/${encodeURIComponent(g.group_id)}/providers`);
          const prov = providers.find((p) => p.provider_id === route.provider_id);
          openSnippet({ groupId: g.group_id, alias: route.alias, protocol: (prov && prov.protocol) || "openai" });
          return;
        }
      } catch {}
    }
  }
  toast(t("route.noProviders"), "warn");
}

// ---------- groups view ----------
async function loadGroups() {
  let groups = [];
  try {
    const data = await api("/admin/llm/groups");
    groups = data.groups || [];
  } catch (e) {
    $("#group-list").innerHTML = `<div class="empty-state">${esc(t("common.loadFailed"))}: ${esc(friendlyError(e))}</div>`;
    return;
  }
  state.groups = groups;
  $("#group-list").innerHTML = groups.length
    ? groups.map((g) => {
        const isDefault = g.group_id === "default";
        return `
        <div class="item">
          <div class="item-main">
            <div class="item-title">
              ${esc(g.name)}
              <span class="item-id">${esc(g.group_id)}</span>
              ${g.enabled ? `<span class="pill pill-ok">${esc(t("group.enabled"))}</span>` : `<span class="pill pill-err">${esc(t("group.disabled"))}</span>`}
              ${isDefault ? `<span class="pill pill-info">${esc(t("group.default"))}</span>` : ""}
            </div>
            <div class="item-sub">${esc(t("groups.stats", { p: g.provider_count, r: g.route_count, k: g.key_count, t: g.tool_count }))}</div>
          </div>
          <div class="item-actions">
            <button class="btn btn-ghost btn-sm" data-action="group-open" data-gid="${esc(g.group_id)}" type="button">${esc(t("groups.open"))}</button>
            <button class="btn btn-ghost btn-sm" data-action="group-copy" data-gid="${esc(g.group_id)}" data-name="${esc(g.name)}" type="button">${esc(t("groups.copy"))}</button>
            <button class="btn btn-danger btn-sm" data-action="group-delete" data-gid="${esc(g.group_id)}" data-name="${esc(g.name)}" ${isDefault ? "disabled" : ""} type="button">${esc(t("groups.delete"))}</button>
          </div>
        </div>`;
      }).join("")
    : `<div class="empty-state">${esc(t("groups.empty"))}</div>`;
}

async function copyGroupFlow(srcGid, srcName) {
  try {
    const data = await api(`/admin/llm/groups/${encodeURIComponent(srcGid)}/copy`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_name: `${srcName} (copy)` }),
    });
    const g = data.group || {};
    const issued = (g.issued_keys || []).length;
    toast(
      `${t("common.done")} → ${g.group_id}` + (issued ? ` (${issued} key${issued > 1 ? "s" : ""})` : ""),
      "ok",
    );
    navigate("group", g.group_id);
  } catch (e) {
    toast(`${t("common.opFailed")}: ${friendlyError(e)}`, "err");
  }
}

// ---------- group detail ----------
async function renderGroupDetail(gid) {
  let group;
  try {
    const data = await api(`/admin/llm/groups/${encodeURIComponent(gid)}`);
    group = data.group;
  } catch (e) {
    toast(friendlyError(e), "err");
    navigate("groups");
    return;
  }
  state.group = group;
  showView("group");

  const isDefault = group.group_id === "default";
  $("#group-crumb").textContent = group.name;
  $("#group-head").innerHTML = `
    <h1>${esc(group.name)}</h1>
    <span class="pill pill-neutral mono">${esc(group.group_id)}</span>
    ${group.enabled ? `<span class="pill pill-ok">${esc(t("group.enabled"))}</span>` : `<span class="pill pill-err">${esc(t("group.disabled"))}</span>`}
    ${isDefault ? `<span class="pill pill-info">${esc(t("group.default"))}</span>` : ""}
    <span class="muted" style="font-size:0.82rem;">${esc(t("groups.stats", { p: group.provider_count, r: group.route_count, k: group.key_count, t: group.tool_count }))}</span>
    <span class="spacer"></span>
    <button class="btn btn-ghost btn-sm" data-action="group-rename" type="button">${esc(t("group.rename"))}</button>
    <button class="btn btn-ghost btn-sm" data-action="group-toggle" type="button">${esc(group.enabled ? t("group.disable") : t("group.enable"))}</button>
    <button class="btn btn-ghost btn-sm" data-action="group-copy-self" type="button">${esc(t("group.copy"))}</button>
    <button class="btn btn-danger btn-sm" data-action="group-delete-self" ${isDefault ? "disabled" : ""} type="button">${esc(t("group.delete"))}</button>
  `;

  showTab(state.tab || "providers");
  await Promise.all([loadProviders(), loadRoutes(), loadKeys(), loadTools(), loadHealth()]);
  hideCredentialPanel();
  hideRouteProvidersPanel();
}

function showTab(tab) {
  state.tab = tab;
  $$("#group-tabs .tab").forEach((b) => b.classList.toggle("active", b.getAttribute("data-tab") === tab));
  ["providers", "routes", "keys", "tools", "health"].forEach((name) => {
    const el = $("#tab-" + name);
    if (el) el.style.display = name === tab ? "" : "none";
  });
}

async function renameGroupFlow() {
  const g = state.group;
  if (!g) return;
  const newName = prompt(t("group.rename") + ":", g.name);
  if (!newName || newName === g.name) return;
  try {
    await api(`/admin/llm/groups/${encodeURIComponent(g.group_id)}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName }),
    });
    await renderGroupDetail(g.group_id);
  } catch (e) { toast(`${t("common.opFailed")}: ${friendlyError(e)}`, "err"); }
}

async function toggleGroupFlow() {
  const g = state.group;
  if (!g) return;
  try {
    await api(`/admin/llm/groups/${encodeURIComponent(g.group_id)}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !g.enabled }),
    });
    await renderGroupDetail(g.group_id);
  } catch (e) { toast(`${t("common.opFailed")}: ${friendlyError(e)}`, "err"); }
}

async function deleteGroupFlow(gid, name, { fromDetail = false } = {}) {
  if (!(await confirmDialog(t("group.deleteConfirm", { name: name || gid })))) return;
  try {
    await api(`/admin/llm/groups/${encodeURIComponent(gid)}`, { method: "DELETE" });
    toast(t("common.done"), "ok");
    navigate(fromDetail ? "groups" : "groups");
    if (!fromDetail) await loadGroups();
  } catch (e) { toast(`${t("common.opFailed")}: ${friendlyError(e)}`, "err"); }
}

// ---------- providers ----------
async function loadProviders() {
  if (!state.group) return;
  try {
    const { providers } = await api(`/admin/llm/groups/${encodeURIComponent(state.group.group_id)}/providers`);
    state.providers = providers || [];
    $("#provider-list").innerHTML = state.providers.length
      ? state.providers.map((p) => {
          const proto = p.protocol || "openai";
          return `
          <div class="item">
            <div class="item-main">
              <div class="item-title">
                ${esc(p.name)}
                <span class="item-id">${esc(p.provider_id)}</span>
                <span class="pill ${proto === "anthropic" ? "pill-warn" : "pill-info"}">${esc(proto)}</span>
                ${p.enabled ? "" : `<span class="pill pill-err">${esc(t("common.disabled"))}</span>`}
              </div>
              <div class="item-sub">${esc(p.base_url)} · ${esc(t("prov.pool", { ok: p.credential_healthy ?? 0, total: p.credential_count ?? 0 }))}</div>
            </div>
            <div class="item-actions">
              <button class="btn btn-ghost btn-sm" data-action="prov-creds" data-id="${esc(p.provider_id)}" type="button">${esc(t("prov.keys"))}</button>
              <button class="btn btn-ghost btn-sm" data-action="prov-edit" data-id="${esc(p.provider_id)}" type="button">${esc(t("common.edit"))}</button>
              <button class="btn btn-ghost btn-sm" data-action="prov-test" data-id="${esc(p.provider_id)}" type="button">${esc(t("common.test"))}</button>
              <button class="btn btn-ghost btn-sm" data-action="prov-toggle" data-id="${esc(p.provider_id)}" data-enabled="${p.enabled ? "1" : "0"}" type="button">${esc(p.enabled ? t("group.disable") : t("group.enable"))}</button>
              <button class="btn btn-danger btn-sm" data-action="prov-delete" data-id="${esc(p.provider_id)}" type="button">${esc(t("common.delete"))}</button>
            </div>
          </div>`;
        }).join("")
      : `<div class="empty-state">${esc(t("common.empty"))}</div>`;
  } catch (e) {
    $("#provider-list").innerHTML = `<div class="empty-state">${esc(friendlyError(e))}</div>`;
  }
  // keep route provider selects in sync
  syncProviderSelects();
}

function syncProviderSelects() {
  const options = state.providers.map((p) =>
    `<option value="${esc(p.provider_id)}">${esc(p.provider_id)} — ${esc(p.name)}</option>`).join("");
  const sel = $("#route-provider-select");
  if (sel) sel.innerHTML = options;
  const rpSel = $("#rp-provider-select");
  if (rpSel) rpSel.innerHTML = options;
}

function resetProviderForm() {
  const f = $("#provider-form");
  f.reset();
  $("#provider-edit-id").value = "";
  $("#provider-id-input").readOnly = false;
  $("#provider-protocol").value = "openai";
  $("#provider-submit").textContent = t("prov.submit");
  $("#provider-test").style.display = "none";
  $("#provider-edit-banner").style.display = "none";
}

function showProviderForm(editing) {
  $("#provider-form").style.display = "";
  $("#provider-add-btn").style.display = "none";
  if (!editing) resetProviderForm();
  $("#provider-id-input").focus();
}

function hideProviderForm() {
  $("#provider-form").style.display = "none";
  $("#provider-add-btn").style.display = "";
  resetProviderForm();
}

async function editProvider(id) {
  try {
    const { provider } = await api(`/admin/llm/providers/${encodeURIComponent(id)}`);
    const f = $("#provider-form");
    f.elements["provider_id"].value = provider.provider_id;
    f.elements["name"].value = provider.name || "";
    f.elements["base_url"].value = provider.base_url || "";
    f.elements["api_key"].value = provider.api_key || "";
    f.elements["note"].value = provider.note || "";
    $("#provider-protocol").value = provider.protocol || "openai";
    $("#provider-edit-id").value = provider.provider_id;
    $("#provider-id-input").readOnly = true;
    $("#provider-submit").textContent = t("prov.save");
    $("#provider-test").style.display = "";
    $("#provider-edit-banner").style.display = "";
    showProviderForm(true);
  } catch (e) { toast(friendlyError(e), "err"); }
}

async function testProvider(id, btn) {
  await withLoading(btn, async () => {
    try {
      const { test } = await api("/admin/llm/test", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider_id: id, group_id: state.group ? state.group.group_id : undefined }),
      });
      toast(`${test.ok ? "PASS" : "FAIL"} · ${test.message} (${test.latency_ms}ms)`, test.ok ? "ok" : "err", 6000);
    } catch (e) { toast(`${t("common.opFailed")}: ${friendlyError(e)}`, "err"); }
  });
}

function bindProviderForm() {
  $("#provider-add-btn")?.addEventListener("click", () => showProviderForm(false));
  $("#provider-cancel")?.addEventListener("click", hideProviderForm);
  $("#provider-test")?.addEventListener("click", (e) => {
    const id = $("#provider-edit-id").value;
    if (id) testProvider(id, e.currentTarget);
  });
  $("#provider-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target;
    const editId = $("#provider-edit-id").value;
    const fd = new FormData(f);
    const apiKey = fd.get("api_key");
    try {
      if (editId) {
        const body = {
          name: fd.get("name"), base_url: fd.get("base_url"),
          protocol: fd.get("protocol") || "openai", note: fd.get("note") || "",
        };
        if (apiKey) body.api_key = apiKey;
        await api(`/admin/llm/providers/${encodeURIComponent(editId)}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        });
        toast(t("prov.updated"), "ok");
      } else {
        if (!apiKey) { toast(t("prov.apiKeyRequired"), "warn"); return; }
        await api(`/admin/llm/groups/${encodeURIComponent(state.group.group_id)}/providers`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            provider_id: fd.get("provider_id"), name: fd.get("name"),
            base_url: fd.get("base_url"), api_key: apiKey,
            protocol: fd.get("protocol") || "openai", note: fd.get("note") || "",
          }),
        });
        toast(t("prov.added"), "ok");
      }
      hideProviderForm();
      await loadProviders();
    } catch (err) { toast(`${t("common.opFailed")}: ${friendlyError(err)}`, "err"); }
  });
}

// ---------- credentials (key pool) ----------
async function showCredentialPanel(providerId) {
  $("#credential-provider-id").value = providerId;
  $("#credential-panel-meta").textContent = t("cred.for", { id: providerId });
  $("#credential-panel").style.display = "";
  $("#credential-panel").scrollIntoView({ behavior: "smooth", block: "nearest" });
  await loadCredentials(providerId);
}

function hideCredentialPanel() {
  const panel = $("#credential-panel");
  if (panel) panel.style.display = "none";
  const form = $("#credential-form");
  if (form) form.reset();
}

async function loadCredentials(providerId) {
  try {
    const { credentials } = await api(`/admin/llm/providers/${encodeURIComponent(providerId)}/credentials`);
    $("#credential-list").innerHTML = credentials.length
      ? credentials.map((c) => `
        <div class="item">
          <div class="item-main">
            <div class="item-title" style="font-weight:500;">
              ${esc(c.label || c.credential_id.slice(0, 8))}
              <span class="pill pill-neutral">${esc(t("cred.priorityShort", { n: c.priority }))}</span>
              ${c.enabled ? "" : `<span class="pill pill-err">${esc(t("common.disabled"))}</span>`}
              ${c.circuit_open ? `<span class="pill pill-warn">${esc(t("cred.circuitOpen"))}</span>` : ""}
            </div>
            <div class="item-sub mono">${c.api_key_set ? esc(c.api_key) : esc(t("cred.noKey"))}</div>
          </div>
          <div class="item-actions">
            <button class="btn btn-ghost btn-sm" data-action="cred-toggle" data-id="${esc(c.credential_id)}" data-enabled="${c.enabled ? "1" : "0"}" type="button">${esc(c.enabled ? t("group.disable") : t("group.enable"))}</button>
            <button class="btn btn-ghost btn-sm" data-action="cred-reset" data-id="${esc(c.credential_id)}" type="button">${esc(t("health.reset"))}</button>
            <button class="btn btn-danger btn-sm" data-action="cred-delete" data-id="${esc(c.credential_id)}" type="button">${esc(t("common.delete"))}</button>
          </div>
        </div>`).join("")
      : `<div class="empty-state">${esc(t("cred.empty"))}</div>`;
  } catch (e) { toast(friendlyError(e), "err"); }
}

function bindCredentialForm() {
  $("#credential-close")?.addEventListener("click", hideCredentialPanel);
  $("#credential-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const providerId = $("#credential-provider-id").value;
    if (!providerId) return;
    const fd = new FormData(e.target);
    try {
      await api(`/admin/llm/providers/${encodeURIComponent(providerId)}/credentials`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: fd.get("api_key"), label: fd.get("label") || "", priority: Number(fd.get("priority") || 0) }),
      });
      toast(t("cred.added"), "ok");
      e.target.reset();
      $("#credential-provider-id").value = providerId;
      await loadCredentials(providerId);
      await loadProviders();
    } catch (err) { toast(`${t("common.opFailed")}: ${friendlyError(err)}`, "err"); }
  });
}

// ---------- routes ----------
function parseJsonSafe(raw, fallback) {
  try { return JSON.parse(raw || "{}"); } catch { return fallback || {}; }
}

function syncRouteModeFields() {
  const mode = $("#route-mode")?.value || "direct";
  const key = { direct: "route.modeHint.direct", "auto-select": "route.modeHint.auto", adapter: "route.modeHint.adapter", fusion: "route.modeHint.fusion" }[mode];
  const hint = $("#route-mode-hint");
  if (hint && key) hint.textContent = t(key);
  const aw = $("#route-adapter-wrap");
  const fw = $("#route-fusion-wrap");
  if (aw) aw.style.display = mode === "adapter" ? "" : "none";
  if (fw) fw.style.display = mode === "fusion" ? "" : "none";
}

function syncAdapterFieldsFromJson() {
  const cfg = parseJsonSafe($("#route-adapter-config")?.value, {});
  if ($("#adapter-vision-alias")) $("#adapter-vision-alias").value = cfg.vision_alias || "";
  if ($("#adapter-fallback")) $("#adapter-fallback").value = cfg.fallback || "error";
}

function syncFusionFieldsFromJson() {
  const cfg = parseJsonSafe($("#route-fusion-config")?.value, {});
  if ($("#fusion-judge-alias")) $("#fusion-judge-alias").value = cfg.judge_alias || "";
  if ($("#fusion-strategy")) $("#fusion-strategy").value = cfg.strategy || "compare_and_synthesize";
  if ($("#fusion-min-candidates")) $("#fusion-min-candidates").value = cfg.min_candidates ?? 2;
  if ($("#fusion-timeout")) $("#fusion-timeout").value = cfg.timeout_seconds ?? 30;
}

function buildAdapterConfigJson() {
  const existing = parseJsonSafe($("#route-adapter-config")?.value, {});
  existing.vision_alias = ($("#adapter-vision-alias")?.value || "").trim();
  existing.fallback = $("#adapter-fallback")?.value || "error";
  if (!existing.vision_alias) delete existing.vision_alias;
  const json = JSON.stringify(existing);
  if ($("#route-adapter-config")) $("#route-adapter-config").value = json;
  return json;
}

function buildFusionConfigJson() {
  const existing = parseJsonSafe($("#route-fusion-config")?.value, {});
  existing.judge_alias = ($("#fusion-judge-alias")?.value || "").trim();
  existing.strategy = $("#fusion-strategy")?.value || "compare_and_synthesize";
  existing.min_candidates = parseInt($("#fusion-min-candidates")?.value || "2", 10) || 2;
  existing.timeout_seconds = parseInt($("#fusion-timeout")?.value || "30", 10) || 30;
  if (!existing.judge_alias) delete existing.judge_alias;
  const json = JSON.stringify(existing);
  if ($("#route-fusion-config")) $("#route-fusion-config").value = json;
  return json;
}

function clearAdapterFusionFields() {
  if ($("#adapter-vision-alias")) $("#adapter-vision-alias").value = "";
  if ($("#adapter-fallback")) $("#adapter-fallback").value = "error";
  if ($("#fusion-judge-alias")) $("#fusion-judge-alias").value = "";
  if ($("#fusion-strategy")) $("#fusion-strategy").value = "compare_and_synthesize";
  if ($("#fusion-min-candidates")) $("#fusion-min-candidates").value = "2";
  if ($("#fusion-timeout")) $("#fusion-timeout").value = "30";
  if ($("#route-adapter-config")) $("#route-adapter-config").value = "";
  if ($("#route-fusion-config")) $("#route-fusion-config").value = "";
}

function resetRouteForm() {
  $("#route-form").reset();
  $("#route-edit-id").value = "";
  $("#route-submit").textContent = t("route.submit");
  clearAdapterFusionFields();
  syncRouteModeFields();
  syncProviderSelects();
}

function showRouteForm(editing) {
  if (!state.providers.length) { toast(t("route.noProviders"), "warn"); return; }
  $("#route-form").style.display = "";
  $("#route-add-btn").style.display = "none";
  if (!editing) resetRouteForm();
}

function hideRouteForm() {
  $("#route-form").style.display = "none";
  $("#route-add-btn").style.display = "";
  resetRouteForm();
}

async function loadRoutes() {
  if (!state.group) return;
  try {
    const { routes } = await api(`/admin/llm/groups/${encodeURIComponent(state.group.group_id)}/routes`);
    state.routes = routes || [];
    $("#route-list").innerHTML = state.routes.length
      ? state.routes.map((r) => {
          const mode = r.mode || "direct";
          const prov = state.providers.find((p) => p.provider_id === r.provider_id);
          return `
          <div class="item">
            <div class="item-main">
              <div class="item-title">
                <span class="mono">${esc(r.alias)}</span>
                <span class="pill pill-violet">${esc(mode)}</span>
                ${r.enabled ? "" : `<span class="pill pill-err">${esc(t("common.disabled"))}</span>`}
              </div>
              <div class="item-sub">
                <strong>${esc(r.provider_id)}</strong>${prov ? ` <span class="pill ${prov.protocol === "anthropic" ? "pill-warn" : "pill-info"}" style="font-size:0.66rem;">${esc(prov.protocol || "openai")}</span>` : ""} → <span class="mono">${esc(r.upstream_model)}</span>
                ${r.upstream_path ? ` · <span class="mono">${esc(r.upstream_path)}</span>` : ""}
              </div>
            </div>
            <div class="item-actions">
              <button class="btn btn-primary btn-sm" data-action="route-connect" data-alias="${esc(r.alias)}" data-provider="${esc(r.provider_id)}" type="button">${esc(t("route.connect"))}</button>
              <button class="btn btn-ghost btn-sm" data-action="route-test" data-alias="${esc(r.alias)}" type="button">${esc(t("common.test"))}</button>
              <button class="btn btn-ghost btn-sm" data-action="route-rps" data-rid="${esc(r.route_id)}" data-alias="${esc(r.alias)}" type="button">${esc(t("route.providers"))}</button>
              <button class="btn btn-ghost btn-sm" data-action="route-edit" data-rid="${esc(r.route_id)}" type="button">${esc(t("common.edit"))}</button>
              <button class="btn btn-ghost btn-sm" data-action="route-toggle" data-id="${esc(r.route_id)}" data-enabled="${r.enabled ? "1" : "0"}" type="button">${esc(r.enabled ? t("group.disable") : t("group.enable"))}</button>
              <button class="btn btn-danger btn-sm" data-action="route-delete" data-id="${esc(r.route_id)}" type="button">${esc(t("common.delete"))}</button>
            </div>
          </div>`;
        }).join("")
      : `<div class="empty-state">${esc(t("common.empty"))}</div>`;
  } catch (e) {
    $("#route-list").innerHTML = `<div class="empty-state">${esc(friendlyError(e))}</div>`;
  }
}

async function editRoute(routeId) {
  try {
    const { route } = await api(`/admin/llm/routes/${encodeURIComponent(routeId)}`);
    const f = $("#route-form");
    showRouteForm(true);
    f.elements["alias"].value = route.alias || "";
    syncProviderSelects();
    f.elements["provider_id"].value = route.provider_id || "";
    f.elements["upstream_model"].value = route.upstream_model || "";
    f.elements["upstream_path"].value = route.upstream_path || "";
    f.elements["mode"].value = route.mode || "direct";
    f.elements["enabled"].value = route.enabled ? "1" : "0";
    f.elements["note"].value = route.note || "";
    $("#route-adapter-config").value = route.adapter_config || "";
    $("#route-fusion-config").value = route.fusion_config || "";
    syncAdapterFieldsFromJson();
    syncFusionFieldsFromJson();
    $("#route-edit-id").value = route.route_id;
    $("#route-submit").textContent = t("route.save");
    syncRouteModeFields();
    await showRouteProvidersPanel(route.route_id, route.alias);
  } catch (e) { toast(friendlyError(e), "err"); }
}

async function testRoute(alias, btn) {
  await withLoading(btn, async () => {
    try {
      const { test } = await api("/admin/llm/test", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ alias, group_id: state.group ? state.group.group_id : undefined }),
      });
      toast(`${test.ok ? "PASS" : "FAIL"} · ${test.message} (${test.latency_ms}ms)`, test.ok ? "ok" : "err", 6000);
    } catch (e) { toast(`${t("common.opFailed")}: ${friendlyError(e)}`, "err"); }
  });
}

function bindRouteForm() {
  $("#route-add-btn")?.addEventListener("click", () => showRouteForm(false));
  $("#route-cancel")?.addEventListener("click", hideRouteForm);
  $("#route-mode")?.addEventListener("change", syncRouteModeFields);
  $("#route-adapter-config")?.addEventListener("change", syncAdapterFieldsFromJson);
  $("#route-fusion-config")?.addEventListener("change", syncFusionFieldsFromJson);
  $("#route-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target;
    const editId = $("#route-edit-id").value;
    const fd = new FormData(f);
    const mode = fd.get("mode") || "direct";
    const adapterConfig = buildAdapterConfigJson() || "{}";
    const fusionConfig = buildFusionConfigJson() || "{}";
    try {
      if (editId) {
        await api(`/admin/llm/routes/${encodeURIComponent(editId)}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            alias: fd.get("alias"), provider_id: fd.get("provider_id"),
            upstream_model: fd.get("upstream_model"), upstream_path: fd.get("upstream_path") || "",
            mode, adapter_config: adapterConfig, fusion_config: fusionConfig,
            enabled: fd.get("enabled") === "1", note: fd.get("note") || "",
          }),
        });
        toast(t("route.updated"), "ok");
      } else {
        await api(`/admin/llm/groups/${encodeURIComponent(state.group.group_id)}/routes`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            alias: fd.get("alias"), provider_id: fd.get("provider_id"),
            upstream_model: fd.get("upstream_model"), upstream_path: fd.get("upstream_path") || "",
            mode, adapter_config: adapterConfig, fusion_config: fusionConfig,
            note: fd.get("note") || "",
          }),
        });
        toast(t("route.added"), "ok");
      }
      hideRouteForm();
      await loadRoutes();
    } catch (err) { toast(`${t("common.opFailed")}: ${friendlyError(err)}`, "err"); }
  });

  $("#rp-close")?.addEventListener("click", hideRouteProvidersPanel);
  $("#rp-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const routeId = $("#rp-route-id")?.value;
    if (!routeId) { toast(t("rp.selectRoute"), "warn"); return; }
    try {
      await api(`/admin/llm/routes/${encodeURIComponent(routeId)}/providers`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider_id: $("#rp-provider-select").value,
          upstream_model: $("#rp-upstream-model").value,
          priority: parseInt($("#rp-priority").value || "0", 10) || 0,
        }),
      });
      toast(t("rp.added"), "ok");
      $("#rp-upstream-model").value = "";
      await loadRouteProviders(routeId);
    } catch (err) { toast(`${t("common.opFailed")}: ${friendlyError(err)}`, "err"); }
  });
}

function hideRouteProvidersPanel() {
  const panel = $("#route-providers-panel");
  if (panel) panel.style.display = "none";
  const rid = $("#rp-route-id");
  if (rid) rid.value = "";
}

async function showRouteProvidersPanel(routeId, alias) {
  const panel = $("#route-providers-panel");
  if (!panel) return;
  panel.style.display = "";
  $("#rp-route-id").value = routeId;
  $("#rp-route-label").textContent = alias ? `(${alias})` : "";
  syncProviderSelects();
  await loadRouteProviders(routeId);
}

async function loadRouteProviders(routeId) {
  try {
    const { route_providers } = await api(`/admin/llm/routes/${encodeURIComponent(routeId)}/providers`);
    $("#rp-list").innerHTML = route_providers.length
      ? route_providers.map((rp) => `
        <div class="item">
          <div class="item-main">
            <div class="item-title" style="font-weight:500;">
              ${esc(rp.provider_id)}
              <span class="pill pill-neutral">${esc(t("cred.priorityShort", { n: rp.priority }))}</span>
              ${rp.enabled ? "" : `<span class="pill pill-err">${esc(t("common.disabled"))}</span>`}
            </div>
            <div class="item-sub mono">→ ${esc(rp.upstream_model)}</div>
          </div>
          <div class="item-actions">
            <button class="btn btn-ghost btn-sm" data-action="rp-toggle" data-id="${esc(rp.rp_id)}" data-enabled="${rp.enabled ? "1" : "0"}" type="button">${esc(rp.enabled ? t("group.disable") : t("group.enable"))}</button>
            <button class="btn btn-danger btn-sm" data-action="rp-delete" data-id="${esc(rp.rp_id)}" type="button">${esc(t("rp.remove"))}</button>
          </div>
        </div>`).join("")
      : `<div class="empty-state">${esc(t("rp.empty"))}</div>`;
  } catch (e) { toast(friendlyError(e), "err"); }
}

// ---------- keys ----------
function usageBar(used, max) {
  if (max == null) {
    return `<span class="usage-row"><span style="min-width:90px;">${esc(t("keys.usage", { used: fmtNum(used || 0), max: t("keys.unlimited") }))}</span></span>`;
  }
  const pct = max > 0 ? Math.min(100, Math.round(((used || 0) / max) * 100)) : 0;
  const cls = pct >= 95 ? "err" : pct >= 75 ? "warn" : "";
  return `<span class="usage-row"><span class="progress ${cls}" style="flex:1;"><span style="width:${pct}%"></span></span><span>${esc(t("keys.usage", { used: fmtNum(used || 0), max: fmtNum(max) }))}</span></span>`;
}

function isExpired(k) {
  if (!k.expires_at) return false;
  const d = new Date(k.expires_at);
  return !isNaN(d) && d.getTime() < Date.now();
}

async function loadKeys() {
  if (!state.group) return;
  try {
    const { keys } = await api(`/admin/llm/groups/${encodeURIComponent(state.group.group_id)}/keys`);
    state.keys = keys || [];
    $("#key-list").innerHTML = state.keys.length
      ? state.keys.map((k) => {
          const expired = isExpired(k);
          const lim = [
            k.concurrency_limit != null ? `conc ${k.concurrency_limit}` : null,
            k.rpm_limit != null ? `rpm ${k.rpm_limit}` : null,
          ].filter(Boolean).join(" · ");
          return `
          <div class="item" style="align-items:flex-start;">
            <div class="item-main">
              <div class="item-title">
                ${esc(k.name)}
                <span class="item-id">${esc(k.key_prefix)}…</span>
                ${k.enabled ? "" : `<span class="pill pill-err">${esc(t("common.disabled"))}</span>`}
                ${expired ? `<span class="pill pill-warn">${esc(t("keys.expiredTag"))}</span>` : ""}
              </div>
              <div class="item-sub">
                ${k.expires_at ? esc(fmtTime(k.expires_at)) : esc(t("keys.noExpiry"))} · ${k.last_used_at ? esc(t("keys.lastUsed", { t: fmtTime(k.last_used_at) })) : esc(t("keys.neverUsed"))}${lim ? " · " + esc(lim) : ""}
              </div>
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.2rem 0.9rem;margin-top:0.35rem;">
                <span class="usage-row"><span class="muted" style="min-width:2.2rem;">${esc(t("keys.reqShort"))}</span>${usageBar(k.used_requests, k.max_requests)}</span>
                <span class="usage-row"><span class="muted" style="min-width:2.2rem;">${esc(t("keys.tokShort"))}</span>${usageBar(k.used_tokens, k.max_tokens)}</span>
              </div>
            </div>
            <div class="item-actions">
              <button class="btn btn-primary btn-sm" data-action="key-connect" data-id="${esc(k.key_id)}" type="button">${esc(t("keys.connect"))}</button>
              <button class="btn btn-ghost btn-sm" data-action="key-copy" data-id="${esc(k.key_id)}" type="button">${esc(t("keys.copyKey"))}</button>
              <button class="btn btn-ghost btn-sm" data-action="key-edit" data-id="${esc(k.key_id)}" type="button">${esc(t("common.edit"))}</button>
              <button class="btn btn-danger btn-sm" data-action="key-delete" data-id="${esc(k.key_id)}" data-name="${esc(k.name)}" type="button">${esc(t("common.delete"))}</button>
            </div>
          </div>`;
        }).join("")
      : `<div class="empty-state">${esc(t("keys.empty"))}</div>`;
  } catch (e) {
    $("#key-list").innerHTML = `<div class="empty-state">${esc(friendlyError(e))}</div>`;
  }
}

function showKeyForm() {
  $("#key-form").style.display = "";
  $("#key-add-btn").style.display = "none";
}

function hideKeyForm() {
  const f = $("#key-form");
  f.style.display = "none";
  f.reset();
  $("#key-add-btn").style.display = "";
}

async function getKeyPlaintext(keyId) {
  if (state.plaintextCache[keyId]) return state.plaintextCache[keyId];
  const { plaintext } = await api(`/admin/llm/keys/${encodeURIComponent(keyId)}/plaintext`);
  state.plaintextCache[keyId] = plaintext;
  return plaintext;
}

function bindKeyForm() {
  $("#key-add-btn")?.addEventListener("click", showKeyForm);
  $("#key-cancel")?.addEventListener("click", hideKeyForm);
  $("#key-result-copy")?.addEventListener("click", () => {
    const v = $("#key-plaintext").textContent;
    if (v) copyText(v);
  });
  $("#key-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = { name: fd.get("name") };
    const exp = fd.get("expires_at");
    if (exp) body.expires_at = new Date(exp).toISOString();
    for (const field of ["max_requests", "max_tokens", "concurrency_limit", "rpm_limit"]) {
      const v = fd.get(field);
      if (v) body[field] = Number(v);
    }
    try {
      const data = await api(`/admin/llm/groups/${encodeURIComponent(state.group.group_id)}/keys`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      $("#key-plaintext").textContent = data.plaintext;
      $("#key-result").style.display = "";
      toast(t("keys.created"), "ok");
      hideKeyForm();
      await loadKeys();
    } catch (err) { toast(`${t("common.opFailed")}: ${friendlyError(err)}`, "err"); }
  });
}

// ---------- key edit modal ----------
function isoToLocalInput(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d)) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function openKeyEditModal(k) {
  state.editingKey = k;
  $("#ke-key-id").value = k.key_id;
  $("#ke-name").value = k.name || "";
  $("#ke-enabled").value = k.enabled ? "1" : "0";
  $("#ke-expires").value = isoToLocalInput(k.expires_at);
  $("#ke-clear-expires").checked = !k.expires_at;
  const quota = [
    ["ke-max-requests", "ke-clear-max-requests", k.max_requests],
    ["ke-max-tokens", "ke-clear-max-tokens", k.max_tokens],
    ["ke-concurrency", "ke-clear-concurrency", k.concurrency_limit],
    ["ke-rpm", "ke-clear-rpm", k.rpm_limit],
  ];
  quota.forEach(([inputId, clearId, val]) => {
    $("#" + inputId).value = val == null ? "" : val;
    $("#" + clearId).checked = val == null;
  });
  $("#ke-reset-usage").checked = false;
  $("#ke-error").textContent = "";
  $("#key-edit-modal").classList.add("open");
}

function closeKeyEditModal() {
  $("#key-edit-modal").classList.remove("open");
  state.editingKey = null;
}

function bindKeyEditModal() {
  $("#ke-cancel")?.addEventListener("click", closeKeyEditModal);
  $("#key-edit-modal")?.addEventListener("click", (e) => {
    if (e.target === $("#key-edit-modal")) closeKeyEditModal();
  });
  // disable number inputs while "unlimited" is checked
  [
    ["ke-max-requests", "ke-clear-max-requests"],
    ["ke-max-tokens", "ke-clear-max-tokens"],
    ["ke-concurrency", "ke-clear-concurrency"],
    ["ke-rpm", "ke-clear-rpm"],
  ].forEach(([inputId, clearId]) => {
    $("#" + clearId)?.addEventListener("change", (e) => {
      const input = $("#" + inputId);
      input.disabled = e.target.checked;
      if (e.target.checked) input.value = "";
    });
  });
  $("#ke-clear-expires")?.addEventListener("change", (e) => {
    const input = $("#ke-expires");
    input.disabled = e.target.checked;
    if (e.target.checked) input.value = "";
  });

  $("#ke-save")?.addEventListener("click", async (e) => {
    const k = state.editingKey;
    if (!k) return;
    const body = {};
    const name = $("#ke-name").value.trim();
    if (name && name !== k.name) body.name = name;
    const enabled = $("#ke-enabled").value === "1";
    if (enabled !== !!k.enabled) body.enabled = enabled;
    if ($("#ke-clear-expires").checked) {
      if (k.expires_at) body.clear_expires_at = true;
    } else {
      const v = $("#ke-expires").value;
      if (v) body.expires_at = new Date(v).toISOString();
    }
    const quota = [
      ["max_requests", "ke-max-requests", "ke-clear-max-requests", "clear_max_requests", k.max_requests],
      ["max_tokens", "ke-max-tokens", "ke-clear-max-tokens", "clear_max_tokens", k.max_tokens],
      ["concurrency_limit", "ke-concurrency", "ke-clear-concurrency", "clear_concurrency_limit", k.concurrency_limit],
      ["rpm_limit", "ke-rpm", "ke-clear-rpm", "clear_rpm_limit", k.rpm_limit],
    ];
    for (const [field, inputId, clearId, clearField, orig] of quota) {
      if ($("#" + clearId).checked) {
        if (orig != null) body[clearField] = true;
      } else {
        const v = $("#" + inputId).value;
        if (v !== "" && Number(v) !== orig) body[field] = Number(v);
      }
    }
    if ($("#ke-reset-usage").checked) body.reset_usage = true;
    await withLoading(e.currentTarget, async () => {
      try {
        await api(`/admin/llm/keys/${encodeURIComponent(k.key_id)}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        });
        toast(body.reset_usage ? t("keyEdit.resetDone") : t("keyEdit.saved"), "ok");
        closeKeyEditModal();
        await loadKeys();
      } catch (err) {
        $("#ke-error").textContent = friendlyError(err);
      }
    });
  });
}

// ---------- tools ----------
async function loadTools() {
  if (!state.group) return;
  try {
    const { tool_providers } = await api(`/admin/llm/groups/${encodeURIComponent(state.group.group_id)}/tool-providers`);
    $("#tool-list").innerHTML = (tool_providers || []).length
      ? tool_providers.map((tp) => `
        <div class="item">
          <div class="item-main">
            <div class="item-title">
              ${esc(tp.name)}
              <span class="item-id">${esc(tp.tool_id)}</span>
              ${tp.enabled ? "" : `<span class="pill pill-err">${esc(t("common.disabled"))}</span>`}
            </div>
            <div class="item-sub">${tp.api_key_set ? esc(t("tools.keySet")) : esc(t("tools.noKey"))}</div>
          </div>
          <div class="item-actions">
            <button class="btn btn-ghost btn-sm" data-action="tool-toggle" data-id="${esc(tp.tool_id)}" data-enabled="${tp.enabled ? "1" : "0"}" type="button">${esc(tp.enabled ? t("group.disable") : t("group.enable"))}</button>
            <button class="btn btn-danger btn-sm" data-action="tool-delete" data-id="${esc(tp.tool_id)}" type="button">${esc(t("common.delete"))}</button>
          </div>
        </div>`).join("")
      : `<div class="empty-state">${esc(t("tools.empty"))}</div>`;
  } catch (e) {
    $("#tool-list").innerHTML = `<div class="empty-state">${esc(friendlyError(e))}</div>`;
  }
}

function bindToolForm() {
  $("#tool-add-btn")?.addEventListener("click", () => {
    $("#tool-form").style.display = "";
    $("#tool-add-btn").style.display = "none";
  });
  $("#tool-cancel")?.addEventListener("click", () => {
    $("#tool-form").style.display = "none";
    $("#tool-form").reset();
    $("#tool-add-btn").style.display = "";
  });
  $("#tool-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      await api(`/admin/llm/groups/${encodeURIComponent(state.group.group_id)}/tool-providers`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool_id: fd.get("tool_id"), name: fd.get("name"), api_key: fd.get("api_key"), enabled: true }),
      });
      toast(t("tools.added"), "ok");
      e.target.reset();
      $("#tool-form").style.display = "none";
      $("#tool-add-btn").style.display = "";
      await loadTools();
    } catch (err) { toast(`${t("common.opFailed")}: ${friendlyError(err)}`, "err"); }
  });
}

// ---------- health ----------
async function loadHealth() {
  if (!state.group) return;
  try {
    const { health } = await api(`/admin/llm/health?group_id=${encodeURIComponent(state.group.group_id)}`);
    $("#health-list").innerHTML = (health || []).length
      ? health.map((h) => {
          const open = !!Number(h.circuit_open);
          return `
          <div class="item">
            <div class="item-main">
              <div class="item-title" style="font-weight:500;">
                ${esc(h.provider_id)}
                ${open ? `<span class="pill pill-err">${esc(t("health.open"))}</span>` : `<span class="pill pill-ok">${esc(t("health.healthy"))}</span>`}
              </div>
              <div class="item-sub">
                ${esc(t("health.failures", { n: h.consecutive_fails || 0 }))}${h.last_fail_at ? " · " + esc(t("health.lastFail", { t: fmtTime(h.last_fail_at) })) : ""}
              </div>
            </div>
            <div class="item-actions">
              <button class="btn btn-ghost btn-sm" data-action="health-reset" data-id="${esc(h.provider_id)}" type="button">${esc(t("health.reset"))}</button>
            </div>
          </div>`;
        }).join("")
      : `<div class="empty-state">${esc(t("health.empty"))}</div>`;
  } catch (e) { toast(friendlyError(e), "err"); }
}

// ---------- logs ----------
let logsViewReady = false;
async function initLogsView() {
  await populateLogKeySelect();
  await loadLogs();
  logsViewReady = true;
}

async function populateLogKeySelect() {
  const sel = $("#log-key-select");
  let allKeys = [];
  try {
    const { groups } = await api("/admin/llm/groups");
    state.groups = groups || [];
    for (const g of state.groups) {
      const { keys } = await api(`/admin/llm/groups/${encodeURIComponent(g.group_id)}/keys`);
      allKeys.push(...(keys || []).map((k) => ({ ...k, group_id: g.group_id })));
    }
  } catch {}
  const cur = sel.value;
  sel.innerHTML =
    `<option value="">${esc(t("logs.allKeys"))}</option>` +
    allKeys.map((k) => `<option value="${esc(k.key_id)}">${esc(k.key_prefix)}… (${esc(k.group_id)}/${esc(k.name)})</option>`).join("");
  if (cur) sel.value = cur;
}

async function loadLogs() {
  const keyId = $("#log-key-select").value;
  try {
    const url = keyId
      ? `/admin/llm/logs?api_key_id=${encodeURIComponent(keyId)}&limit=100`
      : `/admin/llm/logs?limit=100`;
    const { logs } = await api(url);
    $("#log-tbody").innerHTML = (logs || []).length
      ? logs.map((l) => `
        <tr>
          <td class="mono">${esc(fmtTime(l.created_at))}</td>
          <td class="mono">${esc(l.route_alias || "—")}</td>
          <td class="mono">${esc(l.provider_id || "—")}</td>
          <td class="mono">${esc(l.upstream_model || "—")}</td>
          <td>${Number(l.status_code) === 200 ? `<span class="pill pill-ok">${esc(l.status_code)}</span>` : `<span class="pill pill-err">${esc(l.status_code || "—")}</span>`}</td>
          <td>${l.latency_ms != null ? esc(l.latency_ms) + " ms" : "—"}</td>
          <td>${fmtNum((l.request_tokens || 0) + (l.response_tokens || 0))}</td>
          <td class="${l.error ? "err" : ""}">${esc(String(l.error || "").slice(0, 80))}</td>
        </tr>`).join("")
      : `<tr><td colspan="8" class="muted" style="text-align:center;">${esc(t("logs.empty"))}</td></tr>`;
  } catch (e) {
    $("#log-tbody").innerHTML = `<tr><td colspan="8" class="err" style="text-align:center;">${esc(friendlyError(e))}</td></tr>`;
  }
}

async function runE2e() {
  const btn = $("#e2e-run");
  await withLoading(btn, async () => {
    try {
      toast(t("logs.e2eRunning"), "info");
      const data = await api("/admin/llm/e2e", { method: "POST" });
      const grpResults = data.group_results || [];
      const badge = (ok) => `<span class="pill ${ok ? "pill-ok" : "pill-err"}">${esc(ok ? t("e2e.pass") : t("e2e.fail"))}</span>`;
      $("#e2e-results").innerHTML = grpResults.length
        ? grpResults.map((gr) => {
            const rows = (gr.results || []).map((r) => `
              <tr>
                <td class="mono">${esc(r.alias)}</td>
                <td>${esc(r.provider_id)} <span class="muted" style="font-size:0.72rem;">(${esc(r.protocol)})</span></td>
                <td class="mono">${esc(r.upstream_model)}</td>
                <td>${badge(r.ok)}</td>
                <td>${r.latency_ms}ms · ${esc(r.message || "")}</td>
              </tr>`).join("");
            const provRows = (gr.provider_probes || []).map((p) => `
              <tr>
                <td class="mono">${esc(p.provider_id)}</td>
                <td>${badge(p.ok)}</td>
                <td>${p.latency_ms}ms</td>
                <td style="font-size:0.8rem;">${esc(p.message || "")}</td>
              </tr>`).join("");
            return `
              <div class="card">
                <div class="card-head"><span class="card-title" style="font-size:0.95rem;">${esc(t("e2e.groupSummary", { gid: gr.group_id, name: gr.group_name, passed: gr.passed, total: gr.total }))}</span></div>
                <div class="table-wrap" style="margin-bottom:0.7rem;">
                  <table class="table">
                    <thead><tr><th>${esc(t("logs.th.alias"))}</th><th>${esc(t("dash.col.provider"))}</th><th>${esc(t("logs.th.upstream"))}</th><th>${esc(t("dash.col.status"))}</th><th>detail</th></tr></thead>
                    <tbody>${rows || `<tr><td colspan="5" class="muted" style="text-align:center;">${esc(t("e2e.noRoutes"))}</td></tr>`}</tbody>
                  </table>
                </div>
                <div class="card-meta" style="margin-bottom:0.4rem;">${esc(t("e2e.providerProbes", { passed: gr.providers_passed, total: gr.providers_total }))}</div>
                <div class="table-wrap">
                  <table class="table">
                    <thead><tr><th>${esc(t("dash.col.provider"))}</th><th>${esc(t("dash.col.status"))}</th><th>${esc(t("dash.col.latency"))}</th><th>detail</th></tr></thead>
                    <tbody>${provRows || `<tr><td colspan="4" class="muted" style="text-align:center;">${esc(t("e2e.noProviders"))}</td></tr>`}</tbody>
                  </table>
                </div>
              </div>`;
          }).join("")
        : `<div class="empty-state">${esc(t("e2e.noRoutes"))}</div>`;
      $("#e2e-results").style.display = "";
      const ok = data.summary && data.summary.startsWith("PASS");
      toast(data.summary || t("common.done"), ok ? "ok" : "err", 6000);
    } catch (e) {
      toast(`${t("common.opFailed")}: ${friendlyError(e)}`, "err");
    }
  });
}

// ---------- snippet modal ----------
function snippetDefs(protocol, base, key, alias) {
  const openaiPy = `# pip install openai
from openai import OpenAI

client = OpenAI(
    base_url="${base}/v1",
    api_key="${key}",
)

resp = client.chat.completions.create(
    model="${alias}",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(resp.choices[0].message.content)`;
  const curlOpenai = `curl ${base}/v1/chat/completions \\
  -H "Authorization: Bearer ${key}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "${alias}",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'`;
  const claude = `{
  "env": {
    "ANTHROPIC_BASE_URL": "${base}",
    "ANTHROPIC_AUTH_TOKEN": "${key}",
    "ANTHROPIC_MODEL": "${alias}",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "${alias}",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "${alias}",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "${alias}"
  }
}`;
  const anthropicPy = `# pip install anthropic
import anthropic

client = anthropic.Anthropic(
    base_url="${base}",
    api_key="${key}",
)

msg = client.messages.create(
    model="${alias}",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello!"}],
)
print(msg.content[0].text)`;
  const curlAnthropic = `curl ${base}/v1/messages \\
  -H "Authorization: Bearer ${key}" \\
  -H "anthropic-version: 2023-06-01" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "${alias}",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "Hello!"}]
  }'`;
  if (protocol === "anthropic") {
    return [
      { id: "claude", label: t("snip.tab.claude"), code: claude, hint: t("snip.claudeHint") },
      { id: "anthropicPy", label: t("snip.tab.anthropicPy"), code: anthropicPy, hint: "" },
      { id: "curl", label: t("snip.tab.curl"), code: curlAnthropic, hint: "" },
    ];
  }
  return [
    { id: "openaiPy", label: t("snip.tab.openaiPy"), code: openaiPy, hint: "" },
    { id: "curl", label: t("snip.tab.curl"), code: curlOpenai, hint: "" },
  ];
}

async function openSnippet({ groupId, alias, protocol }) {
  state.snippet = { groupId, alias, protocol: protocol || "openai", tab: null, defs: [] };
  $("#snip-sub").textContent = t("snip.sub", { alias });
  $("#snip-proto-note").textContent = t(protocol === "anthropic" ? "snip.protoNote.anthropic" : "snip.protoNote.openai");
  $("#snip-hint").textContent = "";

  // key dropdown
  let keys = [];
  try {
    const data = await api(`/admin/llm/groups/${encodeURIComponent(groupId)}/keys`);
    keys = (data.keys || []).filter((k) => k.enabled);
  } catch {}
  const sel = $("#snip-key-select");
  if (!keys.length) {
    sel.innerHTML = `<option value="">— ${esc(t("snip.noKeys"))} —</option>`;
    $("#snip-code").textContent = "";
    $("#snip-tabs").innerHTML = "";
    $("#snippet-modal").classList.add("open");
    return;
  }
  sel.innerHTML = keys.map((k) => `<option value="${esc(k.key_id)}">${esc(k.name)} (${esc(k.key_prefix)}…)</option>`).join("");
  $("#snippet-modal").classList.add("open");
  await refreshSnippet();
}

async function refreshSnippet() {
  const sn = state.snippet;
  if (!sn) return;
  const keyId = $("#snip-key-select").value;
  if (!keyId) return;
  let keyPlain;
  try {
    keyPlain = await getKeyPlaintext(keyId);
  } catch {
    keyPlain = "db_sk_PASTE_YOUR_KEY_HERE";
  }
  const base = await getBaseUrl();
  sn.defs = snippetDefs(sn.protocol, base, keyPlain, sn.alias);
  if (!sn.tab || !sn.defs.some((d) => d.id === sn.tab)) sn.tab = sn.defs[0].id;
  $("#snip-tabs").innerHTML = sn.defs.map((d) =>
    `<button class="snippet-tab ${d.id === sn.tab ? "active" : ""}" data-stab="${esc(d.id)}" type="button">${esc(d.label)}</button>`).join("");
  const cur = sn.defs.find((d) => d.id === sn.tab);
  $("#snip-code").textContent = cur ? cur.code : "";
  $("#snip-hint").textContent = cur && cur.hint ? cur.hint : "";
}

function bindSnippetModal() {
  $("#snip-key-select")?.addEventListener("change", refreshSnippet);
  $("#snip-tabs")?.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-stab]");
    if (!btn || !state.snippet) return;
    state.snippet.tab = btn.getAttribute("data-stab");
    refreshSnippet();
  });
  $("#snip-copy")?.addEventListener("click", () => copyText($("#snip-code").textContent));
  $("#snip-copy-key")?.addEventListener("click", async () => {
    const keyId = $("#snip-key-select").value;
    if (!keyId) return;
    try {
      await copyText(await getKeyPlaintext(keyId));
    } catch (e) {
      toast(`${t("keys.plaintextFail")}: ${friendlyError(e)}`, "err");
    }
  });
  const close = () => $("#snippet-modal").classList.remove("open");
  $("#snip-close")?.addEventListener("click", close);
  $("#snippet-modal")?.addEventListener("click", (e) => {
    if (e.target === $("#snippet-modal")) close();
  });
}

function connectForRoute(alias, providerId) {
  const prov = state.providers.find((p) => p.provider_id === providerId);
  openSnippet({ groupId: state.group.group_id, alias, protocol: (prov && prov.protocol) || "openai" });
}

async function connectForKey() {
  // pick the first enabled route of the current group
  const route = state.routes.find((r) => r.enabled) || state.routes[0];
  if (!route) {
    toast(t("wizard.s3.t"), "warn");
    return;
  }
  connectForRoute(route.alias, route.provider_id);
}

// ---------- new group modal ----------
function openGroupModal() {
  const overlay = $("#group-modal");
  $("#gm-gid").value = "";
  $("#gm-name").value = "";
  $("#gm-error").textContent = "";
  overlay.classList.add("open");
  $("#gm-gid").focus();
}

function closeGroupModal() {
  $("#group-modal").classList.remove("open");
}

async function submitGroupModal(btn) {
  const gid = $("#gm-gid").value.trim();
  const name = $("#gm-name").value.trim() || gid;
  const errEl = $("#gm-error");
  if (!gid) { errEl.textContent = t("modal.idRequired"); $("#gm-gid").focus(); return; }
  if (!/^[a-z0-9._-]{1,64}$/i.test(gid)) { errEl.textContent = t("modal.idInvalid"); $("#gm-gid").focus(); return; }
  const existing = state.groups.find((g) => g.group_id === gid);
  if (existing) { errEl.textContent = t("modal.idExists", { gid, name: existing.name || "—" }); return; }
  await withLoading(btn, async () => {
    try {
      await api("/admin/llm/groups", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ group_id: gid, name }),
      });
      closeGroupModal();
      toast(t("common.done"), "ok");
      navigate("group", gid);
    } catch (err) {
      errEl.textContent = /409|already exists/i.test(err.message)
        ? t("modal.idExists", { gid, name: "—" })
        : friendlyError(err);
    }
  });
}

function bindGroupModal() {
  $("#gm-create")?.addEventListener("click", (e) => submitGroupModal(e.currentTarget));
  $("#gm-cancel")?.addEventListener("click", closeGroupModal);
  $("#group-modal")?.addEventListener("click", (e) => {
    if (e.target === $("#group-modal")) closeGroupModal();
  });
  ["gm-gid", "gm-name"].forEach((id) => {
    $("#" + id)?.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); submitGroupModal($("#gm-create")); }
      if (e.key === "Escape") { e.preventDefault(); closeGroupModal(); }
    });
  });
}

// ---------- settings ----------
async function loadSettings() {
  try {
    const data = await api("/admin/settings");
    const lang = (data.settings && data.settings.language) || "en";
    const sel = $("#settings-language");
    if (sel) sel.value = lang;
  } catch (e) {
    toast(friendlyError(e), "err");
  }
  const themeSel = $("#settings-theme");
  if (themeSel) themeSel.value = getTheme();
}

function bindSettings() {
  $("#settings-theme")?.addEventListener("change", (e) => setTheme(e.target.value));
  $("#settings-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const lang = $("#settings-language")?.value || "en";
    try {
      const data = await api("/admin/settings", {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ language: lang }),
      });
      const saved = (data.settings && data.settings.language) || lang;
      if (window.KeywayI18n) KeywayI18n.setLanguage(saved);
      syncLangSelects();
      await render();
      toast(t("settings.saved"), "ok");
    } catch (err) { toast(`${t("common.opFailed")}: ${friendlyError(err)}`, "err"); }
  });
}

function syncLangSelects() {
  const lang = window.KeywayI18n ? KeywayI18n.getLanguage() : "en";
  const foot = $("#foot-lang"); if (foot) foot.value = lang;
  const st = $("#settings-language"); if (st) st.value = lang;
}

// ---------- global actions ----------
function bindGlobalActions() {
  $("#dash-refresh")?.addEventListener("click", () => withLoading($("#dash-refresh"), loadDashboard));
  $("#dash-wizard-btn")?.addEventListener("click", () => {
    try { localStorage.removeItem(WIZARD_HIDE_KEY); } catch {}
    renderWizard(state.groups);
  });
  $("#wizard-hide")?.addEventListener("click", () => {
    try { localStorage.setItem(WIZARD_HIDE_KEY, "1"); } catch {}
    $("#wizard-card").style.display = "none";
  });
  $("#groups-new")?.addEventListener("click", openGroupModal);
  $("#health-refresh")?.addEventListener("click", () => withLoading($("#health-refresh"), loadHealth));
  $("#log-refresh")?.addEventListener("click", () => withLoading($("#log-refresh"), loadLogs));
  $("#log-key-select")?.addEventListener("change", loadLogs);
  $("#e2e-run")?.addEventListener("click", runE2e);
  $("#group-tabs")?.addEventListener("click", (e) => {
    const btn = e.target.closest(".tab[data-tab]");
    if (btn) showTab(btn.getAttribute("data-tab"));
  });
  $("#foot-theme")?.addEventListener("change", (e) => setTheme(e.target.value));
  $("#foot-lang")?.addEventListener("change", async (e) => {
    const lang = e.target.value;
    if (window.KeywayI18n) KeywayI18n.setLanguage(lang);
    // persist to server too, best-effort
    try {
      await api("/admin/settings", {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ language: lang }),
      });
    } catch {}
    syncLangSelects();
    await render();
  });
  $("#logout-btn")?.addEventListener("click", async () => {
    try { await api("/admin/logout", { method: "POST" }); } catch {}
    window.location.href = "/";
  });
}

function bindClickDelegation() {
  $("#app").addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-action]");
    if (!btn) return;
    const action = btn.dataset.action;
    const id = btn.dataset.id;
    const gid = btn.dataset.gid;
    const name = btn.dataset.name;
    const alias = btn.dataset.alias;
    const rid = btn.dataset.rid;
    const provider = btn.dataset.provider;
    try {
      switch (action) {
        case "group-open": navigate("group", gid); break;
        case "group-copy": await copyGroupFlow(gid, name); break;
        case "group-delete": await deleteGroupFlow(gid, name); break;
        case "group-rename": await renameGroupFlow(); break;
        case "group-toggle": await toggleGroupFlow(); break;
        case "group-copy-self": await copyGroupFlow(state.group.group_id, state.group.name); break;
        case "group-delete-self": await deleteGroupFlow(state.group.group_id, state.group.name, { fromDetail: true }); break;

        case "prov-creds": await showCredentialPanel(id); break;
        case "prov-edit": await editProvider(id); break;
        case "prov-test": await testProvider(id, btn); break;
        case "prov-toggle": {
          await api(`/admin/llm/providers/${encodeURIComponent(id)}`, {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: btn.dataset.enabled !== "1" }),
          });
          await loadProviders();
          break;
        }
        case "prov-delete":
          if (await confirmDialog(t("prov.deleteConfirm", { id }))) {
            await api(`/admin/llm/providers/${encodeURIComponent(id)}`, { method: "DELETE" });
            toast(t("common.done"), "ok");
            hideCredentialPanel();
            await loadProviders();
            await loadRoutes();
          }
          break;

        case "cred-toggle": {
          await api(`/admin/llm/credentials/${encodeURIComponent(id)}`, {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: btn.dataset.enabled !== "1" }),
          });
          const pid = $("#credential-provider-id")?.value;
          if (pid) await loadCredentials(pid);
          await loadProviders();
          break;
        }
        case "cred-reset": {
          try { await api(`/admin/llm/credentials/${encodeURIComponent(id)}/health/reset`, { method: "POST" }); } catch {}
          const pid = $("#credential-provider-id")?.value;
          if (pid) await loadCredentials(pid);
          break;
        }
        case "cred-delete":
          if (await confirmDialog(t("cred.deleteConfirm"))) {
            await api(`/admin/llm/credentials/${encodeURIComponent(id)}`, { method: "DELETE" });
            const pid = $("#credential-provider-id")?.value;
            if (pid) await loadCredentials(pid);
            await loadProviders();
          }
          break;

        case "route-connect": connectForRoute(alias, provider); break;
        case "route-test": await testRoute(alias, btn); break;
        case "route-rps": await showRouteProvidersPanel(rid, alias || ""); break;
        case "route-edit": await editRoute(rid); break;
        case "route-toggle": {
          await api(`/admin/llm/routes/${encodeURIComponent(id)}`, {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: btn.dataset.enabled !== "1" }),
          });
          await loadRoutes();
          break;
        }
        case "route-delete":
          if (await confirmDialog(t("route.deleteConfirm", { id: alias || id }))) {
            await api(`/admin/llm/routes/${encodeURIComponent(id)}`, { method: "DELETE" });
            toast(t("common.done"), "ok");
            hideRouteProvidersPanel();
            await loadRoutes();
          }
          break;

        case "rp-toggle": {
          await api(`/admin/llm/route-providers/${encodeURIComponent(id)}`, {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: btn.dataset.enabled !== "1" }),
          });
          const rrid = $("#rp-route-id")?.value;
          if (rrid) await loadRouteProviders(rrid);
          break;
        }
        case "rp-delete":
          if (await confirmDialog(t("rp.removeConfirm"))) {
            await api(`/admin/llm/route-providers/${encodeURIComponent(id)}`, { method: "DELETE" });
            const rrid = $("#rp-route-id")?.value;
            if (rrid) await loadRouteProviders(rrid);
          }
          break;

        case "key-connect": await connectForKey(); break;
        case "key-copy":
          try {
            await copyText(await getKeyPlaintext(id));
          } catch (err) {
            toast(`${t("keys.plaintextFail")}: ${friendlyError(err)}`, "err");
          }
          break;
        case "key-edit": {
          const k = state.keys.find((x) => x.key_id === id);
          if (k) openKeyEditModal(k);
          break;
        }
        case "key-delete":
          if (await confirmDialog(t("keys.deleteConfirm", { name: name || id }))) {
            await api(`/admin/llm/keys/${encodeURIComponent(id)}`, { method: "DELETE" });
            delete state.plaintextCache[id];
            toast(t("common.done"), "ok");
            await loadKeys();
          }
          break;

        case "tool-toggle": {
          await api(`/admin/llm/tool-providers/${encodeURIComponent(id)}`, {
            method: "PATCH", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: btn.dataset.enabled !== "1" }),
          });
          await loadTools();
          break;
        }
        case "tool-delete":
          if (await confirmDialog(t("tools.deleteConfirm", { id }))) {
            await api(`/admin/llm/tool-providers/${encodeURIComponent(id)}`, { method: "DELETE" });
            toast(t("common.done"), "ok");
            await loadTools();
          }
          break;

        case "health-reset": {
          await api(`/admin/llm/health/${encodeURIComponent(id)}/reset`, { method: "POST" });
          toast(t("health.resetDone", { id }), "ok");
          await loadHealth();
          break;
        }
      }
    } catch (err) {
      toast(`${t("common.opFailed")}: ${friendlyError(err)}`, "err");
    }
  });
}

// ---------- init ----------
(async function init() {
  setTheme(getTheme());
  syncLangSelects();

  bindGlobalActions();
  bindProviderForm();
  bindCredentialForm();
  bindRouteForm();
  bindKeyForm();
  bindKeyEditModal();
  bindToolForm();
  bindSnippetModal();
  bindGroupModal();
  bindSettings();
  syncRouteModeFields();

  // Desktop mode hides logout (loopback is pre-authenticated)
  try {
    const { config } = await api("/admin/config");
    if (config && config.desktop_mode) {
      state.desktop = true;
      const lb = $("#logout-btn");
      if (lb) lb.style.display = "none";
    }
  } catch {}

  // session check
  try {
    await api("/admin/session");
  } catch {
    $("#gate").style.display = "";
    return;
  }
  $("#app").style.display = "";
  bindClickDelegation();

  // server-persisted language wins for the admin UI
  try {
    const data = await api("/admin/settings");
    const lang = (data.settings && data.settings.language) || "en";
    if (window.KeywayI18n) KeywayI18n.setLanguage(lang);
  } catch {}
  syncLangSelects();

  await render();
})();
