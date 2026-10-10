/* console.js — app bootstrap + tab router (DESIGN.md §7).
 *
 * Tabs per the §7 table: Overview, Credentials, API Keys, Tools, Chat,
 * MCP, Self-check. Chat/MCP/Self-check live in their own modules; the four
 * data-form tabs are defined here.
 *
 * First-run flow (§6): probe GET /admin/api/keys — a 401 opens the auth
 * gate (paste a key, or mint the first admin key with the stdout bootstrap
 * token via X-Bootstrap-Token). Bearer lives in sessionStorage only.
 */

import {
  api,
  ApiError,
  clear,
  clearKey,
  el,
  fmtJson,
  fmtTime,
  getKey,
  setKey,
} from "./api.js";
import * as chat from "./chat.js";
import * as mcp from "./mcp.js";
import * as selfcheck from "./selfcheck.js";

const TABS = [
  { id: "overview", label: "Overview", render: renderOverview },
  { id: "credentials", label: "Credentials", render: renderCredentials },
  { id: "keys", label: "API Keys", render: renderKeys },
  { id: "tools", label: "Tools", render: renderTools },
  { id: "chat", label: "Chat", render: chat.render },
  { id: "mcp", label: "MCP", render: mcp.render },
  { id: "selfcheck", label: "Self-check", render: selfcheck.render },
];

const nav = document.getElementById("nav");
const main = document.getElementById("main");
const authStatus = document.getElementById("auth-status");
const signOutBtn = document.getElementById("btn-signout");
const toastNode = document.getElementById("toast");

let activeTab = "";
let toastTimer = null;

/* ── toast ── */

export function toast(message, kind) {
  toastNode.textContent = message;
  toastNode.className = `toast ${kind === "err" ? "toast-err" : "toast-ok"}`;
  toastNode.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toastNode.hidden = true;
  }, 4200);
}

/* ── router ── */

function buildNav() {
  clear(nav);
  for (const tab of TABS) {
    const btn = el("button", { type: "button", class: "nav-item", "data-tab": tab.id }, tab.label);
    btn.addEventListener("click", () => navigate(tab.id));
    nav.appendChild(btn);
  }
}

export function navigate(tabId) {
  const tab = TABS.find((t) => t.id === tabId) || TABS[0];
  activeTab = tab.id;
  if (location.hash !== `#${tab.id}`) {
    history.replaceState(null, "", `#${tab.id}`);
  }
  for (const btn of nav.querySelectorAll(".nav-item")) {
    btn.classList.toggle("active", btn.dataset.tab === tab.id);
  }
  clear(main);
  const pane = el("div", { class: "pane" });
  main.appendChild(pane);
  Promise.resolve(tab.render(pane, { toast, navigate, onAuthError })).catch((err) => {
    if (onAuthError(err)) return;
    clear(pane);
    pane.appendChild(el("div", { class: "alert alert-err" }, String(err.message || err)));
  });
}

/* ── auth gate ── */

const gate = document.getElementById("auth-gate");

function showAuthStatus() {
  const key = getKey();
  clear(authStatus);
  if (key) {
    authStatus.appendChild(el("span", { class: "dot dot-ok" }));
    authStatus.appendChild(el("span", { class: "mono" }, `${key.slice(0, 11)}…`));
    signOutBtn.hidden = false;
  } else {
    authStatus.appendChild(el("span", { class: "dot dot-warn" }));
    authStatus.appendChild(el("span", null, "not authenticated"));
    signOutBtn.hidden = true;
  }
}

function openGate() {
  if (!gate.open) gate.showModal();
}

function closeGate() {
  if (gate.open) gate.close();
  showAuthStatus();
}

/* Returns true (and opens the gate) when err is a 401. */
export function onAuthError(err) {
  if (err instanceof ApiError && err.status === 401) {
    openGate();
    return true;
  }
  return false;
}

async function probeAuth() {
  try {
    await api("/admin/api/keys");
    return true;
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return false;
    throw err;
  }
}

function wireGate() {
  const keyForm = document.getElementById("auth-key-form");
  const keyInput = document.getElementById("auth-key-input");
  const keyError = document.getElementById("auth-key-error");
  const bootForm = document.getElementById("auth-bootstrap-form");
  const bootInput = document.getElementById("auth-bootstrap-input");
  const bootLabel = document.getElementById("auth-bootstrap-label");
  const bootError = document.getElementById("auth-bootstrap-error");
  const minted = document.getElementById("auth-minted");
  const mintedValue = document.getElementById("auth-minted-value");
  const mintedContinue = document.getElementById("auth-minted-continue");

  gate.addEventListener("cancel", (e) => e.preventDefault()); // gate is mandatory

  keyForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    keyError.hidden = true;
    const candidate = keyInput.value.trim();
    if (!candidate) return;
    setKey(candidate);
    if (await probeAuth().catch(() => false)) {
      keyInput.value = "";
      closeGate();
      navigate(activeTab || "overview");
    } else {
      clearKey();
      keyError.textContent = "Key rejected (401). Check the value and try again.";
      keyError.hidden = false;
    }
  });

  bootForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    bootError.hidden = true;
    const token = bootInput.value.trim();
    if (!token) return;
    try {
      const resp = await fetch("/admin/api/keys", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Bootstrap-Token": token,
        },
        body: JSON.stringify({ label: bootLabel.value.trim() || "console-admin", admin: true }),
      });
      const data = await resp.json().catch(() => null);
      if (!resp.ok) {
        const detail = data && data.detail ? data.detail : `HTTP ${resp.status}`;
        throw new Error(detail);
      }
      setKey(data.plaintext);
      bootInput.value = "";
      mintedValue.textContent = data.plaintext; // shown once; store keeps the hash
      keyForm.hidden = true;
      bootForm.hidden = true;
      minted.hidden = false;
    } catch (err) {
      bootError.textContent = String(err.message || err);
      bootError.hidden = false;
    }
  });

  mintedContinue.addEventListener("click", () => {
    minted.hidden = true;
    keyForm.hidden = false;
    bootForm.hidden = false;
    closeGate();
    navigate(activeTab || "overview");
  });

  signOutBtn.addEventListener("click", () => {
    clearKey();
    showAuthStatus();
    openGate();
  });
}

/* ── shared tab scaffolding ── */

function pageHead(title, subtitle, ...actions) {
  return el(
    "div",
    { class: "page-head" },
    el("div", null, el("h2", { class: "page-title" }, title), el("p", { class: "page-sub" }, subtitle)),
    actions.length ? el("div", { class: "page-actions" }, actions) : null
  );
}

function section(title, ...children) {
  return el("section", { class: "section" }, el("h3", { class: "section-title" }, title), children);
}

function statusBadge(ok, okText, badText) {
  return el(
    "span",
    { class: `badge ${ok ? "badge-ok" : "badge-err"}` },
    ok ? okText : badText
  );
}

/* ── Overview tab ── */

async function renderOverview(pane) {
  pane.appendChild(pageHead("Overview", "Agent health, upstream checks and runtime limits."));
  const body = el("div", { class: "loading" }, "Loading…");
  pane.appendChild(body);

  const data = await api("/admin/api/overview");
  clear(body);
  body.className = "";

  const agentRows = [
    ["Name", data.agent.name],
    ["Version", data.agent.version],
    ["Base URL", data.agent.base_url],
    ["Mode", data.agent.dev_mode ? "development" : "production"],
    ["Bedrock region", data.model.bedrock_region || "—"],
    ["Bedrock model", data.model.bedrock_model_arn || "not configured"],
    ["CORS origins", (data.cors_origins || []).join(", ") || "—"],
  ];
  body.appendChild(
    section(
      "Agent",
      el(
        "table",
        { class: "tbl tbl-kv" },
        el(
          "tbody",
          null,
          agentRows.map(([k, v]) => el("tr", null, el("th", null, k), el("td", { class: "mono" }, v)))
        )
      )
    )
  );

  const adapterRows = (data.adapters || []).map((a) =>
    el(
      "tr",
      null,
      el("td", { class: "mono" }, a.source_name),
      el("td", null, statusBadge(a.healthy, "healthy", "unhealthy")),
      el("td", { class: "mono dim" }, (a.allowed_hosts || []).join(", "))
    )
  );
  body.appendChild(
    section(
      "Upstream sources",
      adapterRows.length
        ? el(
            "table",
            { class: "tbl" },
            el("thead", null, el("tr", null, el("th", null, "Source"), el("th", null, "Health"), el("th", null, "Allowed hosts"))),
            el("tbody", null, adapterRows)
          )
        : el("p", { class: "muted" }, "No source adapters registered.")
    )
  );

  const tasks = data.tasks || {};
  const limits = data.rate_limits || {};
  const statTiles = el(
    "div",
    { class: "tiles" },
    tile("Tasks in store", tasks.count === null || tasks.count === undefined ? "n/a" : String(tasks.count)),
    tile("Interrupted", tasks.interrupted === null || tasks.interrupted === undefined ? "n/a" : String(tasks.interrupted)),
    tile("API keys", String(data.keys ? data.keys.count : "—")),
    tile("Rate limit / identity", `${limits.per_identity_per_minute}/min`),
    tile("Rate limit / IP (unauth)", `${limits.per_ip_unauth_per_minute}/min`),
    tile("Bootstrap", data.bootstrap_armed ? "ARMED" : "disarmed")
  );
  body.appendChild(section("Runtime", statTiles));

  function tile(label, value) {
    return el("div", { class: "tile" }, el("div", { class: "tile-value mono" }, value), el("div", { class: "tile-label" }, label));
  }
}

/* ── Credentials tab ── */

async function renderCredentials(pane, ctx) {
  pane.appendChild(
    pageHead(
      "Credentials",
      "Forms generated from each adapter's CredentialField schema. Values are write-only: the API reports presence, never content."
    )
  );
  const body = el("div", { class: "loading" }, "Loading…");
  pane.appendChild(body);

  const data = await api("/admin/api/credentials");
  clear(body);
  body.className = "";

  const groups = [...(data.sources || [])];
  if (data.bedrock) {
    groups.push({
      source_name: data.bedrock.source_name,
      display_name: "Bedrock model credentials",
      fields: data.bedrock.fields,
    });
  }

  if (data.oauth_idp) {
    groups.push({
      source_name: data.oauth_idp.source_name,
      display_name: "IdP sign-in (AGENT_SDK_OAUTH_IDP)",
      fields: data.oauth_idp.fields,
    });
  }

  if (!groups.length) {
    body.appendChild(el("p", { class: "muted" }, "No credentialed sources registered."));
    return;
  }

  for (const group of groups) {
    const fields = group.fields || [];
    const rows = fields.map((field) => credentialRow(group.source_name, field, ctx));
    body.appendChild(
      section(
        group.display_name || group.source_name,
        fields.length ? el("div", { class: "cred-rows" }, rows) : el("p", { class: "muted" }, "No credential fields declared.")
      )
    );
  }

  function credentialRow(source, field, ctx2) {
    const input = el("input", {
      class: "input mono",
      type: field.secret ? "password" : "text",
      placeholder: field.set ? "configured — enter a new value to replace" : "not set",
      autocomplete: "off",
      spellcheck: "false",
    });
    const badge = statusBadge(field.set, "set", "unset");
    const saveBtn = el("button", { type: "button", class: "btn btn-sm btn-primary" }, "Save");
    const delBtn = el("button", { type: "button", class: "btn btn-sm btn-ghost", disabled: !field.set }, "Delete");

    saveBtn.addEventListener("click", async () => {
      const value = input.value;
      if (!value.trim()) {
        ctx2.toast("Enter a value first.", "err");
        return;
      }
      try {
        await api(`/admin/api/credentials/${encodeURIComponent(source)}/${encodeURIComponent(field.name)}`, {
          method: "PUT",
          body: { value },
        });
        input.value = "";
        input.placeholder = "configured — enter a new value to replace";
        badge.className = "badge badge-ok";
        badge.textContent = "set";
        delBtn.disabled = false;
        ctx2.toast(`${field.label} saved.`, "ok");
      } catch (err) {
        if (!ctx2.onAuthError(err)) ctx2.toast(String(err.message || err), "err");
      }
    });

    delBtn.addEventListener("click", async () => {
      try {
        await api(`/admin/api/credentials/${encodeURIComponent(source)}/${encodeURIComponent(field.name)}`, {
          method: "DELETE",
        });
        badge.className = "badge badge-err";
        badge.textContent = "unset";
        input.placeholder = "not set";
        delBtn.disabled = true;
        ctx2.toast(`${field.label} deleted.`, "ok");
      } catch (err) {
        if (!ctx2.onAuthError(err)) ctx2.toast(String(err.message || err), "err");
      }
    });

    return el(
      "div",
      { class: "cred-row" },
      el(
        "div",
        { class: "cred-meta" },
        el("span", { class: "cred-label" }, field.label),
        el("span", { class: "mono dim" }, `${field.name}${field.type === "url" ? " · url (https, public hosts only)" : ""}${field.required ? "" : " · optional"}`),
        field.help_text ? el("span", { class: "field-help" }, field.help_text) : null
      ),
      el("div", { class: "cred-controls" }, badge, input, saveBtn, delBtn)
    );
  }
}

/* ── API Keys tab ── */

async function renderKeys(pane, ctx) {
  pane.appendChild(
    pageHead("API Keys", "Mint and revoke bearer keys. Plaintext is shown exactly once at mint; storage keeps only a hash.")
  );

  const revealBox = el("div", { class: "key-reveal" });
  revealBox.hidden = true;
  const labelInput = el("input", { class: "input", type: "text", placeholder: "key label", value: "console", autocomplete: "off" });
  const adminCheck = el("input", { type: "checkbox", id: "key-admin-check" });
  const mintBtn = el("button", { type: "button", class: "btn btn-primary" }, "Mint key");
  const mintForm = el(
    "div",
    { class: "mint-form" },
    labelInput,
    el("label", { class: "check-label", for: "key-admin-check" }, adminCheck, " admin"),
    mintBtn
  );
  pane.appendChild(section("Mint a new key", mintForm, revealBox));

  const listWrap = el("div", { class: "loading" }, "Loading…");
  pane.appendChild(section("Existing keys", listWrap));

  async function refresh() {
    const data = await api("/admin/api/keys");
    clear(listWrap);
    listWrap.className = "";
    const rows = (data.keys || []).map((k) => {
      const revokeBtn = el("button", { type: "button", class: "btn btn-sm btn-danger" }, "Revoke");
      revokeBtn.addEventListener("click", async () => {
        try {
          await api(`/admin/api/keys/${encodeURIComponent(k.key_id)}`, { method: "DELETE" });
          ctx.toast(`Key ${k.prefix}… revoked.`, "ok");
          await refresh();
        } catch (err) {
          // last-admin protection surfaces here as a 400 with message
          if (!ctx.onAuthError(err)) ctx.toast(String(err.message || err), "err");
        }
      });
      return el(
        "tr",
        null,
        el("td", { class: "mono" }, `${k.prefix}…`),
        el("td", null, k.label),
        el("td", null, k.admin ? el("span", { class: "badge badge-ok" }, "admin") : el("span", { class: "badge" }, "standard")),
        el("td", { class: "dim" }, fmtTime(k.created_at)),
        el("td", { class: "dim" }, fmtTime(k.last_used)),
        el("td", null, revokeBtn)
      );
    });
    listWrap.appendChild(
      el(
        "table",
        { class: "tbl" },
        el(
          "thead",
          null,
          el(
            "tr",
            null,
            el("th", null, "Key"),
            el("th", null, "Label"),
            el("th", null, "Role"),
            el("th", null, "Created"),
            el("th", null, "Last used"),
            el("th", null, "")
          )
        ),
        el("tbody", null, rows)
      )
    );
  }

  mintBtn.addEventListener("click", async () => {
    try {
      const data = await api("/admin/api/keys", {
        method: "POST",
        body: { label: labelInput.value.trim() || "console", admin: adminCheck.checked },
      });
      clear(revealBox);
      revealBox.hidden = false;
      revealBox.appendChild(el("p", { class: "key-reveal-title" }, "Copy this key now — it is shown exactly once."));
      revealBox.appendChild(el("code", { class: "key-reveal-value mono" }, data.plaintext));
      ctx.toast("Key minted.", "ok");
      await refresh();
    } catch (err) {
      if (!ctx.onAuthError(err)) ctx.toast(String(err.message || err), "err");
    }
  });

  await refresh();
}

/* ── Tools tab ── */

async function renderTools(pane, ctx) {
  pane.appendChild(
    pageHead(
      "Tools",
      "Catalog from the ToolRegistry (single source of truth for card, MCP and console). Tier 1 = A2A + MCP; Tier 2 = A2A only."
    )
  );
  const body = el("div", { class: "loading" }, "Loading…");
  pane.appendChild(body);

  const data = await api("/admin/api/tools");
  clear(body);
  body.className = "";

  if (!(data.tools || []).length) {
    body.appendChild(el("p", { class: "muted" }, "No tools registered."));
    return;
  }

  for (const tool of data.tools) {
    body.appendChild(toolCard(tool));
  }

  function toolCard(tool) {
    const argsInput = el("textarea", { class: "input mono code-area", rows: "6", spellcheck: "false" });
    argsInput.value = fmtJson(tool.sample || {});
    const output = el("pre", { class: "code-output mono" });
    output.hidden = true;
    const tryBtn = el("button", { type: "button", class: "btn btn-sm btn-primary" }, "Try");
    const schemaPre = el("pre", { class: "code-output mono" }, fmtJson(tool.input_schema));
    const schemaWrap = el("details", { class: "tool-schema" }, el("summary", null, "input schema"), schemaPre);

    tryBtn.addEventListener("click", async () => {
      let args;
      try {
        args = argsInput.value.trim() ? JSON.parse(argsInput.value) : {};
      } catch {
        ctx.toast("Arguments must be valid JSON.", "err");
        return;
      }
      tryBtn.disabled = true;
      output.hidden = false;
      output.textContent = "Running…";
      try {
        const resp = await api(`/admin/api/tools/${encodeURIComponent(tool.name)}/try`, {
          method: "POST",
          body: args,
        });
        output.textContent = fmtJson(resp);
        output.classList.toggle("code-err", resp && resp.ok === false);
      } catch (err) {
        if (ctx.onAuthError(err)) return;
        output.textContent = String(err.message || err);
        output.classList.add("code-err");
      } finally {
        tryBtn.disabled = false;
      }
    });

    return el(
      "div",
      { class: "card tool-card" },
      el(
        "div",
        { class: "tool-head" },
        el("span", { class: "mono tool-name" }, tool.name),
        el("span", { class: `badge ${tool.tier === 1 ? "badge-ok" : ""}` }, `tier ${tool.tier}`)
      ),
      el("p", { class: "muted tool-desc" }, tool.description),
      schemaWrap,
      el("div", { class: "tool-try" }, argsInput, tryBtn),
      output
    );
  }
}

/* ── boot ── */

async function boot() {
  buildNav();
  wireGate();
  showAuthStatus();

  let authed = false;
  try {
    authed = await probeAuth();
  } catch (err) {
    toast(`Cannot reach the agent: ${err.message || err}`, "err");
  }
  if (!authed) openGate();

  const fromHash = (location.hash || "").replace(/^#/, "");
  navigate(TABS.some((t) => t.id === fromHash) ? fromHash : "overview");

  window.addEventListener("hashchange", () => {
    const id = (location.hash || "").replace(/^#/, "");
    if (id && id !== activeTab && TABS.some((t) => t.id === id)) navigate(id);
  });
}

boot();
