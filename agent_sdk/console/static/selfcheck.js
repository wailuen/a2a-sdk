/* selfcheck.js — runtime conformance probes (DESIGN.md §7 Self-check row).
 *
 * Pass/fail rows over the live surfaces:
 *  1. agent card: protocolVersion 0.3.0, url present, preferredTransport HTTP+JSON
 *  2. A2A message:send echo + tasks/get
 *  3. A2A message:stream final-frame check (first frame Task, last final:true)
 *  4. AG-UI: first frame is RUN_STARTED
 *  5. MCP: POST initialize + GET SSE channel + DELETE
 *  6. OAuth discovery chain: PRM + suffixed PRM + AS metadata with S256
 *  7. CORS preflight: OPTIONS /mcp → 204 + expose headers
 */

import { api, authHeaders, el, clear, postSse, readSse, uuid } from "./api.js";

export async function render(pane, ctx) {
  pane.appendChild(
    el(
      "div",
      { class: "page-head" },
      el(
        "div",
        null,
        el("h2", { class: "page-title" }, "Self-check"),
        el("p", { class: "page-sub" }, "Runtime conformance probes against this deployment's live protocol surfaces.")
      )
    )
  );

  const runBtn = el("button", { type: "button", class: "btn btn-primary" }, "Run all probes");
  const table = el("div", { class: "probe-rows" });
  pane.appendChild(el("div", { class: "page-actions probe-actions" }, runBtn));
  pane.appendChild(table);

  let info = null;
  try {
    info = await api("/admin/api/selfcheck-info");
  } catch (err) {
    if (ctx.onAuthError(err)) return;
    pane.appendChild(el("div", { class: "alert alert-err" }, `selfcheck-info failed: ${err.message || err}`));
    return;
  }
  const ep = info.endpoints;

  function row(name) {
    const status = el("span", { class: "badge" }, "pending");
    const detail = el("span", { class: "dim probe-detail" }, "");
    table.appendChild(el("div", { class: "probe-row" }, el("span", { class: "probe-name" }, name), status, detail));
    return {
      running() {
        status.className = "badge badge-warn";
        status.textContent = "running";
      },
      pass(text) {
        status.className = "badge badge-ok";
        status.textContent = "pass";
        detail.textContent = text || "";
      },
      fail(text) {
        status.className = "badge badge-err";
        status.textContent = "fail";
        detail.textContent = text || "";
      },
    };
  }

  const expect = (cond, okMsg, badMsg) => {
    if (!cond) throw new Error(badMsg);
    return okMsg;
  };

  /* ── probes ── */

  async function probeCard() {
    const resp = await fetch(ep.agent_card);
    expect(resp.ok, "", `HTTP ${resp.status}`);
    const card = await resp.json();
    expect(card.protocolVersion === info.a2a_protocol_version, "", `protocolVersion ${card.protocolVersion} ≠ ${info.a2a_protocol_version}`);
    expect(typeof card.url === "string" && card.url.length > 0, "", "card.url missing");
    expect(card.preferredTransport === "HTTP+JSON", "", `preferredTransport ${card.preferredTransport} ≠ HTTP+JSON`);
    return `v${card.protocolVersion} · ${card.url}`;
  }

  async function probeSend() {
    const body = {
      message: {
        kind: "message",
        role: "user",
        parts: [{ kind: "text", text: "selfcheck ping" }],
        messageId: uuid(),
      },
    };
    const resp = await fetch(ep.a2a_send, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    });
    expect(resp.ok, "", `HTTP ${resp.status}`);
    const result = await resp.json();
    expect(result.kind === "task" || result.kind === "message", "", `result kind ${result.kind} not task|message`);
    if (result.kind === "task") {
      expect(typeof result.contextId === "string" && result.contextId.length > 0, "", "task.contextId missing");
      const got = await fetch(ep.a2a_task.replace("{id}", encodeURIComponent(result.id)), { headers: authHeaders() });
      expect(got.ok, "", `tasks/get HTTP ${got.status}`);
      const task = await got.json();
      expect(task.id === result.id, "", "tasks/get returned a different task");
      return `task ${result.id} · tasks/get ok`;
    }
    return "synchronous Message result";
  }

  async function probeStream() {
    const body = {
      message: {
        kind: "message",
        role: "user",
        parts: [{ kind: "text", text: "selfcheck stream ping" }],
        messageId: uuid(),
      },
    };
    const resp = await postSse(ep.a2a_stream, body);
    expect(resp.ok, "", `HTTP ${resp.status}`);
    const ctype = resp.headers.get("Content-Type") || "";
    expect(ctype.includes("text/event-stream"), "", `Content-Type ${ctype}`);
    let first = null;
    let sawFinal = false;
    let frames = 0;
    await readSse(resp, ({ json }) => {
      if (!json) return;
      frames += 1;
      if (first === null) first = json;
      if (json.final === true) sawFinal = true;
    });
    expect(first !== null, "", "no frames received");
    expect(first.kind === "task", "", `first frame kind ${first.kind} ≠ task`);
    expect(sawFinal, "", "stream ended without a final:true frame");
    return `${frames} frames · first=Task · final:true seen`;
  }

  async function probeAgui() {
    const body = {
      threadId: uuid(),
      runId: uuid(),
      messages: [{ id: uuid(), role: "user", content: "selfcheck" }],
      state: {},
      tools: [],
      context: [],
      forwardedProps: {},
    };
    const controller = new AbortController();
    const resp = await fetch(ep.agui_run, {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json", Accept: "text/event-stream" }),
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    expect(resp.ok, "", `HTTP ${resp.status}`);
    const ctype = resp.headers.get("Content-Type") || "";
    expect(ctype.includes("text/event-stream"), "", `Content-Type ${ctype}`);
    let first = null;
    try {
      await readSse(resp, ({ json }) => {
        if (json && first === null) {
          first = json;
          controller.abort(); // first frame is all this probe needs
        }
      });
    } catch (err) {
      if (!(err && err.name === "AbortError") && first === null) throw err;
    }
    expect(first !== null, "", "no frames received");
    expect(first.type === "RUN_STARTED", "", `first frame ${first.type} ≠ RUN_STARTED`);
    return "first frame RUN_STARTED";
  }

  async function probeMcp() {
    // POST initialize
    const resp = await fetch(ep.mcp, {
      method: "POST",
      headers: authHeaders({
        "Content-Type": "application/json",
        Accept: "application/json, text/event-stream",
      }),
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "initialize",
        params: {
          protocolVersion: info.mcp_protocol_version,
          capabilities: {},
          clientInfo: { name: "selfcheck", version: "1.0" },
        },
      }),
    });
    expect(resp.ok, "", `initialize HTTP ${resp.status}`);
    const sessionId = resp.headers.get("Mcp-Session-Id");
    expect(!!sessionId, "", "no Mcp-Session-Id header on initialize");
    let initResult = null;
    if ((resp.headers.get("Content-Type") || "").includes("text/event-stream")) {
      await readSse(resp, ({ json }) => {
        if (json && json.id === 1) initResult = json;
      });
    } else {
      initResult = await resp.json();
    }
    expect(initResult && initResult.result && initResult.result.protocolVersion, "", "no protocolVersion in initialize result");

    // GET SSE channel (405 here breaks Claude Desktop — LRN-053)
    const controller = new AbortController();
    const get = await fetch(ep.mcp, {
      method: "GET",
      headers: authHeaders({
        Accept: "text/event-stream",
        "Mcp-Session-Id": sessionId,
        "MCP-Protocol-Version": initResult.result.protocolVersion,
      }),
      signal: controller.signal,
    });
    expect(get.ok, "", `GET /mcp HTTP ${get.status}`);
    const gtype = get.headers.get("Content-Type") || "";
    expect(gtype.includes("text/event-stream"), "", `GET Content-Type ${gtype}`);
    controller.abort();

    // DELETE session
    const del = await fetch(ep.mcp, {
      method: "DELETE",
      headers: authHeaders({ "Mcp-Session-Id": sessionId }),
    });
    expect(del.status === 204 || del.ok, "", `DELETE HTTP ${del.status}`);
    return `initialize ${initResult.result.protocolVersion} · GET SSE ok · DELETE ${del.status}`;
  }

  async function probeOauthDiscovery() {
    const prm = await fetch(ep.prm);
    expect(prm.ok, "", `PRM HTTP ${prm.status}`);
    const prmDoc = await prm.json();
    expect(typeof prmDoc.resource === "string" && prmDoc.resource.endsWith("/mcp"), "", `PRM resource ${prmDoc.resource} (want …/mcp)`);

    const prmSuffixed = await fetch(ep.prm_suffixed);
    expect(prmSuffixed.ok, "", `suffixed PRM HTTP ${prmSuffixed.status} (Claude probes this first)`);

    const as = await fetch(ep.as_metadata);
    expect(as.ok, "", `AS metadata HTTP ${as.status}`);
    const asDoc = await as.json();
    const methods = asDoc.code_challenge_methods_supported || [];
    expect(methods.includes("S256"), "", "code_challenge_methods_supported lacks S256");
    return `resource ${prmDoc.resource} · S256 advertised`;
  }

  async function probeCors() {
    const resp = await fetch(ep.mcp, {
      method: "OPTIONS",
      headers: {
        Origin: "https://claude.ai",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "authorization,content-type,mcp-session-id",
      },
    });
    expect(resp.status === 204, "", `preflight HTTP ${resp.status} ≠ 204`);
    const exposeResp = await fetch(ep.mcp, {
      method: "POST",
      headers: { Origin: "https://claude.ai", "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "ping" }),
    });
    const expose = (exposeResp.headers.get("Access-Control-Expose-Headers") || "").toLowerCase();
    expect(expose.includes("www-authenticate"), "", "Expose-Headers lacks WWW-Authenticate (discovery never starts)");
    expect(expose.includes("mcp-session-id"), "", "Expose-Headers lacks Mcp-Session-Id");
    return "preflight 204 · expose headers ok";
  }

  const probes = [
    ["Agent card (/.well-known/agent-card.json)", probeCard],
    ["A2A message:send + tasks/get", probeSend],
    ["A2A message:stream final-frame", probeStream],
    ["AG-UI first frame RUN_STARTED", probeAgui],
    ["MCP POST initialize + GET SSE + DELETE", probeMcp],
    ["OAuth discovery chain (PRM, suffixed PRM, AS metadata S256)", probeOauthDiscovery],
    ["CORS preflight OPTIONS /mcp", probeCors],
  ];

  async function runAll() {
    runBtn.disabled = true;
    clear(table);
    const rows = probes.map(([name]) => row(name));
    for (let i = 0; i < probes.length; i++) {
      const [, fn] = probes[i];
      rows[i].running();
      try {
        const detail = await fn();
        rows[i].pass(detail);
      } catch (err) {
        rows[i].fail(String(err.message || err));
      }
    }
    runBtn.disabled = false;
  }

  runBtn.addEventListener("click", runAll);
}
