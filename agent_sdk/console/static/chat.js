/* chat.js — A2A + AG-UI test client (DESIGN.md §7 Chat row, §5.1, §5.3).
 *
 * A2A mode: POST {base}/v1/message:stream — first SSE frame is the full
 * Task, then status-update / artifact-update frames; stop on final:true.
 * AG-UI mode: POST {base}/ag-ui/run with the FULL RunAgentInput (threadId,
 * runId, messages, state, tools, context, forwardedProps with
 * a2uiClientCapabilities tier "core+extended") and routes ALL frozen
 * CUSTOM events: AGENT_ARTIFACT, A2UI_UPDATE, AGENT_PROGRESS, AGENT_NOTE.
 *
 * Untrusted-output invariant: every model/tool string lands as a text node
 * (el() / textContent) — never markup. A raw SSE trace panel shows each
 * frame verbatim alongside the rendered transcript.
 */

import { el, clear, fmtJson, postSse, readSse, uuid } from "./api.js";
import { renderA2ui } from "./a2ui.js";

/* session state survives tab switches */
const state = {
  mode: "a2a",
  base: location.origin,
  // A2A continuity
  contextId: null,
  // AG-UI continuity (client owns history, §5.3)
  threadId: uuid(),
  aguiMessages: [],
  busy: false,
};

export function render(pane, ctx) {
  pane.appendChild(
    el(
      "div",
      { class: "page-head" },
      el(
        "div",
        null,
        el("h2", { class: "page-title" }, "Chat"),
        el("p", { class: "page-sub" }, "Test client for the A2A and AG-UI surfaces with live SSE trace and A2UI rendering.")
      )
    )
  );

  const transcript = el("div", { class: "chat-transcript" });
  const trace = el("pre", { class: "chat-trace mono" });
  const input = el("textarea", {
    class: "input mono chat-input",
    rows: "3",
    placeholder: "Message the agent… (Enter to send, Shift+Enter for newline)",
    spellcheck: "false",
  });
  const sendBtn = el("button", { type: "button", class: "btn btn-primary" }, "Send");
  const resetBtn = el("button", { type: "button", class: "btn btn-ghost btn-sm" }, "Reset session");

  const modeA2a = modeButton("A2A", "a2a");
  const modeAgui = modeButton("AG-UI", "agui");
  const baseInput = el("input", { class: "input mono chat-base", type: "text", value: state.base, spellcheck: "false" });
  baseInput.addEventListener("change", () => {
    state.base = baseInput.value.trim().replace(/\/$/, "") || location.origin;
  });

  function modeButton(label, mode) {
    const btn = el("button", { type: "button", class: "btn btn-sm seg" }, label);
    btn.addEventListener("click", () => {
      state.mode = mode;
      modeA2a.classList.toggle("active", mode === "a2a");
      modeAgui.classList.toggle("active", mode === "agui");
    });
    return btn;
  }
  modeA2a.classList.toggle("active", state.mode === "a2a");
  modeAgui.classList.toggle("active", state.mode === "agui");

  resetBtn.addEventListener("click", () => {
    state.contextId = null;
    state.threadId = uuid();
    state.aguiMessages = [];
    clear(transcript);
    clear(trace);
    systemLine("session reset");
    ctx.toast("Chat session reset.", "ok");
  });

  pane.appendChild(
    el(
      "div",
      { class: "chat-toolbar" },
      el("div", { class: "seg-group" }, modeA2a, modeAgui),
      baseInput,
      resetBtn
    )
  );
  pane.appendChild(
    el(
      "div",
      { class: "chat-grid" },
      el("div", { class: "chat-col" }, el("h3", { class: "section-title" }, "Transcript"), transcript),
      el("div", { class: "chat-col" }, el("h3", { class: "section-title" }, "Raw SSE trace"), trace)
    )
  );
  pane.appendChild(el("div", { class: "chat-composer" }, input, sendBtn));

  /* ── transcript helpers (text nodes only) ── */

  function bubble(role, textContent) {
    const node = el(
      "div",
      { class: `chat-msg ${role}` },
      el("div", { class: "chat-msg-role" }, role),
      el("div", { class: "chat-msg-body" }, textContent || "")
    );
    transcript.appendChild(node);
    transcript.scrollTop = transcript.scrollHeight;
    return node.querySelector(".chat-msg-body");
  }

  function systemLine(text) {
    transcript.appendChild(el("div", { class: "chat-system dim" }, text));
    transcript.scrollTop = transcript.scrollHeight;
  }

  function attach(node) {
    transcript.appendChild(node);
    transcript.scrollTop = transcript.scrollHeight;
  }

  function traceFrame(label, payload) {
    const line = typeof payload === "string" ? payload : fmtJson(payload);
    trace.appendChild(document.createTextNode(`── ${label}\n${line}\n\n`));
    trace.scrollTop = trace.scrollHeight;
  }

  function renderA2uiMessages(messages, fallbackText) {
    const { nodes, notes } = renderA2ui(messages, { fallbackText });
    nodes.forEach(attach);
    notes.forEach((n) => systemLine(`a2ui: ${n}`));
  }

  /* ── A2A mode (§5.1) ── */

  async function sendA2a(text) {
    const message = {
      kind: "message",
      role: "user",
      parts: [{ kind: "text", text }],
      messageId: uuid(),
      metadata: { a2uiClientCapabilities: { tier: "core+extended" } },
    };
    if (state.contextId) message.contextId = state.contextId;

    const resp = await postSse(`${state.base}/v1/message:stream`, { message }, {
      "X-A2A-Extensions": "https://a2ui.org/a2a-extension/a2ui/v0.9.1",
    });
    if (!resp.ok) {
      const body = await resp.text();
      traceFrame(`HTTP ${resp.status}`, body);
      systemLine(`stream request failed: HTTP ${resp.status}`);
      return;
    }

    let sawFinal = false;
    let agentBody = null;

    await readSse(resp, ({ event, json, data }) => {
      traceFrame(event || "data", json !== null ? json : data);
      if (!json) return;
      const kind = json.kind;
      if (kind === "task") {
        state.contextId = json.contextId || state.contextId;
        systemLine(`task ${json.id} · ${json.status ? json.status.state : "?"}`);
      } else if (kind === "message") {
        for (const part of json.parts || []) {
          if (part.kind === "text" && part.text) bubble("agent", part.text);
        }
        state.contextId = json.contextId || state.contextId;
      } else if (kind === "status-update") {
        const status = json.status || {};
        systemLine(`status: ${status.state || "?"}`);
        const msg = status.message;
        if (msg && Array.isArray(msg.parts)) {
          for (const part of msg.parts) {
            if (part.kind === "text" && part.text) {
              if (!agentBody) agentBody = bubble("agent", "");
              agentBody.appendChild(document.createTextNode(part.text));
            }
          }
        }
        if (json.final === true) sawFinal = true;
      } else if (kind === "artifact-update") {
        handleA2aArtifact(json.artifact);
      }
    });

    if (!sawFinal) systemLine("stream closed without final:true (re-subscribe per §5.2)");
  }

  function handleA2aArtifact(artifact) {
    if (!artifact) return;
    const parts = artifact.parts || [];
    const textPart = parts.find((p) => p.kind === "text");
    const fallbackText = textPart ? textPart.text : "";
    let renderedA2ui = false;
    for (const part of parts) {
      if (part.kind !== "data") continue;
      const mime = part.metadata ? part.metadata.mimeType : "";
      // canonical mime + accepted legacy form (§5.4)
      if (mime === "application/a2ui+json" || mime === "application/json+a2ui" || Array.isArray(part.data)) {
        renderA2uiMessages(part.data, fallbackText);
        renderedA2ui = true;
      } else {
        attach(el("pre", { class: "code-output mono" }, fmtJson(part.data)));
      }
    }
    if (!renderedA2ui && fallbackText) bubble("agent", fallbackText);
  }

  /* ── AG-UI mode (§5.3) ── */

  async function sendAgui(text) {
    state.aguiMessages.push({ id: uuid(), role: "user", content: text });
    const body = {
      threadId: state.threadId,
      runId: uuid(),
      messages: state.aguiMessages.slice(),
      state: {},
      tools: [],
      context: [],
      forwardedProps: { a2uiClientCapabilities: { tier: "core+extended" } },
    };

    const resp = await postSse(`${state.base}/ag-ui/run`, body);
    if (!resp.ok) {
      const respBody = await resp.text();
      traceFrame(`HTTP ${resp.status}`, respBody);
      systemLine(`run request failed: HTTP ${resp.status}`);
      return;
    }

    const textBuffers = new Map(); // messageId -> {node, content}
    let terminal = false;

    await readSse(resp, ({ json, data }) => {
      traceFrame(json && json.type ? json.type : "data", json !== null ? json : data);
      if (!json || !json.type) return;
      switch (json.type) {
        case "RUN_STARTED":
          systemLine(`run ${json.runId || ""} started`);
          break;
        case "TEXT_MESSAGE_START":
          textBuffers.set(json.messageId, { node: bubble("agent", ""), content: "" });
          break;
        case "TEXT_MESSAGE_CONTENT": {
          const buf = textBuffers.get(json.messageId);
          if (buf && json.delta) {
            buf.content += json.delta;
            buf.node.appendChild(document.createTextNode(json.delta));
            transcript.scrollTop = transcript.scrollHeight;
          }
          break;
        }
        case "TEXT_MESSAGE_END": {
          const buf = textBuffers.get(json.messageId);
          if (buf) {
            // client owns history: fold the assistant turn back in
            state.aguiMessages.push({ id: json.messageId, role: "assistant", content: buf.content });
          }
          break;
        }
        case "TOOL_CALL_START":
          systemLine(`tool call: ${json.toolCallName || json.toolCallId}`);
          break;
        case "TOOL_CALL_RESULT":
          systemLine(`tool result for ${json.toolCallId || "?"}`);
          break;
        case "STEP_STARTED":
          systemLine(`step ${json.stepName || ""} started`);
          break;
        case "STEP_FINISHED":
          systemLine(`step ${json.stepName || ""} finished`);
          break;
        case "CUSTOM":
          handleCustom(json);
          break;
        case "RUN_FINISHED":
          terminal = true;
          systemLine("run finished");
          if (json.outcome && json.outcome.type === "interrupt") {
            systemLine(`interrupted: ${fmtJson(json.outcome.interrupts || [])}`);
          }
          break;
        case "RUN_ERROR":
          terminal = true;
          systemLine(`run error: ${json.message || "unknown"}`);
          break;
        default:
          break; // STATE_SNAPSHOT/STATE_DELTA/etc — trace panel only
      }
    });

    if (!terminal) systemLine("stream closed without RUN_FINISHED/RUN_ERROR");
  }

  /* ALL frozen CUSTOM payload contracts (§5.3 table) */
  function handleCustom(frame) {
    const name = frame.name;
    const value = frame.value || {};
    if (name === "AGENT_ARTIFACT") {
      // {data_type, tool_name, data}
      attach(
        el(
          "div",
          { class: "card artifact-card" },
          el("div", { class: "a2ui-card-title" }, `artifact · ${value.data_type || "?"} · ${value.tool_name || "?"}`),
          el("pre", { class: "code-output mono" }, fmtJson(value.data))
        )
      );
    } else if (name === "A2UI_UPDATE") {
      // {messages: [...]}
      renderA2uiMessages(value.messages || [], "");
    } else if (name === "AGENT_PROGRESS") {
      // {message}
      systemLine(`progress: ${value.message || ""}`);
    } else if (name === "AGENT_NOTE") {
      // {note}
      systemLine(`note: ${value.note || ""}`);
    } else {
      systemLine(`unrecognized CUSTOM event: ${String(name)}`);
    }
  }

  /* ── send wiring ── */

  async function send() {
    const text = input.value.trim();
    if (!text || state.busy) return;
    input.value = "";
    state.busy = true;
    sendBtn.disabled = true;
    bubble("user", text);
    try {
      if (state.mode === "a2a") await sendA2a(text);
      else await sendAgui(text);
    } catch (err) {
      systemLine(`error: ${err.message || err}`);
    } finally {
      state.busy = false;
      sendBtn.disabled = false;
      input.focus();
    }
  }

  sendBtn.addEventListener("click", send);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
}
