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
 *   the surface data model.
 * - Renders the 14 FROZEN Standard Profile types; MarketBriefing is prose
 *   (no card chrome); unknown components render the artifact's text
 *   fallback. Display-only: no input binding, no action dispatch.
 * - Untrusted-output invariant: every dynamic value lands via
 *   createTextNode/textContent or numeric SVG attributes — never markup.
 */

import { el } from "./api.js";

/* surfaceId -> {catalogId, components: [], dataModel: {}, node, closed} */
const surfaces = new Map();

/* ── JSON Pointer (RFC 6901) ── */

function pointerTokens(pointer) {
  if (pointer === "" || pointer === null || pointer === undefined) return [];
  if (pointer === "/") return [""];
  return String(pointer)
    .split("/")
    .slice(1)
    .map((t) => t.replace(/~1/g, "/").replace(/~0/g, "~"));
}

export function pointerGet(doc, pointer) {
  let cur = doc;
  for (const token of pointerTokens(pointer)) {
    if (cur === null || cur === undefined) return undefined;
    if (Array.isArray(cur)) cur = cur[Number(token)];
    else if (typeof cur === "object") cur = cur[token];
    else return undefined;
  }
  return cur;
}

function pointerSet(doc, pointer, value) {
  const tokens = pointerTokens(pointer);
  if (!tokens.length) return value === undefined ? doc : value;
  let cur = doc;
  for (let i = 0; i < tokens.length - 1; i++) {
    const token = tokens[i];
    const key = Array.isArray(cur) ? Number(token) : token;
    if (cur[key] === null || cur[key] === undefined || typeof cur[key] !== "object") {
      cur[key] = /^\d+$/.test(tokens[i + 1]) ? [] : {};
    }
    cur = cur[key];
  }
  const last = tokens[tokens.length - 1];
  if (Array.isArray(cur)) cur[last === "-" ? cur.length : Number(last)] = value;
  else cur[last] = value;
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
  for (const msg of list) {
    if (!msg || typeof msg !== "object") continue;
    if (msg.createSurface) {
      const { surfaceId, catalogId } = msg.createSurface;
      if (!surfaceId) continue;
      const existing = surfaces.get(surfaceId);
      if (existing && existing.closed) {
        notes.push(`createSurface rejected: surface ${surfaceId} is closed`);
        continue;
      }
      if (!existing) {
        surfaces.set(surfaceId, {
          catalogId: catalogId || "",
          components: [],
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
        continue;
      }
      entry.components = Array.isArray(components) ? components : [];
      touched.add(surfaceId);
    } else if (msg.updateDataModel) {
      const { surfaceId, path, value } = msg.updateDataModel;
      const entry = surfaces.get(surfaceId);
      if (!entry || entry.closed) {
        notes.push(`updateDataModel dropped: unknown/closed surface ${surfaceId}`);
        continue;
      }
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
    const painted = paintSurface(entry, fallbackText, notes);
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
  const root =
    entry.components.find((c) => c && c.id === "root") || entry.components[0];
  if (!root) {
    return fallbackNode(fallbackText, "surface has no components");
  }
  const binding = root.data && root.data.path !== undefined ? root.data.path : null;
  const value = binding !== null ? pointerGet(entry.dataModel, binding) : entry.dataModel;
  const renderer = RENDERERS[root.component];
  if (!renderer) {
    notes.push(`unknown component ${String(root.component)} — JSON fallback rendered`);
    const resolvedValue = value === undefined ? null : value;
    if (resolvedValue !== null && typeof resolvedValue === "object") {
      return jsonFallbackNode(root.component, resolvedValue);
    }
    return fallbackNode(fallbackText, `unknown component: ${String(root.component)}`);
  }
  try {
    const node = renderer(value === undefined ? {} : value);
    node.classList.add("a2ui-surface");
    return node;
  } catch (err) {
    notes.push(`renderer ${root.component} failed: ${err.message || err}`);
    return fallbackNode(fallbackText, `renderer error for ${String(root.component)}`);
  }
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

/**
 * Render an unknown structured component as formatted JSON so that new domain
 * content types are inspectable in the console even before a dedicated renderer
 * is registered. Uses <pre class="a2ui-json"> — same pattern as chat.js fmtJson.
 */
function jsonFallbackNode(componentName, data) {
  const node = el("div", { class: "a2ui-surface a2ui-fallback" });
  node.appendChild(el("div", { class: "dim" }, `unknown component: ${String(componentName)}`));
  const pre = el("pre", { class: "a2ui-json" });
  pre.appendChild(document.createTextNode(JSON.stringify(data, null, 2)));
  node.appendChild(pre);
  return node;
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
    metrics.map((m) =>
      el(
        "div",
        { class: "a2ui-kpi" },
        el("div", { class: "a2ui-kpi-value mono" }, `${fmtNum(m.value)}${m.unit ? ` ${m.unit}` : ""}`),
        el("div", { class: "a2ui-kpi-label" }, m.label !== undefined ? String(m.label) : ""),
        trendSpan(m.trend, m.change_pct !== undefined ? m.change_pct : null)
      )
    )
  );
  return card(data.title || null, null, grid);
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
      rows.map((row) =>
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
  return card(data.title || null, null, table);
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
    items.map((item) =>
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
    list
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
    ["Called down", pct(data.calledDownPct)],
  ].filter(([, v]) => v !== null && v !== undefined);
  const grid = el(
    "div",
    { class: "a2ui-kpi-grid" },
    entries.map(([label, value]) =>
      el("div", { class: "a2ui-kpi" }, el("div", { class: "a2ui-kpi-value mono" }, value), el("div", { class: "a2ui-kpi-label" }, label))
    )
  );
  return card(data.fundName || "Fund performance", data.asOfDate ? `as of ${data.asOfDate}` : null, grid);
}

function renderEmailList(data) {
  const messages = data.messages || [];
  const list = el(
    "div",
    { class: "a2ui-list" },
    messages.map((m) => {
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
  return card("Mail", sub.join(" · "), list);
}

function renderCalendarEvents(data) {
  const events = data.events || [];
  const range = data.date_range || {};
  const list = el(
    "div",
    { class: "a2ui-list" },
    events.map((e) => {
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
    list
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
    users.map((u) =>
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
    list
  );
}

function renderDocumentList(data) {
  const documents = data.documents || [];
  const list = el(
    "div",
    { class: "a2ui-list" },
    documents.map((d) => {
      const when = d.last_modified || d.modified;
      const meta = [d.type, when ? `modified ${when}` : null, d.modified_by, d.size ? `${fmtNum(d.size)} bytes` : null]
        .filter(Boolean)
        .join(" · ");
      return el(
        "div",
        { class: "a2ui-list-row" },
        el("div", { class: "a2ui-list-name" }, String(d.name !== undefined ? d.name : "")),
        meta ? el("div", { class: "dim" }, meta) : null
      );
    })
  );
  return card("Documents", `${data.total_count !== undefined ? data.total_count : documents.length} document(s)`, list);
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
