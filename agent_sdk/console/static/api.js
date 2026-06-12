/* api.js — fetch wrapper + shared console utilities (DESIGN.md §7).
 *
 * Invariants owned here:
 * - Bearer comes from sessionStorage only (header-borne, never cookies).
 * - el() builds DOM with createElement/createTextNode only — dynamic
 *   content can never become markup (the console origin holds the admin
 *   token; innerHTML with model output is the tested-forbidden pattern).
 * - readSse() is the one SSE parser shared by chat/mcp/selfcheck.
 */

const KEY_STORAGE = "agent_sdk_admin_key";

export function getKey() {
  try {
    return sessionStorage.getItem(KEY_STORAGE) || "";
  } catch {
    return "";
  }
}

export function setKey(key) {
  try {
    sessionStorage.setItem(KEY_STORAGE, key);
  } catch {
    /* sessionStorage unavailable: the key lives only in module state */
  }
}

export function clearKey() {
  try {
    sessionStorage.removeItem(KEY_STORAGE);
  } catch {
    /* ignore */
  }
}

export class ApiError extends Error {
  constructor(status, detail, body) {
    super(detail || `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
    this.body = body;
  }
}

export function authHeaders(extra) {
  const headers = Object.assign({}, extra);
  const key = getKey();
  if (key) headers["Authorization"] = `Bearer ${key}`;
  return headers;
}

/* JSON request against the console's own origin. Throws ApiError on !ok. */
export async function api(path, options = {}) {
  const { method = "GET", body, headers = {} } = options;
  const init = {
    method,
    headers: authHeaders(Object.assign({ Accept: "application/json" }, headers)),
  };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const resp = await fetch(path, init);
  if (resp.status === 204) return null;
  let data = null;
  const text = await resp.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!resp.ok) {
    const detail =
      data && typeof data === "object" && typeof data.detail === "string"
        ? data.detail
        : `HTTP ${resp.status}`;
    throw new ApiError(resp.status, detail, data);
  }
  return data;
}

/* ── SSE ──
 * Parses a fetch Response body into {event, data, json} frames. Handles
 * LF and CRLF separators and multi-line data fields. onFrame is called per
 * frame; returns when the stream ends or signal aborts.
 */
export async function readSse(response, onFrame) {
  if (!response.body) throw new Error("response has no body stream");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";

  const emit = (raw) => {
    let event = "";
    const dataLines = [];
    for (let line of raw.split(/\r?\n/)) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) {
        dataLines.push(line.startsWith("data: ") ? line.slice(6) : line.slice(5));
      }
    }
    if (!event && dataLines.length === 0) return;
    const data = dataLines.join("\n");
    let json = null;
    if (data) {
      try {
        json = JSON.parse(data);
      } catch {
        json = null;
      }
    }
    onFrame({ event, data, json });
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let m;
      while ((m = buf.match(/\r?\n\r?\n/))) {
        const raw = buf.slice(0, m.index);
        buf = buf.slice(m.index + m[0].length);
        emit(raw);
      }
    }
    buf += decoder.decode();
    if (buf.trim()) emit(buf);
  } finally {
    reader.releaseLock();
  }
}

/* POST that expects an SSE stream back; applies bearer + JSON body. */
export async function postSse(path, body, extraHeaders) {
  const resp = await fetch(path, {
    method: "POST",
    headers: authHeaders(
      Object.assign(
        { "Content-Type": "application/json", Accept: "text/event-stream" },
        extraHeaders
      )
    ),
    body: JSON.stringify(body),
  });
  return resp;
}

/* ── DOM helpers (text-node-only invariant) ── */

const BLOCKED_ATTRS = /^on/i;

export function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [name, value] of Object.entries(attrs)) {
      if (value === null || value === undefined || value === false) continue;
      if (BLOCKED_ATTRS.test(name)) continue; // no inline handlers, ever
      if (name === "class") node.className = String(value);
      else if (name === "text") node.textContent = String(value);
      else if (value === true) node.setAttribute(name, "");
      else node.setAttribute(name, String(value));
    }
  }
  append(node, children);
  return node;
}

function append(node, child) {
  if (child === null || child === undefined || child === false) return;
  if (Array.isArray(child)) {
    for (const c of child) append(node, c);
  } else if (child instanceof Node) {
    node.appendChild(child);
  } else {
    node.appendChild(document.createTextNode(String(child)));
  }
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

export function fmtJson(value) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export function fmtTime(epochSeconds) {
  if (!epochSeconds) return "—";
  try {
    return new Date(epochSeconds * 1000).toLocaleString();
  } catch {
    return "—";
  }
}
