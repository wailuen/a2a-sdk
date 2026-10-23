// GH-216: build an AG-UI resume payload from an interrupt's responseSchema.
// Pure functions (no DOM) so they can be run under node in tests.

function props(schema) {
  const p = schema && typeof schema === "object" ? schema.properties : null;
  return p && typeof p === "object" ? p : {};
}

export function coerceValue(propSchema, raw) {
  const s = propSchema && typeof propSchema === "object" ? propSchema : {};
  const text = String(raw).trim();
  if (Array.isArray(s.enum)) {
    const hit = s.enum.find((v) => String(v) === text);
    if (hit === undefined) return { ok: false, error: `must be one of: ${s.enum.join(", ")}` };
    return { ok: true, value: hit };
  }
  switch (s.type) {
    case "integer":
      if (!/^[+-]?\d+$/.test(text)) return { ok: false, error: "must be a whole number" };
      return { ok: true, value: Number.parseInt(text, 10) };
    case "number": {
      const n = Number(text);
      if (text === "" || !Number.isFinite(n)) return { ok: false, error: "must be a number" };
      return { ok: true, value: n };
    }
    case "boolean": {
      const t = text.toLowerCase();
      if (["true", "yes", "y", "1"].includes(t)) return { ok: true, value: true };
      if (["false", "no", "n", "0"].includes(t)) return { ok: true, value: false };
      return { ok: false, error: "must be true or false" };
    }
    default:
      return { ok: true, value: String(raw) };
  }
}

export function formFields(schema) {
  const names = Object.keys(props(schema));
  return names.length > 1 ? names : null;
}

export function buildPayloadFromValues(schema, values) {
  const p = props(schema);
  const required = Array.isArray(schema && schema.required) ? schema.required : [];
  const payload = {};
  for (const name of Object.keys(p)) {
    const raw = values[name];
    if (raw === undefined || String(raw).trim() === "") {
      if (required.includes(name)) return { ok: false, error: `${name} is required` };
      continue;
    }
    const r = coerceValue(p[name], raw);
    if (!r.ok) return { ok: false, error: `${name} ${r.error}` };
    payload[name] = r.value;
  }
  return { ok: true, payload };
}

export function buildResumePayload(schema, text) {
  const names = Object.keys(props(schema));
  if (names.length === 0) return { ok: true, payload: { decision: text } };
  if (names.length === 1) {
    const r = coerceValue(props(schema)[names[0]], text);
    if (!r.ok) return { ok: false, error: `${names[0]} ${r.error}` };
    return { ok: true, payload: { [names[0]]: r.value } };
  }
  return { ok: false, error: "this interrupt needs several fields; use the form" };
}
