/* retry.js — retry policy for the console's first run request (GH-191).
 * Pure module: no DOM, no network of its own, so it can be unit-tested in node.
 */

export const MAX_RETRIES = 3;
export const MAX_DELAY_MS = 30000;
const BASE_DELAY_MS = 1000;
const WAIT_STATUSES = new Set([429, 503]);

/** Retry-After header value -> milliseconds (capped), or null if absent/invalid. */
export function parseRetryAfter(value, now = Date.now()) {
  if (value === null || value === undefined) return null;
  const text = String(value).trim();
  if (text === "") return null;
  let seconds;
  if (/^\d+$/.test(text)) {
    seconds = Number(text);
  } else {
    const when = Date.parse(text);
    if (Number.isNaN(when)) return null;
    seconds = Math.max(0, (when - now) / 1000);
  }
  return Math.min(seconds * 1000, MAX_DELAY_MS);
}

/** Decide what to do after a non-OK response. attempt is 0-based. */
export function decideRetry(status, retryAfter, attempt) {
  if (!WAIT_STATUSES.has(status) || attempt >= MAX_RETRIES) return { retry: false, delayMs: 0 };
  const fromHeader = parseRetryAfter(retryAfter);
  const backoff = Math.min(BASE_DELAY_MS * 2 ** attempt, MAX_DELAY_MS);
  return { retry: true, delayMs: fromHeader === null ? backoff : fromHeader };
}

/**
 * POST until a response that is OK, or a failure that must not be retried.
 * Only called before any SSE frame has been read, so a network failure is safe
 * to retry. Returns the OK response, or null after reporting the failure.
 */
export async function postWithRetry(doPost, { systemLine, traceFrame, label, sleep }) {
  const wait = sleep || ((ms) => new Promise((r) => setTimeout(r, ms)));
  for (let attempt = 0; ; attempt++) {
    let resp;
    try {
      resp = await doPost();
    } catch (err) {
      if (attempt >= MAX_RETRIES) {
        systemLine(`${label} failed: network error`);
        return null;
      }
      const delayMs = Math.min(BASE_DELAY_MS * 2 ** attempt, MAX_DELAY_MS);
      systemLine(`${label} failed (network error), retrying in ${delayMs / 1000}s…`);
      await wait(delayMs);
      continue;
    }
    if (resp.ok) return resp;
    const { retry, delayMs } = decideRetry(resp.status, resp.headers && resp.headers.get("Retry-After"), attempt);
    if (!retry) {
      traceFrame(`HTTP ${resp.status}`, await resp.text());
      systemLine(`${label} failed: HTTP ${resp.status}`);
      return null;
    }
    systemLine(`${label} failed (HTTP ${resp.status}), retrying in ${delayMs / 1000}s…`);
    await wait(delayMs);
  }
}
