/* mcp.js — MCP exerciser tab (DESIGN.md §7 MCP row, §5.5).
 *
 * Streamable-HTTP exerciser: initialize → notifications/initialized →
 * tools/list → tools/call against POST /mcp, honoring Mcp-Session-Id and
 * sending MCP-Protocol-Version on post-init requests. POST responses may be
 * application/json or text/event-stream — both are handled.
 *
 * OAuth walk-through (Claude.ai connector parity): DCR (RFC 7591) →
 * authorize URL with in-browser PKCE S256 (WebCrypto) → paste code →
 * token exchange → authenticated tools/list with the OAuth token.
 */

import { authHeaders, clear, el, fmtJson, getKey, readSse, uuid } from "./api.js";

const MCP_PROTOCOL_VERSION = "2025-06-18";

/* module state survives tab switches */
const state = {
  base: location.origin,
  sessionId: null,
  negotiatedVersion: null,
  tools: [],
  // oauth walkthrough
  clientId: null,
  redirectUri: null,
  codeVerifier: null,
  accessToken: null,
  rpcId: 0,
};

/* ── JSON-RPC over Streamable HTTP ── */

async function mcpPost(payload, opts = {}) {
  const headers = {
    "Content-Type": "application/json",
    Accept: "application/json, text/event-stream",
  };
  const token = opts.token !== undefined ? opts.token : getKey();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (state.sessionId && !opts.noSession) headers["Mcp-Session-Id"] = state.sessionId;
  if (state.negotiatedVersion && payload.method !== "initialize") {
    headers["MCP-Protocol-Version"] = state.negotiatedVersion;
  }
  const resp = await fetch(`${state.base}/mcp`, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });
  const sid = resp.headers.get("Mcp-Session-Id");
  if (sid) state.sessionId = sid;

  if (resp.status === 202) return { resp, result: null };
  const ctype = resp.headers.get("Content-Type") || "";
  let message = null;
  if (ctype.includes("text/event-stream")) {
    await readSse(resp, ({ json }) => {
      if (json && json.id === payload.id) message = json;
      else if (json && message === null && json.jsonrpc) message = json;
    });
  } else {
    message = await resp.json().catch(() => null);
  }
  if (!resp.ok) {
    const detail = message && message.error ? message.error.message : `HTTP ${resp.status}`;
    throw new Error(detail);
  }
  if (message && message.error) {
    throw new Error(`JSON-RPC ${message.error.code}: ${message.error.message}`);
  }
  return { resp, result: message ? message.result : null };
}

/* ── PKCE (S256, WebCrypto) ── */

function b64url(bytes) {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function pkcePair() {
  const verifier = b64url(crypto.getRandomValues(new Uint8Array(48)));
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return { verifier, challenge: b64url(new Uint8Array(digest)) };
}

/* ── tab ── */

export function render(pane, ctx) {
  pane.appendChild(
    el(
      "div",
      { class: "page-head" },
      el(
        "div",
        null,
        el("h2", { class: "page-title" }, "MCP"),
        el("p", { class: "page-sub" }, "Streamable-HTTP exerciser for /mcp plus the OAuth 2.1 connector walk-through.")
      )
    )
  );

  const log = el("pre", { class: "chat-trace mono mcp-log" });
  function logLine(label, payload) {
    log.appendChild(
      document.createTextNode(`── ${label}\n${payload === undefined ? "" : typeof payload === "string" ? payload : fmtJson(payload)}\n\n`)
    );
    log.scrollTop = log.scrollHeight;
  }

  /* ── session panel ── */

  const baseInput = el("input", { class: "input mono chat-base", type: "text", value: state.base, spellcheck: "false" });
  baseInput.addEventListener("change", () => {
    state.base = baseInput.value.trim().replace(/\/$/, "") || location.origin;
  });

  const sessionStatus = el("span", { class: "mono dim" }, state.sessionId ? `session ${state.sessionId}` : "no session");
  function refreshSessionStatus() {
    sessionStatus.textContent = state.sessionId
      ? `session ${state.sessionId} · ${state.negotiatedVersion || "?"}`
      : "no session";
  }
  refreshSessionStatus();

  const initBtn = el("button", { type: "button", class: "btn btn-sm btn-primary" }, "initialize");
  const listBtn = el("button", { type: "button", class: "btn btn-sm" }, "tools/list");
  const pingBtn = el("button", { type: "button", class: "btn btn-sm" }, "ping");
  const deleteBtn = el("button", { type: "button", class: "btn btn-sm btn-danger" }, "DELETE session");

  initBtn.addEventListener("click", () => run(initialize));
  listBtn.addEventListener("click", () => run(toolsList));
  pingBtn.addEventListener("click", () =>
    run(async () => {
      const { result } = await mcpPost({ jsonrpc: "2.0", id: ++state.rpcId, method: "ping" });
      logLine("ping result", result);
    })
  );
  deleteBtn.addEventListener("click", () => run(terminate));

  async function initialize(token) {
    state.sessionId = null;
    state.negotiatedVersion = null;
    const { resp, result } = await mcpPost(
      {
        jsonrpc: "2.0",
        id: ++state.rpcId,
        method: "initialize",
        params: {
          protocolVersion: MCP_PROTOCOL_VERSION,
          capabilities: {},
          clientInfo: { name: "agent-sdk-console", version: "1.0" },
        },
      },
      { token, noSession: true }
    );
    state.negotiatedVersion = result && result.protocolVersion ? result.protocolVersion : MCP_PROTOCOL_VERSION;
    logLine(`initialize → session ${resp.headers.get("Mcp-Session-Id") || state.sessionId || "?"}`, result);
    // spec: client must follow with notifications/initialized (expect 202)
    const note = await mcpPost({ jsonrpc: "2.0", method: "notifications/initialized" }, { token });
    logLine(`notifications/initialized → HTTP ${note.resp.status}`, undefined);
    refreshSessionStatus();
  }

  async function toolsList(token) {
    const { result } = await mcpPost({ jsonrpc: "2.0", id: ++state.rpcId, method: "tools/list" }, { token });
    state.tools = (result && result.tools) || [];
    logLine(`tools/list → ${state.tools.length} tool(s)`, result);
    rebuildToolSelect();
  }

  async function terminate() {
    if (!state.sessionId) {
      logLine("DELETE skipped", "no active session");
      return;
    }
    const resp = await fetch(`${state.base}/mcp`, {
      method: "DELETE",
      headers: authHeaders({ "Mcp-Session-Id": state.sessionId }),
    });
    logLine(`DELETE /mcp → HTTP ${resp.status}`, undefined);
    state.sessionId = null;
    state.negotiatedVersion = null;
    refreshSessionStatus();
  }

  async function run(fn, token) {
    try {
      await fn(token);
      refreshSessionStatus();
    } catch (err) {
      logLine("error", String(err.message || err));
      ctx.toast(String(err.message || err), "err");
    }
  }

  pane.appendChild(
    el(
      "section",
      { class: "section" },
      el("h3", { class: "section-title" }, "Session"),
      el("div", { class: "mcp-toolbar" }, baseInput, initBtn, pingBtn, listBtn, deleteBtn, sessionStatus)
    )
  );

  /* ── tools/call panel ── */

  const toolSelect = el("select", { class: "input mcp-tool-select" });
  const argsInput = el("textarea", { class: "input mono code-area", rows: "5", spellcheck: "false" });
  argsInput.value = "{}";
  const callBtn = el("button", { type: "button", class: "btn btn-sm btn-primary" }, "tools/call");

  function rebuildToolSelect() {
    clear(toolSelect);
    for (const tool of state.tools) {
      toolSelect.appendChild(el("option", { value: tool.name }, tool.name));
    }
    if (!state.tools.length) toolSelect.appendChild(el("option", { value: "" }, "run tools/list first"));
  }
  rebuildToolSelect();

  callBtn.addEventListener("click", () =>
    run(async () => {
      const name = toolSelect.value;
      if (!name) throw new Error("no tool selected — run tools/list first");
      let args;
      try {
        args = argsInput.value.trim() ? JSON.parse(argsInput.value) : {};
      } catch {
        throw new Error("arguments must be valid JSON");
      }
      const { result } = await mcpPost({
        jsonrpc: "2.0",
        id: ++state.rpcId,
        method: "tools/call",
        params: { name, arguments: args },
      });
      logLine(`tools/call ${name}${result && result.isError ? " → isError" : ""}`, result);
    })
  );

  pane.appendChild(
    el(
      "section",
      { class: "section" },
      el("h3", { class: "section-title" }, "tools/call"),
      el("div", { class: "mcp-call" }, toolSelect, argsInput, callBtn)
    )
  );

  /* ── OAuth walk-through ── */

  const oauthStatus = el("div", { class: "mono dim oauth-status" });
  function setOauthStatus() {
    const bits = [];
    if (state.clientId) bits.push(`client_id ${state.clientId}`);
    if (state.accessToken) bits.push(`token ${state.accessToken.slice(0, 10)}…`);
    oauthStatus.textContent = bits.join(" · ") || "not started";
  }
  setOauthStatus();

  const dcrBtn = el("button", { type: "button", class: "btn btn-sm" }, "1 · Register client (DCR)");
  const authorizeLink = el("a", { class: "btn btn-sm", target: "_blank", rel: "noopener noreferrer", hidden: true }, "2 · Open authorize URL");
  const authorizeBtn = el("button", { type: "button", class: "btn btn-sm" }, "2 · Build authorize URL");
  const codeInput = el("input", { class: "input mono", type: "text", placeholder: "paste ?code=… value here", spellcheck: "false" });
  const tokenBtn = el("button", { type: "button", class: "btn btn-sm" }, "3 · Exchange code for token");
  const oauthListBtn = el("button", { type: "button", class: "btn btn-sm" }, "4 · tools/list with OAuth token");

  dcrBtn.addEventListener("click", () =>
    run(async () => {
      state.redirectUri = `${location.origin}/admin/console`;
      const resp = await fetch(`${state.base}/oauth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          client_name: "console-walkthrough",
          redirect_uris: [state.redirectUri],
          grant_types: ["authorization_code", "refresh_token"],
          response_types: ["code"],
          token_endpoint_auth_method: "none",
        }),
      });
      const data = await resp.json().catch(() => null);
      if (!resp.ok) throw new Error((data && (data.error_description || data.detail)) || `DCR failed: HTTP ${resp.status}`);
      state.clientId = data.client_id;
      logLine("DCR registered", { client_id: data.client_id, redirect_uri: state.redirectUri });
      setOauthStatus();
    })
  );

  authorizeBtn.addEventListener("click", () =>
    run(async () => {
      if (!state.clientId) throw new Error("register a client first (step 1)");
      const { verifier, challenge } = await pkcePair();
      state.codeVerifier = verifier;
      const params = new URLSearchParams({
        response_type: "code",
        client_id: state.clientId,
        redirect_uri: state.redirectUri,
        code_challenge: challenge,
        code_challenge_method: "S256",
        state: uuid(),
        resource: `${state.base}/mcp`, // RFC 8707 canonical MCP URI (§5.5)
      });
      const url = `${state.base}/oauth/authorize?${params.toString()}`;
      authorizeLink.setAttribute("href", url);
      authorizeLink.hidden = false;
      logLine("authorize URL built (consent requires an admin API key)", url);
    })
  );

  tokenBtn.addEventListener("click", () =>
    run(async () => {
      const code = codeInput.value.trim();
      if (!code) throw new Error("paste the authorization code first");
      if (!state.codeVerifier) throw new Error("build the authorize URL first (step 2 generated the PKCE verifier)");
      const form = new URLSearchParams({
        grant_type: "authorization_code",
        code,
        redirect_uri: state.redirectUri,
        client_id: state.clientId,
        code_verifier: state.codeVerifier,
        // NOTE: resource deliberately NOT sent at the token request (§5.5)
      });
      const resp = await fetch(`${state.base}/oauth/token`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: form.toString(),
      });
      const data = await resp.json().catch(() => null);
      if (!resp.ok) throw new Error((data && (data.error_description || data.error)) || `token exchange failed: HTTP ${resp.status}`);
      state.accessToken = data.access_token;
      logLine("token exchanged", {
        token_type: data.token_type,
        expires_in: data.expires_in,
        access_token: `${String(data.access_token).slice(0, 10)}…`,
        refresh_token: data.refresh_token ? "(issued)" : undefined,
        scope: data.scope,
      });
      setOauthStatus();
    })
  );

  oauthListBtn.addEventListener("click", () =>
    run(async () => {
      if (!state.accessToken) throw new Error("exchange a token first (step 3)");
      await initialize(state.accessToken);
      await toolsList(state.accessToken);
      logLine("authenticated tools/list with OAuth token", "ok — oauth-kind identity accepted on /mcp");
    })
  );

  pane.appendChild(
    el(
      "section",
      { class: "section" },
      el("h3", { class: "section-title" }, "OAuth connector walk-through"),
      el(
        "p",
        { class: "muted" },
        "Mirrors the Claude.ai connector flow: DCR, PKCE S256 authorize (consent needs an admin API key), code-for-token exchange, then an authenticated MCP call."
      ),
      el("div", { class: "oauth-steps" }, dcrBtn, authorizeBtn, authorizeLink, codeInput, tokenBtn, oauthListBtn, oauthStatus)
    )
  );

  pane.appendChild(el("section", { class: "section" }, el("h3", { class: "section-title" }, "Log"), log));
}
