// Keyway admin UI. Session-cookie auth (login via /admin/login).
// Layout: single HTML page + hash-based view switching.
//   #                       → list of groups (default view)
//   #view=group&group_id=X → group detail (providers/routes/keys/tools)

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opts = {}) {
  const resp = await fetch(path, { credentials: "include", ...opts });
  let data = null;
  try { data = await resp.json(); } catch {}
  if (!resp.ok) {
    const detail = data && data.detail;
    const msg = typeof detail === "string" ? detail : (detail?.message || data?.message || `${resp.status}`);
    throw new Error(msg);
  }
  return data;
}

function setStatus(el, text, ok) {
  el.textContent = text;
  el.className = "status " + (ok ? "ok" : "err");
  setTimeout(() => { el.textContent = ""; el.className = "status"; }, 4000);
}

async function copyText(text, statusEl) {
  try {
    await navigator.clipboard.writeText(text);
    if (statusEl) setStatus(statusEl, "Copied", true);
    return true;
  } catch {
    if (statusEl) setStatus(statusEl, "Copy failed", false);
    return false;
  }
}

async function getBaseUrl() {
  if (getBaseUrl._cached) return getBaseUrl._cached;
  try {
    const { config } = await api("/admin/config");
    return (getBaseUrl._cached = (config && config.app_base_url) || window.location.origin);
  } catch {
    return (getBaseUrl._cached = window.location.origin);
  }
}

function buildKeyBaseUrl(base, format) {
  // OpenAI SDK uses base + /chat/completions; Anthropic SDK uses base (auto /v1/messages)
  // We expose bare /v1/ so:
  //   OpenAI base_url = http://host:port/v1
  //   Anthropic base_url = http://host:port  (SDK appends /v1/messages)
  return format === "anthropic"
    ? `${base.replace(/\/+$/, "")}`
    : `${base.replace(/\/+$/, "")}/v1`;
}

function showOutput(obj) {
  const el = $("#output");
  if (el) el.textContent = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);
}

// ---------- view routing ----------
function parseHash() {
  const h = (location.hash || "").replace(/^#/, "");
  if (!h) return { view: "list" };
  const params = new URLSearchParams(h);
  return { view: params.get("view") || "list", group_id: params.get("group_id") || "" };
}

function navigate(view, group_id) {
  const params = new URLSearchParams();
  if (view && view !== "list") params.set("view", view);
  if (group_id) params.set("group_id", group_id);
  const h = params.toString();
  location.hash = h ? "#" + h : "";
}

let currentGroupId = null;
let currentGroupMeta = null;
let cachedGroups = [];

async function render() {
  const { view, group_id } = parseHash();
  if (view === "group" && group_id) {
    await renderGroupDetail(group_id);
  } else {
    await renderGroupList();
  }
}

window.addEventListener("hashchange", render);

// ---------- group list view ----------
async function renderGroupList() {
  currentGroupId = null;
  const main = $("#list-view");
  const detail = $("#detail-view");
  if (!main) return;
  if (detail) detail.style.display = "none";
  main.style.display = "";

  let groups = [];
  try {
    const data = await api("/admin/llm/groups");
    groups = data.groups || [];
    cachedGroups = groups;
  } catch (e) {
    $("#group-list").innerHTML =
      `<div class="status err">Load failed: ${esc(e.message)}</div>`;
    return;
  }

  const html = groups.map(g => {
    const enabledChip = g.enabled
      ? `<span class="pill enabled">enabled</span>`
      : `<span class="pill disabled">disabled</span>`;
    const isDefault = g.group_id === "default";
    return `
      <div class="item" style="flex-direction:column;align-items:stretch;gap:0.4rem;">
        <div style="display:flex;gap:0.5rem;align-items:center;">
          <span class="id">${esc(g.group_id)}</span>
          ${enabledChip}
          ${isDefault ? '<span class="pill default">default</span>' : ""}
          <strong style="flex:1;min-width:0;">${esc(g.name)}</strong>
          <button data-action="open" data-gid="${esc(g.group_id)}">Edit</button>
          <button data-action="copy" data-gid="${esc(g.group_id)}" data-name="${esc(g.name)}">Copy</button>
          <button class="danger" data-action="delete" data-gid="${esc(g.group_id)}" data-default="${isDefault}" ${isDefault ? "disabled" : ""}>Delete</button>
        </div>
        <div style="color:var(--muted);font-size:0.78rem;padding-left:0.3rem;">
          ${g.provider_count} providers · ${g.route_count} routes · ${g.key_count} keys · ${g.tool_count} tools
        </div>
      </div>
    `;
  }).join("") || '<div style="color:var(--muted);font-size:0.85rem;">(no groups yet)</div>';
  $("#group-list").innerHTML = html;
}

async function copyGroupFlow(src_gid, src_name) {
  const newName = prompt(`Copy group "${src_name}" to new group, new name:`, `${src_name} (copy)`);
  if (!newName) return;
  let newGid = prompt(`New group_id (leave empty for auto):`, "");
  if (!newGid) newGid = undefined;
  try {
    const body = { new_name: newName };
    if (newGid) body.new_group_id = newGid;
    const data = await api(`/admin/llm/groups/${encodeURIComponent(src_gid)}/copy`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const issued = data.group.issued_keys || [];
    const keysHint = issued.length
      ? `\n\nNew group has ${issued.length} new key(s) (plaintext shown once):\n` +
        issued.map(k => `  - ${k.name || '(unnamed)'}: ${k.plaintext}`).join("\n")
      : "";
    alert(`Copied to new group: ${data.group.group_id}${keysHint}`);
    navigate("group", data.group.group_id);
  } catch (err) {
    alert("Copy failed: " + err.message);
  }
}

// ---------- group detail view ----------
async function renderGroupDetail(group_id) {
  currentGroupId = group_id;
  const main = $("#list-view");
  const detail = $("#detail-view");
  if (!detail) return;
  if (main) main.style.display = "none";
  detail.style.display = "";

  try {
    const data = await api(`/admin/llm/groups/${encodeURIComponent(group_id)}`);
    currentGroupMeta = data.group;
  } catch (e) {
    alert("Load group failed: " + e.message);
    navigate("list");
    return;
  }

  const enabledChip = currentGroupMeta.enabled
    ? `<span class="pill enabled">enabled</span>`
    : `<span class="pill disabled">disabled</span>`;
  const isDefault = group_id === "default";
  $("#detail-head-info").innerHTML = `
    <div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;">
      <button data-action="back" style="background:transparent;border:1px solid var(--border);padding:0.3rem 0.7rem;border-radius:5px;cursor:pointer;color:var(--text);">← Back</button>
      <h1 style="margin:0;font-size:1.5rem;font-weight:500;">${esc(currentGroupMeta.name)}</h1>
      <span class="id">${esc(group_id)}</span>
      ${enabledChip}
      ${isDefault ? '<span class="pill default">default</span>' : ""}
      <span style="color:var(--muted);font-size:0.82rem;">${currentGroupMeta.provider_count} providers · ${currentGroupMeta.route_count} routes · ${currentGroupMeta.key_count} keys · ${currentGroupMeta.tool_count} tools</span>
      <span style="flex:1;"></span>
      <button data-action="rename" style="background:transparent;border:1px solid var(--border);padding:0.3rem 0.7rem;border-radius:5px;cursor:pointer;color:var(--text);">Rename</button>
      <button data-action="toggle-enabled" style="background:transparent;border:1px solid var(--border);padding:0.3rem 0.7rem;border-radius:5px;cursor:pointer;color:var(--text);">${currentGroupMeta.enabled ? "Disable" : "Enable"}</button>
      <button data-action="copy-detail" style="background:transparent;border:1px solid var(--border);padding:0.3rem 0.7rem;border-radius:5px;cursor:pointer;color:var(--text);">Copy</button>
      <button data-action="delete-detail" style="background:transparent;border:1px solid #b00;color:#b00;padding:0.3rem 0.7rem;border-radius:5px;cursor:pointer;" ${isDefault ? "disabled" : ""}>Delete</button>
    </div>
  `;

  await Promise.all([
    loadGroupProviders(),
    loadGroupRoutes(),
    loadRouteProviderSelect(),
    loadGroupKeys(),
    loadGroupToolProviders(),
  ]);
}

// ---------- providers ----------
async function loadGroupProviders() {
  try {
    const { providers } = await api(`/admin/llm/groups/${encodeURIComponent(currentGroupId)}/providers`);
    $("#provider-list").innerHTML = providers.map(p => {
      const proto = p.protocol || "openai";
      const protoBadge = `<span class="pill ${proto}">${proto}</span>`;
      return `
      <div class="item">
        <span class="id">${esc(p.provider_id)}</span>
        <div class="grow"><div class="ellipsis"><strong>${esc(p.name)}</strong> — ${esc(p.base_url)} ${p.enabled ? "" : "(disabled)"}</div></div>
        ${protoBadge}
        <span style="color:var(--muted);font-size:0.78rem;">key: ${p.api_key_set ? "set" : "no"}</span>
        <button data-action="edit-provider" data-id="${esc(p.provider_id)}">Edit</button>
        <button data-action="test-provider" data-id="${esc(p.provider_id)}">Test</button>
        <button data-action="toggle-provider" data-id="${esc(p.provider_id)}" data-enabled="${p.enabled ? "1" : "0"}">${p.enabled ? "Disable" : "Enable"}</button>
        <button class="danger" data-action="delete-provider" data-id="${esc(p.provider_id)}">Delete</button>
      </div>`;
    }).join("") || "";
  } catch (e) { showOutput("load providers: " + e.message); }
}

function resetProviderForm() {
  const f = $("#provider-form"); f.reset();
  $("#provider-edit-id").value = "";
  $("#provider-submit").textContent = "Add Provider";
  $("#provider-cancel").style.display = "none";
  $("#provider-test").style.display = "none";
  $("#provider-id-input").readOnly = false;
  $("#provider-protocol").value = "openai";
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
    $("#provider-submit").textContent = "Save Changes";
    $("#provider-cancel").style.display = "";
    $("#provider-test").style.display = "";
    $("#provider-id-input").readOnly = true;
    setStatus($("#provider-status"), "Editing (fill key field to change; leave empty to keep)", true);
  } catch (e) { showOutput("edit provider: " + e.message); }
}

function bindProviderForm() {
  const form = $("#provider-form");
  if (!form) return;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target;
    const editId = $("#provider-edit-id").value;
    const fd = new FormData(f);
    const apiKey = fd.get("api_key");
    if (editId) {
      const body = {
        name: fd.get("name"), base_url: fd.get("base_url"),
        protocol: fd.get("protocol") || "openai", note: fd.get("note") || "",
      };
      if (apiKey) body.api_key = apiKey;
      try {
        await api(`/admin/llm/providers/${encodeURIComponent(editId)}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        });
        setStatus($("#provider-status"), "Updated", true);
      } catch (err) { setStatus($("#provider-status"), err.message, false); return; }
    } else {
      const body = {
        provider_id: fd.get("provider_id"), name: fd.get("name"),
        base_url: fd.get("base_url"), api_key: apiKey,
        protocol: fd.get("protocol") || "openai", note: fd.get("note") || "",
      };
      if (!apiKey) { setStatus($("#provider-status"), "API Key required", false); return; }
      try {
        await api(`/admin/llm/groups/${encodeURIComponent(currentGroupId)}/providers`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        });
        setStatus($("#provider-status"), "Added", true);
      } catch (err) { setStatus($("#provider-status"), err.message, false); return; }
    }
    resetProviderForm();
    await loadGroupProviders();
  });
  $("#provider-cancel")?.addEventListener("click", resetProviderForm);
  $("#provider-test")?.addEventListener("click", async () => {
    const id = $("#provider-edit-id").value;
    if (!id) return;
    try {
      const { test } = await api("/admin/llm/test", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider_id: id }),
      });
      setStatus($("#provider-status"), `${test.ok ? "OK" : "FAIL"}: ${test.message} (${test.latency_ms}ms)`, test.ok);
    } catch (e) { setStatus($("#provider-status"), "Test failed: " + e.message, false); }
  });
}

// ---------- routes ----------
async function loadGroupRoutes() {
  try {
    const { routes } = await api(`/admin/llm/groups/${encodeURIComponent(currentGroupId)}/routes`);
    $("#route-list").innerHTML = routes.map(r => `
      <div class="item">
        <span class="id">${esc(r.alias)}</span>
        <div class="grow"><div class="ellipsis"><strong>${esc(r.provider_id)}</strong> → ${esc(r.upstream_model)} ${r.enabled ? "" : "(disabled)"} ${r.upstream_path ? `[${esc(r.upstream_path)}]` : ""}</div></div>
        <button data-action="edit-route" data-rid="${esc(r.route_id)}">Edit</button>
        <button data-action="test-route" data-alias="${esc(r.alias)}">Test</button>
        <button data-action="toggle-route" data-id="${esc(r.route_id)}" data-enabled="${r.enabled ? "1" : "0"}">${r.enabled ? "Disable" : "Enable"}</button>
        <button class="danger" data-action="delete-route" data-id="${esc(r.route_id)}">Delete</button>
      </div>`).join("") || "";
  } catch (e) { showOutput("load routes: " + e.message); }
}

async function loadRouteProviderSelect() {
  try {
    const { providers } = await api(`/admin/llm/groups/${encodeURIComponent(currentGroupId)}/providers`);
    const sel = $("#route-provider-select");
    sel.innerHTML = providers.map(p =>
      `<option value="${esc(p.provider_id)}">${esc(p.provider_id)} — ${esc(p.name)}</option>`).join("");
  } catch (e) { showOutput("load providers for select: " + e.message); }
}

function resetRouteForm() {
  $("#route-form").reset();
  $("#route-edit-id").value = "";
  $("#route-submit").textContent = "Add Route";
  $("#route-cancel").style.display = "none";
  loadRouteProviderSelect();
}

async function editRoute(route_id) {
  try {
    const { route } = await api(`/admin/llm/routes/${encodeURIComponent(route_id)}`);
    const f = $("#route-form");
    f.elements["alias"].value = route.alias || "";
    await loadRouteProviderSelect();
    f.elements["provider_id"].value = route.provider_id || "";
    f.elements["upstream_model"].value = route.upstream_model || "";
    f.elements["upstream_path"].value = route.upstream_path || "";
    f.elements["enabled"].value = route.enabled ? "1" : "0";
    f.elements["note"].value = route.note || "";
    $("#route-edit-id").value = route.route_id;
    $("#route-submit").textContent = "Save Changes";
    $("#route-cancel").style.display = "";
  } catch (err) { showOutput("edit route: " + err.message); }
}

function bindRouteForm() {
  const form = $("#route-form");
  if (!form) return;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target;
    const editId = $("#route-edit-id").value;
    const fd = new FormData(f);
    if (editId) {
      const body = {
        alias: fd.get("alias"), provider_id: fd.get("provider_id"),
        upstream_model: fd.get("upstream_model"),
        upstream_path: fd.get("upstream_path") || "",
        enabled: fd.get("enabled") === "1", note: fd.get("note") || "",
      };
      try {
        await api(`/admin/llm/routes/${encodeURIComponent(editId)}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        });
        setStatus($("#route-status"), "Updated", true);
      } catch (err) { setStatus($("#route-status"), err.message, false); return; }
    } else {
      const body = {
        alias: fd.get("alias"), provider_id: fd.get("provider_id"),
        upstream_model: fd.get("upstream_model"),
        upstream_path: fd.get("upstream_path") || "",
        note: fd.get("note") || "",
      };
      try {
        await api(`/admin/llm/groups/${encodeURIComponent(currentGroupId)}/routes`, {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        });
        setStatus($("#route-status"), "Added", true);
      } catch (err) { setStatus($("#route-status"), err.message, false); return; }
    }
    resetRouteForm();
    await loadGroupRoutes();
  });
  $("#route-cancel")?.addEventListener("click", resetRouteForm);
}

// ---------- keys ----------
async function loadGroupKeys() {
  try {
    const { keys } = await api(`/admin/llm/groups/${encodeURIComponent(currentGroupId)}/keys`);
    $("#key-list").innerHTML = keys.map(k => `
      <div class="item">
        <span class="id">${esc(k.key_prefix)}...</span>
        <div class="grow"><div class="ellipsis">${esc(k.name)} ${k.expires_at ? `(expires ${esc(k.expires_at)})` : "(no expiry)"} ${k.enabled ? "" : "(disabled)"}</div></div>
        <span style="color:var(--muted);font-size:0.78rem;">last used: ${k.last_used_at ? esc(k.last_used_at) : "—"}</span>
        <button data-action="copy-plaintext" data-id="${esc(k.key_id)}">Copy Key</button>
        <button data-action="copy-baseurl" data-id="${esc(k.key_id)}" data-format="openai">OpenAI URL</button>
        <button data-action="copy-baseurl" data-id="${esc(k.key_id)}" data-format="anthropic">Anthropic URL</button>
        <button class="danger" data-action="delete-key" data-id="${esc(k.key_id)}">Delete</button>
      </div>`).join("") || "";
  } catch (e) { showOutput("load keys: " + e.message); }
}

function bindKeyForm() {
  const form = $("#key-form");
  if (!form) return;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = { name: fd.get("name") };
    const exp = fd.get("expires_at");
    if (exp) body.expires_at = exp;
    try {
      const data = await api(`/admin/llm/groups/${encodeURIComponent(currentGroupId)}/keys`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      setStatus($("#key-status"), "Created — plaintext & URLs below", true);
      $("#key-plaintext").textContent = data.plaintext;
      const base = await getBaseUrl();
      const openai = buildKeyBaseUrl(base, "openai");
      const anthropic = buildKeyBaseUrl(base, "anthropic");
      $("#key-result-baseurls").innerHTML = `
        <div style="display:flex;align-items:center;gap:0.5rem;font-size:0.78rem;margin-bottom:0.3rem;">
          <span style="font-family:'IBM Plex Mono',monospace;flex:1;word-break:break-all;">${esc(openai)}</span>
          <button type="button" data-copy-url="${esc(openai)}" style="font-size:0.72rem;padding:2px 8px;border:1px solid #b00;background:#fff;color:#b00;border-radius:4px;cursor:pointer;">Copy OpenAI URL</button>
        </div>
        <div style="display:flex;align-items:center;gap:0.5rem;font-size:0.78rem;">
          <span style="font-family:'IBM Plex Mono',monospace;flex:1;word-break:break-all;">${esc(anthropic)}</span>
          <button type="button" data-copy-url="${esc(anthropic)}" style="font-size:0.72rem;padding:2px 8px;border:1px solid #b00;background:#fff;color:#b00;border-radius:4px;cursor:pointer;">Copy Anthropic URL</button>
        </div>`;
      $("#key-result").style.display = "block";
      e.target.reset();
      await loadGroupKeys();
    } catch (err) { setStatus($("#key-status"), err.message, false); }
  });
  $("#key-result")?.addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-copy-url]");
    if (!btn) return;
    await copyText(btn.dataset.copyUrl, $("#key-status"));
  });
  $("#key-result-copy")?.addEventListener("click", () => {
    const v = $("#key-plaintext").textContent;
    if (v) copyText(v, $("#key-status"));
  });
}

// ---------- tool providers ----------
async function loadGroupToolProviders() {
  try {
    const { tool_providers } = await api(`/admin/llm/groups/${encodeURIComponent(currentGroupId)}/tool-providers`);
    $("#tool-list").innerHTML = tool_providers.map(t => `
      <div class="item">
        <span class="id">${esc(t.tool_id)}</span>
        <div class="grow"><div class="ellipsis">${esc(t.name)} ${t.enabled ? "" : "(disabled)"}</div></div>
        <span style="color:var(--muted);font-size:0.78rem;">key: ${t.api_key_set ? "set" : "no"}</span>
        <button data-action="toggle-tool" data-id="${esc(t.tool_id)}" data-enabled="${t.enabled ? "1" : "0"}">${t.enabled ? "Disable" : "Enable"}</button>
        <button class="danger" data-action="delete-tool" data-id="${esc(t.tool_id)}">Delete</button>
      </div>`).join("") || "";
  } catch (e) { showOutput("load tool providers: " + e.message); }
}

function bindToolForm() {
  const form = $("#tool-form");
  if (!form) return;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const body = Object.fromEntries(fd);
    body.enabled = true;
    try {
      await api(`/admin/llm/groups/${encodeURIComponent(currentGroupId)}/tool-providers`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      setStatus($("#tool-status"), "Added", true);
      e.target.reset();
      await loadGroupToolProviders();
    } catch (err) { setStatus($("#tool-status"), err.message, false); }
  });
}

// ---------- logs ----------
async function loadLogs() {
  const keyId = $("#log-key-select").value;
  if (!keyId) { $("#log-tbody").innerHTML = '<tr><td colspan="8" style="color:var(--muted);text-align:center;">Select a key first</td></tr>'; return; }
  try {
    const { logs } = await api(`/admin/llm/logs?api_key_id=${encodeURIComponent(keyId)}&limit=50`);
    if (!logs.length) { $("#log-tbody").innerHTML = '<tr><td colspan="8" style="color:var(--muted);text-align:center;">No records</td></tr>'; return; }
    $("#log-tbody").innerHTML = logs.map(l => `
      <tr>
        <td><span class="mono">${esc(l.created_at)}</span></td>
        <td><span class="mono">${esc(l.route_alias)}</span></td>
        <td><span class="mono">${esc(l.provider_id)}</span></td>
        <td><span class="mono">${esc(l.upstream_model)}</span></td>
        <td>${esc(l.status_code || "—")}</td>
        <td>${esc(l.latency_ms || "—")}ms</td>
        <td>${esc((l.request_tokens || 0) + (l.response_tokens || 0))} <span style="color:var(--muted);font-size:0.75rem;">(in ${l.request_tokens || 0} / out ${l.response_tokens || 0})</span></td>
        <td class="${l.error ? "err" : ""}">${esc((l.error || "").slice(0, 60))}</td>
      </tr>`).join("");
  } catch (e) { showOutput("load logs: " + e.message); }
}

async function populateLogKeySelect() {
  const sel = $("#log-key-select");
  let allKeys = [];
  try {
    const { groups } = await api("/admin/llm/groups");
    for (const g of groups) {
      const { keys } = await api(`/admin/llm/groups/${encodeURIComponent(g.group_id)}/keys`);
      allKeys.push(...keys.map(k => ({ ...k, group_id: g.group_id })));
    }
  } catch {}
  const cur = sel.value;
  sel.innerHTML = '<option value="">— Select key —</option>' + allKeys.map(k =>
    `<option value="${esc(k.key_id)}">${esc(k.key_prefix)}... (${esc(k.group_id)}/${esc(k.name)})</option>`).join("");
  if (cur) sel.value = cur;
}

function bindLogs() {
  $("#log-refresh")?.addEventListener("click", loadLogs);
  $("#log-key-select")?.addEventListener("change", loadLogs);
}

async function runE2e() {
  const btn = $("#e2e-run");
  btn.disabled = true;
  btn.textContent = "Testing…";
  setStatus($("#e2e-status"), "Probing every enabled route's upstream…", true);
  try {
    const data = await api("/admin/llm/e2e", { method: "POST" });
    const ok = data.summary && data.summary.startsWith("PASS");
    setStatus($("#e2e-status"), data.summary, ok);
    const grpResults = data.group_results || [];
    const html = grpResults.map(gr => {
      const rows = (gr.results || []).map(r => {
        const badge = r.ok
          ? `<span style="background:#dcfce7;color:#0a6;padding:2px 8px;border-radius:4px;font-size:0.78rem;">PASS</span>`
          : `<span style="background:#fee2e2;color:#b00;padding:2px 8px;border-radius:4px;font-size:0.78rem;">FAIL</span>`;
        return `<tr>
          <td><span class="mono">${esc(r.alias)}</span></td>
          <td>${esc(r.provider_id)} <span style="color:var(--muted);font-size:0.72rem;">(${esc(r.protocol)})</span></td>
          <td><span class="mono">${esc(r.upstream_model)}</span></td>
          <td>${badge}</td>
          <td>${r.latency_ms}ms · ${esc(r.message || "")}</td>
        </tr>`;
      }).join("");
      const provRows = (gr.provider_probes || []).map(p => {
        const badge = p.ok
          ? `<span style="background:#dcfce7;color:#0a6;padding:2px 8px;border-radius:4px;font-size:0.78rem;">PASS</span>`
          : `<span style="background:#fee2e2;color:#b00;padding:2px 8px;border-radius:4px;font-size:0.78rem;">FAIL</span>`;
        return `<tr>
          <td><span class="mono">${esc(p.provider_id)}</span></td>
          <td>${badge}</td>
          <td>${p.latency_ms}ms</td>
          <td style="font-size:0.78rem;">${esc(p.message || "")}</td>
        </tr>`;
      }).join("");
      return `
        <h4 style="margin:0.8rem 0 0.3rem;">Group ${esc(gr.group_id)} — ${esc(gr.group_name)} — ${gr.passed}/${gr.total}</h4>
        <table class="log-table">
          <thead><tr><th>alias</th><th>provider (proto)</th><th>upstream</th><th>status</th><th>detail</th></tr></thead>
          <tbody>${rows || '<tr><td colspan="5" style="color:var(--muted);text-align:center;">no enabled route</td></tr>'}</tbody>
        </table>
        <h4 style="margin:0.5rem 0 0.2rem;">Provider probes — ${gr.providers_passed}/${gr.providers_total}</h4>
        <table class="log-table">
          <thead><tr><th>provider</th><th>status</th><th>latency</th><th>detail</th></tr></thead>
          <tbody>${provRows || '<tr><td colspan="4" style="color:var(--muted);text-align:center;">no provider</td></tr>'}</tbody>
        </table>
      `;
    }).join("");
    $("#e2e-results").style.display = "block";
    $("#e2e-results").innerHTML = html || '<div style="color:var(--muted);font-size:0.85rem;">No enabled routes</div>';
  } catch (e) {
    setStatus($("#e2e-status"), "E2E failed: " + e.message, false);
  } finally {
    btn.disabled = false;
    btn.textContent = "Run E2E Test";
  }
}

// ---------- init ----------
(async function init() {
  // Check session
  try {
    await api("/admin/session");
  } catch (e) {
    $("#gate").style.display = "block";
    return;
  }
  $("#shell").style.display = "";

  // Global click delegate
  $("#shell").addEventListener("click", async (e) => {
    const btn = e.target.closest("button[data-action]");
    if (!btn) return;
    const action = btn.dataset.action;
    const gid = btn.dataset.gid;
    const id = btn.dataset.id;
    const alias = btn.dataset.alias;
    const routeId = btn.dataset.rid;
    const name = btn.dataset.name;
    const isDefault = btn.dataset.default === "true";
    const format = btn.dataset.format || "openai";
    try {
      if (action === "new-group") {
        await newGroupFlow();
      } else if (action === "open" && gid) {
        navigate("group", gid);
      } else if (action === "copy" && gid) {
        await copyGroupFlow(gid, name);
      } else if (action === "delete" && gid) {
        if (isDefault) { alert("default group cannot be deleted"); return; }
        if (!confirm(`Delete group ${gid}? All providers/routes/keys/tools will be cascade-deleted.`)) return;
        await api(`/admin/llm/groups/${encodeURIComponent(gid)}`, { method: "DELETE" });
        await renderGroupList();
      } else if (action === "back") {
        navigate("list");
      } else if (action === "rename") {
        await renameGroupFlow();
      } else if (action === "toggle-enabled") {
        await toggleEnabledFlow();
      } else if (action === "copy-detail") {
        await copyGroupFlow(currentGroupId, currentGroupMeta.name);
      } else if (action === "delete-detail") {
        if (!confirm(`Delete group ${currentGroupId}? All providers/routes/keys/tools will be cascade-deleted.`)) return;
        await api(`/admin/llm/groups/${encodeURIComponent(currentGroupId)}`, { method: "DELETE" });
        navigate("list");
      } else if (action === "edit-provider" && id) {
        await editProvider(id);
      } else if (action === "test-provider" && id) {
        const { test } = await api("/admin/llm/test", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ provider_id: id }),
        });
        alert(`${test.ok ? "PASS" : "FAIL"}\n${test.message} (${test.latency_ms}ms)`);
      } else if (action === "toggle-provider" && id) {
        const enabled = btn.dataset.enabled !== "1";
        await api(`/admin/llm/providers/${encodeURIComponent(id)}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }),
        });
        await loadGroupProviders();
      } else if (action === "delete-provider" && id) {
        if (!confirm(`Delete provider ${id}? Routes under it will be cascade-deleted.`)) return;
        await api(`/admin/llm/providers/${encodeURIComponent(id)}`, { method: "DELETE" });
        await loadGroupProviders();
      } else if (action === "edit-route" && routeId) {
        await editRoute(routeId);
      } else if (action === "test-route" && alias) {
        const { test } = await api("/admin/llm/test", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ alias }),
        });
        alert(`${test.ok ? "PASS" : "FAIL"}\n${test.message} (${test.latency_ms}ms)`);
      } else if (action === "toggle-route" && id) {
        const enabled = btn.dataset.enabled !== "1";
        await api(`/admin/llm/routes/${encodeURIComponent(id)}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }),
        });
        await loadGroupRoutes();
      } else if (action === "delete-route" && id) {
        if (!confirm(`Delete route ${id}?`)) return;
        await api(`/admin/llm/routes/${encodeURIComponent(id)}`, { method: "DELETE" });
        await loadGroupRoutes();
      } else if (action === "delete-key" && id) {
        if (!confirm("Delete this key? Clients using it will get 401 immediately.")) return;
        await api(`/admin/llm/keys/${encodeURIComponent(id)}`, { method: "DELETE" });
        await loadGroupKeys();
      } else if (action === "copy-plaintext" && id) {
        try {
          const { plaintext } = await api(`/admin/llm/keys/${encodeURIComponent(id)}/plaintext`);
          await copyText(plaintext, $("#key-status"));
        } catch (err) {
          setStatus($("#key-status"), "Failed to retrieve plaintext: " + err.message, false);
        }
      } else if (action === "copy-baseurl" && id) {
        const base = await getBaseUrl();
        await copyText(buildKeyBaseUrl(base, format), $("#key-status"));
      } else if (action === "delete-tool" && id) {
        if (!confirm(`Delete tool provider ${id}?`)) return;
        await api(`/admin/llm/tool-providers/${encodeURIComponent(id)}`, { method: "DELETE" });
        await loadGroupToolProviders();
      } else if (action === "toggle-tool" && id) {
        const enabled = btn.dataset.enabled !== "1";
        await api(`/admin/llm/tool-providers/${encodeURIComponent(id)}`, {
          method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }),
        });
        await loadGroupToolProviders();
      }
    } catch (err) {
      const hint = /401|unauthor/i.test(err.message) ? " — session expired, please re-login at /" : "";
      alert(`Operation failed: ${err.message}${hint}`);
    }
  });

  bindProviderForm();
  bindRouteForm();
  bindKeyForm();
  bindToolForm();
  bindLogs();
  $("#e2e-run")?.addEventListener("click", runE2e);
  $("#logout-link")?.addEventListener("click", async (e) => {
    e.preventDefault();
    try { await api("/admin/logout", { method: "POST" }); } catch {}
    window.location.href = "/";
  });
  await render();
  await populateLogKeySelect();
})();

async function newGroupFlow() {
  const gid = prompt("New group_id (slug, alphanumeric + _-):");
  if (!gid) return;
  let existing = cachedGroups.find(g => g.group_id === gid);
  if (!existing) {
    try {
      const { groups } = await api("/admin/llm/groups");
      cachedGroups = groups || [];
      existing = cachedGroups.find(g => g.group_id === gid);
    } catch {}
  }
  if (existing) {
    alert(`group_id "${gid}" already exists (group: ${existing.name}). Choose another or delete it first.`);
    return;
  }
  const name = prompt("Group name:") || gid;
  try {
    await api("/admin/llm/groups", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ group_id: gid, name }),
    });
    await renderGroupList();
  } catch (err) {
    const msg = /409|already exists/i.test(err.message)
      ? `group_id "${gid}" already exists.`
      : "Create failed: " + err.message;
    alert(msg);
  }
}

async function renameGroupFlow() {
  const newName = prompt("New name:", currentGroupMeta.name);
  if (!newName || newName === currentGroupMeta.name) return;
  try {
    await api(`/admin/llm/groups/${encodeURIComponent(currentGroupId)}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newName }),
    });
    await renderGroupDetail(currentGroupId);
  } catch (err) { alert("Rename failed: " + err.message); }
}

async function toggleEnabledFlow() {
  try {
    await api(`/admin/llm/groups/${encodeURIComponent(currentGroupId)}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !currentGroupMeta.enabled }),
    });
    await renderGroupDetail(currentGroupId);
  } catch (err) { alert("Toggle failed: " + err.message); }
}
