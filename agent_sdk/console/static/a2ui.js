/* a2ui.js — A2UI v0.9.1 Path-A renderer (DESIGN.md §7.1, §5.4).
 *
 * Contract:
 * - Surface registry keyed by surfaceId; createSurface / updateComponents /
 *   updateDataModel are folded ATOMICALLY per message array and each touched
 *   surface is painted ONCE per array — never repainted mid-array.
 * - deleteSurface applies POST-paint: the registry entry closes (further
 *   updates for that surfaceId are rejected) while the painted DOM persists
 *   as a transcript snapshot (show-then-close, the SDK-wide rule).
 * - Data bindings are JSON Pointer (RFC 6901) {"path": ...} references into
 *   the surface data model. RT-002: per spec, an omitted path AND the
 *   literal path "/" both mean "the whole data model" — "/" is NOT the
 *   RFC-6901-literal one-segment pointer to the child key "" here.
 *   pointerTokens() folds both to the empty token list.
 * - Renders the 14 FROZEN Standard Profile types; MarketBriefing is prose
 *   (no card chrome); unknown components bound to an object render a generic
 *   card (GH-215); other unknowns render the artifact's text fallback. Display-only: no input binding, no action dispatch.
 * - ChildList template expansion ({path, componentId} form) is out of scope
 *   for this display-only renderer.
 * - Untrusted-output invariant: every dynamic value lands via
 *   createTextNode/textContent or numeric SVG attributes — never markup.
 */

import { el } from "./api.js";

/* surfaceId -> {catalogId, components: [], dataModel: {}, node, closed} */
const surfaces = new Map();

/* ── JSON Pointer (RFC 6901) ── */

function isRelativePointer(pointer) {
  return typeof pointer === "string" && pointer !== "" && !pointer.startsWith("/");
}

function pointerTokens(pointer) {
  // A2UI v0.9.1: "Omit path or use '/' to replace the whole data model" —
  // "/" is a SPEC ALIAS for the omitted path, not the RFC-6901-literal
  // single empty-string token (which would address the child key ""). Both
  // fold to the empty token list so pointerSet/pointerGet treat them
  // identically (whole-document replace / whole-document read).
  if (pointer === "" || pointer === "/" || pointer === null || pointer === undefined) return [];
  // GH-215: a relative pointer ("name", "0/name") has no scope at this layer;
  // it must never fold to the model root. null = unresolvable.
  if (typeof pointer === "string" && !pointer.startsWith("/")) return null;
  return String(pointer)
    .split("/")
    .slice(1)
    .map((t) => t.replace(/~1/g, "/").replace(/~0/g, "~"));
}

const UNSAFE_TOKENS = new Set(["__proto__", "constructor", "prototype"]);

export function pointerGet(doc, pointer) {
  const tokens = pointerTokens(pointer);
  if (tokens === null) return undefined;
  let cur = doc;
  for (const token of tokens) {
    if (cur === null || cur === undefined) return undefined;
    if (UNSAFE_TOKENS.has(token)) return undefined;
    if (Array.isArray(cur)) cur = cur[Number(token)];
    else if (typeof cur === "object") cur = Object.hasOwn(cur, token) ? cur[token] : undefined;
    else return undefined;
  }
  return cur;
}

function pointerSet(doc, pointer, value) {
  const tokens = pointerTokens(pointer);
  if (tokens === null) return doc;
  if (!tokens.length) return value === undefined ? doc : value;
  if (tokens.some((t) => UNSAFE_TOKENS.has(t))) {
    throw new Error("unsafe JSON Pointer token rejected");
  }
  let cur = doc;
  for (let i = 0; i < tokens.length - 1; i++) {
    const token = tokens[i];
    const key = Array.isArray(cur) ? Number(token) : token;
    if (!Object.hasOwn(cur, key) || cur[key] === null || typeof cur[key] !== "object") {
      cur[key] = /^\d+$/.test(tokens[i + 1]) ? [] : {};
    }
    cur = cur[key];
  }
  const last = tokens[tokens.length - 1];
  if (value === undefined) {
    if (Array.isArray(cur)) cur.splice(Number(last), 1);
    else delete cur[last];
  } else if (Array.isArray(cur)) {
    cur[last === "-" ? cur.length : Number(last)] = value;
  } else {
    cur[last] = value;
  }
  return doc;
}

/* ── fold + paint ── */

/**
 * Process one A2UI message array (one artifact / one A2UI_UPDATE event).
 * Returns { nodes, notes }: nodes are newly painted (or repainted) surface
 * DOM elements for the transcript; notes are renderer diagnostics.
 */
export function renderA2ui(messages, opts = {}) {
  const fallbackText = opts.fallbackText || "";
  const list = Array.isArray(messages) ? messages : [messages];
  const touched = new Set();
  const deletions = [];
  const notes = [];

  // 1) fold the whole array atomically — no painting yet
  list.forEach((msg, index) => {
    try {
      foldMessage(msg);
    } catch (err) {
      notes.push(`message ${index} skipped: ${(err && err.message) || err}`);
    }
  });

  function foldMessage(msg) {
    if (!msg || typeof msg !== "object") return;
    if (!msg.version || typeof msg.version !== "string") {
      console.warn("[a2ui] message missing required version — skipped", msg);
      return;
    }
    if (msg.createSurface) {
      const { surfaceId, catalogId } = msg.createSurface;
      if (!surfaceId) return;
      const existing = surfaces.get(surfaceId);
      if (existing && existing.closed) {
        notes.push(`createSurface rejected: surface ${surfaceId} is closed`);
        return;
      } else if (existing && !existing.closed) {
        console.warn("[a2ui] protocol error: duplicate createSurface for open surface", surfaceId);
        return;
      }
      if (!existing) {
        surfaces.set(surfaceId, {
          catalogId: catalogId || "",
          components: [],
          _componentMap: new Map(),
          dataModel: {},
          node: null,
          closed: false,
        });
      }
      touched.add(surfaceId);
    } else if (msg.updateComponents) {
      const { surfaceId, components } = msg.updateComponents;
      const entry = surfaces.get(surfaceId);
      if (!entry || entry.closed) {
        notes.push(`updateComponents dropped: unknown/closed surface ${surfaceId}`);
        return;
      }
      if (!entry._componentMap) entry._componentMap = new Map();
      if (Array.isArray(components)) {
        for (const c of components) {
          if (c && c.id !== undefined) entry._componentMap.set(c.id, c);
        }
      }
      entry.components = [...entry._componentMap.values()];
      touched.add(surfaceId);
    } else if (msg.updateDataModel) {
      const { surfaceId, path } = msg.updateDataModel;
      const entry = surfaces.get(surfaceId);
      if (!entry || entry.closed) {
        notes.push(`updateDataModel dropped: unknown/closed surface ${surfaceId}`);
        return;
      }
      // Absent "value" key means delete; explicit null means set to null.
      if (isRelativePointer(path)) {
        notes.push(`updateDataModel rejected: relative path ${JSON.stringify(path)} has no scope`);
        return;
      }
      const value = "value" in msg.updateDataModel ? msg.updateDataModel.value : undefined;
      entry.dataModel = pointerSet(entry.dataModel, path || "", value);
      touched.add(surfaceId);
    } else if (msg.deleteSurface) {
      const { surfaceId } = msg.deleteSurface;
      if (surfaceId) deletions.push(surfaceId);
    }
  }

  // 2) paint each touched surface exactly once
  const nodes = [];
  for (const surfaceId of touched) {
    const entry = surfaces.get(surfaceId);
    if (!entry || entry.closed) continue;
    let painted;
    try {
      painted = paintSurface(entry, fallbackText, notes);
    } catch (err) {
      notes.push(`surface ${surfaceId} paint failed: ${(err && err.message) || err}`);
      painted = fallbackNode(fallbackText, `render error for surface ${surfaceId}`);
    }
    if (entry.node && entry.node.parentNode) {
      entry.node.replaceWith(painted); // repaint in place (same transcript slot)
    } else {
      nodes.push(painted);
    }
    entry.node = painted;
  }

  // 3) deleteSurface post-paint: close the registry entry; DOM persists
  for (const surfaceId of deletions) {
    const entry = surfaces.get(surfaceId);
    if (entry) {
      entry.closed = true;
      surfaces.delete(surfaceId); // painted node persists as a snapshot
    }
  }

  return { nodes, notes };
}

function paintSurface(entry, fallbackText, notes) {
  const root = entry.components.find((c) => c && c.id === "root");
  if (!root) {
    return fallbackNode(fallbackText, entry.components.length ? "surface has no root component" : "surface has no components");
  }
  const binding = root.data && root.data.path !== undefined ? root.data.path : null;
  if (isRelativePointer(binding)) {
    notes.push(`root binding rejected: relative path ${JSON.stringify(binding)} has no scope`);
    return fallbackNode(fallbackText, "relative data path rejected");
  }
  const value = binding !== null ? pointerGet(entry.dataModel, binding) : entry.dataModel;
  let renderer = Object.prototype.hasOwnProperty.call(RENDERERS, root.component) ? RENDERERS[root.component] : null;
  if (!renderer) {
    const resolvedValue = value === undefined ? null : value;
    if (resolvedValue === null || typeof resolvedValue !== "object" || Array.isArray(resolvedValue)) {
      notes.push(`unknown component ${String(root.component)} — text fallback rendered`);
      return fallbackNode(fallbackText, `unknown component: ${String(root.component)}`);
    }
    notes.push(`unknown component ${String(root.component)} — generic renderer used`);
    const name = root.component;
    renderer = (data) => renderGeneric(name, data);
  }
  try {
    const resolved = value === undefined ? {} : value;
    const node = renderer(resolved);
    node.classList.add("a2ui-surface");
    appendMetadataFootnote(node, resolved);
    return node;
  } catch (err) {
    notes.push(`renderer ${root.component} failed: ${err.message || err}`);
    return fallbackNode(fallbackText, `renderer error for ${String(root.component)}`);
  }
}

/**
 * Render the SDK-wide `metadata` envelope once, for every STRUCTURED
 * component type (13 of the 14 — see the MarketBriefing note below).
 *
 * RT-004: `metadata` is declared on `ContentModel` itself, so no per-component
 * renderer owns it — and none of the 14 read it, which made the console blind
 * to the whole GH-63 disclosure envelope. That is not a cosmetic gap: with
 * `FundPerformance.fundName` removed (GH-149), the CHANGELOG's own migration
 * callout names `metadata={"fund": "Fund III"}` as a supported way to carry
 * fund identity, and the console is the renderer `/acceptance --ux` inspects.
 * Without this, an agent that follows that instruction sees N cards all titled
 * the fixed string "Fund performance" with nothing to tell them apart.
 *
 * Applied at the single dispatch point rather than inside `card()`, which
 * receives only (title, subtitle, children) and never the data — one call site
 * covers 13 of the 14 renderers plus every future domain card, mirroring
 * `ContentModel.to_plain_text()` appending `_metadata_suffix()` once on the
 * base class for the text fallback.
 *
 * RT-006: MarketBriefing is a genuine exception, not a bug to fix here.
 * translator.py's `translate()` binds MarketBriefing's A2UI surface value to
 * `payload.to_markdown()` — a bare markdown STRING — instead of `payload.wire()`,
 * and `to_markdown()` is documented (content_types.py) to deliberately stay
 * "clean" of the metadata suffix, unlike `to_plain_text()`. So the console's
 * data model for a MarketBriefing surface never contains a `metadata` key —
 * there is nothing here to read, in JS or otherwise, without changing that
 * locked wire contract. The disclosure envelope still reaches callers through
 * `to_plain_text()` (the A2A TextPart and the MCP `tools/call` text) — it is
 * only this on-canvas footnote that a prose card cannot carry.
 */
function appendMetadataFootnote(node, data) {
  // See the MarketBriefing note above: its bound value is a bare markdown
  // string, never an object, so it never reaches past this guard.
  if (!data || typeof data !== "object" || Array.isArray(data)) return;
  const meta = data.metadata;
  if (!meta || typeof meta !== "object" || Array.isArray(meta)) return;
  const entries = Object.entries(meta);
  if (!entries.length) return;

  // RT-008/RT-010: metadata is caller-/tool-supplied (RT-A06), so it must
  // carry the SAME bounds as content_types.py's _metadata_suffix() --
  // per-field control-char strip + 256-char cap
  // (_METADATA_SUFFIX_FIELD_MAX_LEN), and a 4096-char cap on the assembled
  // footnote as a whole (_METADATA_SUFFIX_MAX_LEN) -- otherwise a metadata
  // dict with thousands of keys or embedded C0/C1 control chars renders
  // unbounded in the console.
  //
  // RT-010: the 4096 budget below is spent against the per-entry length
  // Python's _metadata_suffix() assembles -- "\n" + key + "=" + value, 2
  // separator chars -- not against this console's own "key: value" display
  // string, even though both happen to carry 2 separator chars too (and so
  // land at an identical cutoff for the same string-valued metadata dict --
  // cross-checked entry-for-entry against the real _metadata_suffix() in
  // tests/test_rt010_metadata_footnote_budget_matches_metadata_suffix.py).
  // Pinning the budget arithmetic to Python's literal formula, rather than
  // to whatever this console happens to display, means a future change to
  // the ": " display separator can't silently desync the two budgets by
  // changing `rendered.length` out from under this comment's guarantee.
  // This is a length/count parity, not a content one: a value that renders
  // to a DIFFERENT string per language (null here is "—" vs Python's
  // str(None) == "None"; an object goes through JSON.stringify here vs
  // Python's dict repr there) can still shift where the shared budget runs
  // out, since the two sides are then spending it on different content.
  // RT-006: byte-matches Python's sanitize_text (agent_sdk/common/redact.py,
  // C-007) -- `s[:max_len].translate(...)` -- which slices to max_len FIRST
  // and never appends an ellipsis. Stripping before truncating (as this used
  // to) can let a control char collapse into a space that then survives past
  // where sanitize_text would have already cut the string, and the trailing
  // "…" pushed the rendered field to 257 chars against Python's hard 256 cap.
  const FIELD_MAX_LEN = 256;
  const SUFFIX_MAX_LEN = 4096;
  // RT-011 (debug round 6): the truncation counts CODE POINTS, not UTF-16 code
  // units, because Python's `s[:256]` counts code points. `s.slice(0, 256)`
  // counts code units, so every non-BMP character (emoji, astral CJK) is 2
  // units to JS and 1 char to Python: a 256-emoji value is cut to 128 emoji
  // here against Python's 256, the two sides then spend the shared 4096
  // SUFFIX_MAX_LEN budget at different rates, and the "byte-matches
  // sanitize_text" claim above silently stops holding. `slice` can also cut
  // between a surrogate pair and leave a lone surrogate. Array.from() iterates
  // by code point, so both problems go away together.
  const sanitize = (s) =>
    Array.from(s).slice(0, FIELD_MAX_LEN).join("").replace(/[\x00-\x1f\x7f-\x9f]/g, " ");

  const row = el("div", { class: "dim a2ui-meta" });
  let budget = SUFFIX_MAX_LEN;
  for (const [k, v] of entries) {
    if (budget <= 0) break;
    // Untrusted-output invariant: metadata is caller-/tool-supplied, so every
    // key and value lands as a text node (el() uses createTextNode), never
    // markup. Objects are JSON-stringified rather than rendered as [object
    // Object]; a cyclic value degrades to the placeholder instead of throwing
    // out of the renderer (which paintSurface would turn into a fallback node,
    // losing the whole card over a footnote).
    let text;
    if (v === null || v === undefined) {
      text = "—";
    } else if (typeof v === "object") {
      try {
        text = JSON.stringify(v);
      } catch (err) {
        text = "(unserializable)";
      }
    } else {
      text = String(v);
    }
    const key = sanitize(String(k));
    const value = sanitize(text);
    const rendered = `${key}: ${value}`;
    // Budget spend mirrors "\n" + key + "=" + value (_metadata_suffix()'s own
    // per-entry length), not rendered.length -- see the RT-010 comment above.
    // RT-011: both the length AND the final slice below must count CODE
    // POINTS, not UTF-16 code units -- same reason as the sanitize() fix
    // above. key/value already passed through sanitize()'s Array.from() cap,
    // but they can still hold non-BMP characters (a 256-emoji value stays
    // 256 code points / 512 UTF-16 units after that cap), so `.length` here
    // would spend the shared 4096 SUFFIX_MAX_LEN budget roughly twice as fast
    // as Python's code-point-counting len() once several such entries are
    // rendered -- desyncing which entries survive long before FIELD_MAX_LEN
    // is ever reached. Array.from(...).length / slicing by code point keeps
    // the running budget code-point-for-code-point identical to Python's.
    const keyLen = Array.from(key).length;
    const valueLen = Array.from(value).length;
    const pythonEntryLen = 1 + keyLen + 1 + valueLen;
    row.appendChild(
      el("span", { class: "a2ui-meta-item" }, Array.from(rendered).slice(0, budget).join(""))
    );
    budget -= pythonEntryLen;
  }
  node.appendChild(row);
}

function fallbackNode(fallbackText, reason) {
  const node = el("div", { class: "a2ui-surface a2ui-fallback" });
  if (fallbackText) {
    for (const para of String(fallbackText).split(/\n/)) {
      node.appendChild(el("div", { class: "a2ui-fallback-line" }, para));
    }
  } else {
    node.appendChild(el("div", { class: "dim" }, reason));
  }
  return node;
}

/* ── row cap (GH-215): one constant for every list/table renderer ── */

export const MAX_ROWS = 100;

function capRows(items) {
  return items.length > MAX_ROWS ? items.slice(0, MAX_ROWS) : items;
}

function moreNote(items) {
  const extra = items.length - MAX_ROWS;
  return extra > 0 ? el("div", { class: "dim a2ui-more" }, `${extra} more`) : null;
}

/* ── generic data-driven renderer for components with no dedicated one ── */

function titleFromComponent(name) {
  return String(name)
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .trim();
}

function isScalar(v) {
  return v === null || v === undefined || typeof v !== "object";
}

function scalarText(v) {
  if (v === null || v === undefined) return "—";
  return typeof v === "number" ? fmtNum(v) : String(v);
}

function compactText(v) {
  if (isScalar(v)) return scalarText(v);
  let text;
  try {
    text = Array.isArray(v) && v.every(isScalar) ? v.map(scalarText).join(", ") : JSON.stringify(v);
  } catch (_e) {
    text = "(unserializable)";
  }
  return text.length > 200 ? `${text.slice(0, 200)}…` : text;
}

function genericTable(rows) {
  const columns = [];
  for (const r of rows) {
    for (const [k, v] of Object.entries(r)) {
      if (isScalar(v) && !columns.includes(k) && columns.length < 8) columns.push(k);
    }
  }
  const shown = capRows(rows);
  return el(
    "table",
    { class: "tbl a2ui-table" },
    el("thead", null, el("tr", null, columns.map((c) => el("th", null, c)))),
    el(
      "tbody",
      null,
      shown.map((r) =>
        el("tr", null, columns.map((c) => el("td", { class: typeof r[c] === "number" ? "mono" : null }, scalarText(r[c]))))
      )
    )
  );
}

function renderGeneric(componentName, data) {
  const scalarRows = [];
  const sections = [];
  for (const [key, value] of Object.entries(data)) {
    if (key === "metadata") continue; // rendered once by appendMetadataFootnote
    const isRowArray =
      Array.isArray(value) && value.length > 0 && value.every((x) => x && typeof x === "object" && !Array.isArray(x));
    if (isRowArray) {
      sections.push(el("div", { class: "a2ui-card-sub" }, key), genericTable(value), moreNote(value));
    } else {
      scalarRows.push([key, compactText(value)]);
    }
  }
  const children = [];
  if (scalarRows.length) {
    children.push(
      el(
        "table",
        { class: "tbl tbl-kv" },
        el("tbody", null, scalarRows.map(([k, v]) => el("tr", null, el("th", null, k), el("td", null, v))))
      )
    );
  }
  children.push(...sections);
  const raw = el("details", { class: "a2ui-raw" }, el("summary", null, "Raw JSON"));
  const pre = el("pre", { class: "a2ui-json" });
  pre.appendChild(document.createTextNode(JSON.stringify(data, null, 2)));
  raw.appendChild(pre);
  children.push(raw);
  return card(titleFromComponent(componentName) || "Details", null, ...children);
}

/* ── shared bits ── */

const SVG_NS = "http://www.w3.org/2000/svg";

function svg(tag, attrs, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v !== null && v !== undefined) node.setAttribute(k, String(v));
    }
  }
  for (const child of children) {
    if (child) node.appendChild(child);
  }
  return node;
}

function svgText(x, y, content, cls, anchor) {
  const t = svg("text", { x, y, class: cls || "a2ui-svg-label", "text-anchor": anchor || "start" });
  t.appendChild(document.createTextNode(String(content)));
  return t;
}

function card(title, subtitle, ...children) {
  return el(
    "div",
    { class: "a2ui-card" },
    title ? el("div", { class: "a2ui-card-title" }, title) : null,
    subtitle ? el("div", { class: "a2ui-card-sub" }, subtitle) : null,
    children
  );
}

function fmtNum(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v !== "number") return String(v);
  if (Number.isInteger(v) && Math.abs(v) < 1e15) return v.toLocaleString();
  return v.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function money(m) {
  if (!m || m.amount === null || m.amount === undefined) return null;
  return `${fmtNum(m.amount)} ${m.currency || "USD"}`;
}

const ARROWS = { up: "▲", down: "▼", flat: "→" };

function trendSpan(trend, changePct) {
  if (!trend && (changePct === null || changePct === undefined)) return null;
  // Wire contract (Standard Profile v1): trend is a direction string "up"|"down"|"flat".
  // The object form {direction, delta_pct, period} no longer appears on the wire;
  // changePct (from MetricItem.change_pct) carries any numeric delta annotation.
  let dir = null;
  let detail = "";
  if (typeof trend === "string") {
    dir = trend;
  } else if (trend && typeof trend === "object") {
    // Back-compat for any pre-wire-fix data that may still pass a KpiTrend object.
    dir = trend.direction || null;
  }
  if (changePct !== undefined && changePct !== null) {
    detail = ` ${changePct > 0 ? "+" : ""}${fmtNum(changePct)}%`;
  }
  if (!dir && !detail) return null;
  const cls = dir === "up" ? "a2ui-trend up" : dir === "down" ? "a2ui-trend down" : "a2ui-trend";
  return el("span", { class: cls }, `${ARROWS[dir] || ""}${detail}`);
}

/* simple numeric series → SVG path points */
function scalePoints(values, width, height, pad) {
  const finite = values.filter((v) => typeof v === "number" && isFinite(v));
  if (!finite.length) return null;
  let min = Math.min(...finite);
  let max = Math.max(...finite);
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const innerW = width - pad * 2;
  const innerH = height - pad * 2;
  const step = values.length > 1 ? innerW / (values.length - 1) : 0;
  const pts = values.map((v, i) => {
    if (typeof v !== "number" || !isFinite(v)) return null;
    const x = pad + i * step;
    const y = pad + innerH - ((v - min) / (max - min)) * innerH;
    return [x, y];
  });
  return { pts, min, max, innerH, innerW, pad };
}

/* ── component renderers (FROZEN field contracts, content_types.py) ── */

function renderKpiCard(data) {
  const metrics = data.metrics || [];
  const grid = el(
    "div",
    { class: "a2ui-kpi-grid" },
    capRows(metrics).map((m) =>
      el(
        "div",
        { class: "a2ui-kpi" },
        el("div", { class: "a2ui-kpi-value mono" }, `${fmtNum(m.value)}${m.unit ? ` ${m.unit}` : ""}`),
        el("div", { class: "a2ui-kpi-label" }, m.label !== undefined ? String(m.label) : ""),
        trendSpan(m.trend, m.change_pct !== undefined ? m.change_pct : null)
      )
    )
  );
  return card(data.title || null, null, grid, moreNote(metrics));
}

function renderTimeSeriesChart(data) {
  const points = data.data || [];
  const W = 560;
  const H = 180;
  const PAD = 28;
  const values = points.map((p) => (p && typeof p.value === "number" ? p.value : null));
  const scaled = scalePoints(values, W, H, PAD);
  const node = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "a2ui-svg", role: "img" });
  if (scaled) {
    const { pts, min, max } = scaled;
    const good = pts.filter(Boolean);
    if (data.chart_type === "bar") {
      const bw = Math.max(2, ((W - PAD * 2) / Math.max(points.length, 1)) * 0.7);
      pts.forEach((pt) => {
        if (!pt) return;
        node.appendChild(
          svg("rect", {
            x: pt[0] - bw / 2,
            y: pt[1],
            width: bw,
            height: H - PAD - pt[1],
            class: "a2ui-svg-bar",
          })
        );
      });
    } else {
      const d = good.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
      if (data.chart_type === "area" && good.length) {
        const areaD = `${d} L${good[good.length - 1][0].toFixed(1)},${H - PAD} L${good[0][0].toFixed(1)},${H - PAD} Z`;
        node.appendChild(svg("path", { d: areaD, class: "a2ui-svg-area" }));
      }
      node.appendChild(svg("path", { d, class: "a2ui-svg-line" }));
    }
    node.appendChild(svg("line", { x1: PAD, y1: H - PAD, x2: W - PAD, y2: H - PAD, class: "a2ui-svg-axis" }));
    node.appendChild(svgText(PAD, 14, fmtNum(max), "a2ui-svg-label"));
    node.appendChild(svgText(PAD, H - PAD + 14, fmtNum(min), "a2ui-svg-label"));
    if (points.length) {
      const first = points[0] || {};
      const last = points[points.length - 1] || {};
      node.appendChild(svgText(PAD, H - 4, String(first.date || ""), "a2ui-svg-label"));
      node.appendChild(svgText(W - PAD, H - 4, String(last.date || ""), "a2ui-svg-label", "end"));
    }
  }
  const summaryBits = [];
  const s = data.summary || {};
  if (s.change_percent !== undefined && s.change_percent !== null) {
    summaryBits.push(`${s.change_percent > 0 ? "+" : ""}${fmtNum(s.change_percent)}%`);
  }
  if (s.average !== undefined && s.average !== null) summaryBits.push(`avg ${fmtNum(s.average)}`);
  summaryBits.push(`${data.total_count !== undefined ? data.total_count : points.length} points`);
  return card(data.title || "Time series", data.subtitle || null, node, el("div", { class: "dim a2ui-chart-foot" }, summaryBits.join(" · ")));
}

function renderComparisonTable(data) {
  const columns = data.columns || [];
  const rows = data.rows || [];
  const table = el(
    "table",
    { class: "tbl a2ui-table" },
    el(
      "thead",
      null,
      el("tr", null, columns.map((c) => el("th", null, `${c.label !== undefined ? c.label : c.key}${c.unit ? ` (${c.unit})` : ""}`)))
    ),
    el(
      "tbody",
      null,
      capRows(rows).map((row) =>
        el(
          "tr",
          null,
          columns.map((c) => {
            const v = row ? row[c.key] : undefined;
            return el("td", { class: typeof v === "number" ? "mono" : null }, v === undefined || v === null ? "—" : fmtNum(v));
          })
        )
      )
    )
  );
  return card(data.title || null, null, table, moreNote(rows));
}

function renderBarChart(data) {
  const bars = data.bars || [];
  const W = 560;
  const rowH = 24;
  const PAD = 4;
  const labelW = 150;
  const H = bars.length * rowH + PAD * 2;
  const values = bars.map((b) => (typeof b.value === "number" ? b.value : 0));
  const maxAbs = Math.max(...values.map((v) => Math.abs(v)), 1);
  const node = svg("svg", { viewBox: `0 0 ${W} ${Math.max(H, rowH)}`, class: "a2ui-svg", role: "img" });
  bars.forEach((b, i) => {
    const y = PAD + i * rowH;
    const w = (Math.abs(values[i]) / maxAbs) * (W - labelW - 90);
    node.appendChild(svgText(labelW - 8, y + rowH / 2 + 4, String(b.category !== undefined ? b.category : ""), "a2ui-svg-label", "end"));
    node.appendChild(
      svg("rect", { x: labelW, y: y + 4, width: Math.max(w, 1), height: rowH - 8, class: values[i] < 0 ? "a2ui-svg-bar neg" : "a2ui-svg-bar" })
    );
    node.appendChild(svgText(labelW + Math.max(w, 1) + 6, y + rowH / 2 + 4, fmtNum(values[i]), "a2ui-svg-label"));
  });
  return card(data.title || null, null, node);
}

function renderEntityList(data) {
  const items = data.items || [];
  const list = el(
    "div",
    { class: "a2ui-list" },
    capRows(items).map((item) =>
      el(
        "div",
        { class: "a2ui-list-row" },
        el("div", { class: "a2ui-list-name" }, item.name !== undefined ? String(item.name) : ""),
        item.summary ? el("div", { class: "dim" }, String(item.summary)) : null
      )
    )
  );
  const showing = data.showing !== undefined && data.showing !== null ? data.showing : items.length;
  const total = data.total_count !== undefined && data.total_count !== null ? data.total_count : items.length;
  return card(
    data.title || `${data.entity_type || "entity"} list`,
    `showing ${showing} of ${total}${data.has_more ? " · more available" : ""}`,
    list,
    moreNote(items)
  );
}

/* PROSE exception (§7.1): the wire value is a markdown string; render as
 * plain-text paragraphs with NO card chrome. */
function renderMarketBriefing(value) {
  const text = typeof value === "string" ? value : value && value.title ? String(value.title) : "";
  const node = el("div", { class: "a2ui-prose" });
  for (const block of text.split(/\n{2,}/)) {
    const p = el("p", { class: "a2ui-prose-p" });
    block.split(/\n/).forEach((line, i) => {
      if (i) p.appendChild(document.createElement("br"));
      p.appendChild(document.createTextNode(line));
    });
    node.appendChild(p);
  }
  return node;
}

function renderWaterfallChart(data) {
  const segments = data.segments || [];
  const W = 560;
  const H = 200;
  const PAD = 28;
  // y-scale over every cumulative boundary including the zero/base
  const bounds = [0];
  segments.forEach((s) => {
    bounds.push(typeof s.cumulative === "number" ? s.cumulative : 0);
    bounds.push((typeof s.cumulative === "number" ? s.cumulative : 0) - (typeof s.value === "number" ? s.value : 0));
  });
  let min = Math.min(...bounds);
  let max = Math.max(...bounds);
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const innerH = H - PAD * 2 - 16;
  const toY = (v) => PAD + innerH - ((v - min) / (max - min)) * innerH;
  const bw = Math.max(8, ((W - PAD * 2) / Math.max(segments.length, 1)) * 0.62);
  const step = (W - PAD * 2) / Math.max(segments.length, 1);
  const node = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "a2ui-svg", role: "img" });
  node.appendChild(svg("line", { x1: PAD, y1: toY(0), x2: W - PAD, y2: toY(0), class: "a2ui-svg-axis" }));
  segments.forEach((s, i) => {
    const cum = typeof s.cumulative === "number" ? s.cumulative : 0;
    const val = typeof s.value === "number" ? s.value : 0;
    const isTotal = s.type === "initial" || s.type === "final" || s.type === "subtotal";
    const start = isTotal ? 0 : cum - val;
    const x = PAD + i * step + (step - bw) / 2;
    const y1 = toY(Math.max(start, cum));
    const y2 = toY(Math.min(start, cum));
    const cls = isTotal ? "a2ui-svg-bar total" : val >= 0 ? "a2ui-svg-bar" : "a2ui-svg-bar neg";
    node.appendChild(svg("rect", { x, y: y1, width: bw, height: Math.max(y2 - y1, 1.5), class: cls }));
    const label = String(s.label !== undefined ? s.label : "");
    node.appendChild(svgText(x + bw / 2, H - 6, label.length > 12 ? `${label.slice(0, 11)}…` : label, "a2ui-svg-label", "middle"));
  });
  const subBits = [data.subtitle, data.entity_name, data.currency, data.as_of_date].filter(Boolean);
  if (data.date_range && data.date_range.start) subBits.push(`${data.date_range.start} – ${data.date_range.end}`);
  return card(data.title || "Waterfall", subBits.join(" · ") || null, node);
}

function renderMultiCategoryChart(data) {
  const periods = data.periods || [];
  const categories = [];
  periods.forEach((p) => {
    Object.keys(p.categories || {}).forEach((k) => {
      if (!categories.includes(k)) categories.push(k);
    });
  });
  const W = 560;
  const H = 200;
  const PAD = 28;
  const innerH = H - PAD * 2 - 16;
  const totals = periods.map((p) =>
    Object.values(p.categories || {}).reduce((acc, c) => acc + (c && typeof c.value === "number" ? c.value : 0), 0)
  );
  const maxTotal = Math.max(...totals, 1);
  const step = (W - PAD * 2) / Math.max(periods.length, 1);
  const bw = Math.max(8, step * 0.6);
  const node = svg("svg", { viewBox: `0 0 ${W} ${H}`, class: "a2ui-svg", role: "img" });
  node.appendChild(svg("line", { x1: PAD, y1: H - PAD - 16, x2: W - PAD, y2: H - PAD - 16, class: "a2ui-svg-axis" }));
  periods.forEach((p, i) => {
    const x = PAD + i * step + (step - bw) / 2;
    let yCursor = H - PAD - 16;
    categories.forEach((cat, ci) => {
      const cell = (p.categories || {})[cat];
      const v = cell && typeof cell.value === "number" ? cell.value : 0;
      const h = (Math.abs(v) / maxTotal) * innerH;
      yCursor -= h;
      node.appendChild(svg("rect", { x, y: yCursor, width: bw, height: Math.max(h, 0.5), class: `a2ui-svg-bar cat-${ci % 6}` }));
    });
    const label = String(p.period !== undefined ? p.period : "");
    node.appendChild(svgText(x + bw / 2, H - 6, label.length > 10 ? `${label.slice(0, 9)}…` : label, "a2ui-svg-label", "middle"));
  });
  const legend = el(
    "div",
    { class: "a2ui-legend" },
    categories.map((cat, ci) =>
      el("span", { class: "a2ui-legend-item" }, el("span", { class: `a2ui-swatch cat-${ci % 6}` }), cat)
    )
  );
  const range = data.date_range || {};
  const subBits = [data.subtitle, data.unit_label, range.first ? `${range.first} – ${range.last}` : null].filter(Boolean);
  return card(data.title || "Categories", subBits.join(" · ") || null, node, legend);
}

/* sole camelCase-wire type */
function renderFundPerformance(data) {
  const pct = (v) => (v === null || v === undefined ? null : `${(v * 100).toFixed(1)}%`);
  const mult = (v) => (v === null || v === undefined ? null : `${fmtNum(v)}x`);
  const entries = [
    ["IRR", pct(data.irr)],
    ["Net IRR", pct(data.netIrr)],
    ["Gross IRR", pct(data.grossIrr)],
    ["TVPI", mult(data.tvpi)],
    ["DPI", mult(data.dpi)],
    ["RVPI", mult(data.rvpi)],
    ["MOIC", mult(data.moic)],
    ["Quartile", data.quartile !== undefined && data.quartile !== null ? `Q${data.quartile}` : null],
    ["NAV", money(data.nav)],
    ["Dry powder", money(data.dryPowder)],
    ["Distributed", money(data.distributed)],
    ["Remaining value", money(data.remainingValue)],
    ["Distributed + remaining", money(data.distributedPlusRemaining)],
    ["Called down", pct(data.calledDownPct)],
    ["Dry powder %", pct(data.dryPowderPct)],
  ].filter(([, v]) => v !== null && v !== undefined);
  const grid = el(
    "div",
    { class: "a2ui-kpi-grid" },
    entries.map(([label, value]) =>
      el("div", { class: "a2ui-kpi" }, el("div", { class: "a2ui-kpi-value mono" }, value), el("div", { class: "a2ui-kpi-label" }, label))
    )
  );
  const periodBits = [data.asOfQuarter ? `Q${data.asOfQuarter}` : null, data.asOfYear ? String(data.asOfYear) : null].filter(Boolean);
  const subBits = [
    periodBits.length ? periodBits.join(" ") : null,
    data.asOfDate ? `as of ${data.asOfDate}` : null,
    data.pbId ? `source ${data.pbId}` : null,
  ].filter(Boolean);
  return card("Fund performance", subBits.join(" · ") || null, grid);
}

function renderEmailList(data) {
  const messages = data.messages || [];
  const list = el(
    "div",
    { class: "a2ui-list" },
    capRows(messages).map((m) => {
      const from = m.from || {};
      return el(
        "div",
        { class: `a2ui-list-row ${m.is_read === false ? "unread" : ""}` },
        el(
          "div",
          { class: "a2ui-row-line" },
          m.is_read === false ? el("span", { class: "dot dot-ok" }) : null,
          el("span", { class: "a2ui-list-name" }, String(m.subject !== undefined ? m.subject : "")),
          m.has_attachments ? el("span", { class: "badge" }, "attachment") : null,
          m.importance === "high" ? el("span", { class: "badge badge-err" }, "high") : null
        ),
        el("div", { class: "dim" }, `${from.name || from.email || ""} · ${m.received_at || ""}`),
        m.preview ? el("div", { class: "a2ui-preview" }, String(m.preview)) : null
      );
    })
  );
  const sub = [`${data.total_count !== undefined ? data.total_count : messages.length} message(s)`];
  if (data.folder) sub.push(data.folder);
  if (data.has_more) sub.push("more available");
  return card("Mail", sub.join(" · "), list, moreNote(messages));
}

function renderCalendarEvents(data) {
  const events = data.events || [];
  const range = data.date_range || {};
  const list = el(
    "div",
    { class: "a2ui-list" },
    capRows(events).map((e) => {
      const loc = e.location || {};
      const online = e.is_online || loc.is_online;
      return el(
        "div",
        { class: "a2ui-list-row" },
        el(
          "div",
          { class: "a2ui-row-line" },
          el("span", { class: "a2ui-list-name" }, String(e.subject !== undefined ? e.subject : "")),
          e.is_cancelled ? el("span", { class: "badge badge-err" }, "cancelled") : null,
          online ? el("span", { class: "badge badge-ok" }, "online") : null,
          e.is_recurring ? el("span", { class: "badge" }, "recurring") : null
        ),
        el("div", { class: "dim mono" }, e.is_all_day ? `${e.start || ""} · all day` : `${e.start || ""} → ${e.end || ""}`),
        el(
          "div",
          { class: "dim" },
          [
            loc.display_name,
            e.organizer && e.organizer.name ? `organizer ${e.organizer.name}` : null,
            e.attendees_count ? `${e.attendees_count} attendees` : null,
          ]
            .filter(Boolean)
            .join(" · ")
        )
      );
    })
  );
  return card(
    "Calendar",
    `${data.total_count !== undefined ? data.total_count : events.length} event(s)${range.start ? ` · ${range.start} – ${range.end}` : ""}${data.has_more ? " · more available" : ""}`,
    list,
    moreNote(events)
  );
}

function renderUserProfile(data) {
  const presence = data.presence || null;
  const manager = data.manager || null;
  const rows = [
    ["Email", data.email],
    ["Title", data.job_title],
    ["Department", data.department],
    ["Office", data.office_location],
    ["Mobile", data.mobile_phone],
    ["Phones", (data.business_phones || []).join(", ") || null],
    ["Manager", manager ? `${manager.display_name} <${manager.email}>` : null],
    ["Presence", presence ? `${presence.availability}${presence.status_message ? ` — ${presence.status_message}` : ""}` : null],
  ].filter(([, v]) => v);
  const table = el(
    "table",
    { class: "tbl tbl-kv" },
    el("tbody", null, rows.map(([k, v]) => el("tr", null, el("th", null, k), el("td", null, String(v)))))
  );
  const ooo = data.out_of_office;
  return card(
    data.display_name || "User",
    null,
    table,
    ooo && ooo.is_enabled
      ? el("div", { class: "alert alert-warn" }, `Out of office${ooo.start_date ? ` ${ooo.start_date} – ${ooo.end_date || ""}` : ""}`)
      : null
  );
}

function renderUserList(data) {
  const users = data.users || [];
  const list = el(
    "div",
    { class: "a2ui-list" },
    capRows(users).map((u) =>
      el(
        "div",
        { class: "a2ui-list-row" },
        el(
          "div",
          { class: "a2ui-row-line" },
          el("span", { class: "a2ui-list-name" }, String(u.display_name !== undefined ? u.display_name : "")),
          u.presence ? el("span", { class: "badge" }, String(u.presence.availability)) : null
        ),
        el("div", { class: "dim" }, [u.email, u.job_title, u.department].filter(Boolean).join(" · "))
      )
    )
  );
  return card(
    "People",
    `${data.total_count !== undefined ? data.total_count : users.length} user(s)${data.query ? ` · "${data.query}"` : ""}${data.has_more ? " · more available" : ""}`,
    list,
    moreNote(users)
  );
}

// GH-177 (SI console-href): a DocumentItem link is a model-controlled URL in
// the admin console. Only an absolute http: or https: URL becomes an href;
// anything else (javascript:, data:, relative, unparsable) returns null and
// the name renders as plain text.
function safeHttpUrl(value) {
  if (typeof value !== "string" || !value) return null;
  let url;
  try {
    url = new URL(value);
  } catch {
    return null;
  }
  return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
}

function renderDocumentList(data) {
  const documents = data.documents || [];
  const list = el(
    "div",
    { class: "a2ui-list" },
    capRows(documents).map((d) => {
      // GH-177: contract keys first (modified, link); the pre-GH-177 keys
      // (last_modified, web_url) are only a fallback for older payloads.
      const when = d.modified || d.last_modified;
      const meta = [d.type, when ? `modified ${when}` : null, d.modified_by, d.size ? `${fmtNum(d.size)} bytes` : null]
        .filter(Boolean)
        .join(" · ");
      const name = String(d.name !== undefined ? d.name : "");
      const href = safeHttpUrl(d.link) || safeHttpUrl(d.web_url);
      return el(
        "div",
        { class: "a2ui-list-row" },
        href
          ? el("a", { class: "a2ui-list-name", href, target: "_blank", rel: "noopener noreferrer" }, name)
          : el("div", { class: "a2ui-list-name" }, name),
        meta ? el("div", { class: "dim" }, meta) : null
      );
    })
  );
  return card("Documents", `${data.total_count !== undefined ? data.total_count : documents.length} document(s)`, list, moreNote(documents));
}

const RENDERERS = {
  KpiCard: renderKpiCard,
  TimeSeriesChart: renderTimeSeriesChart,
  ComparisonTable: renderComparisonTable,
  BarChart: renderBarChart,
  EntityList: renderEntityList,
  MarketBriefing: renderMarketBriefing,
  WaterfallChart: renderWaterfallChart,
  MultiCategoryChart: renderMultiCategoryChart,
  FundPerformance: renderFundPerformance,
  EmailList: renderEmailList,
  CalendarEvents: renderCalendarEvents,
  UserProfile: renderUserProfile,
  UserList: renderUserList,
  DocumentList: renderDocumentList,
};
