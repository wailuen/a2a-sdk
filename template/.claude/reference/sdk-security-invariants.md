# SDK Security Invariants — reference

These 7 invariants apply to every agent built on `agent-sdk`. They are
checked by `/redteam` (fail-closed), enforced by `python-implementer` in
code, and used by `planner` to add `SI:` fields to relevant todos.

**Fail-closed rule:** An invariant that cannot be positively confirmed from
code is a **finding**, not a pass. Absence of evidence = violation.

---

## SI-1 — No raw HTTP in tools

**Severity:** Critical

No `httpx.AsyncClient`, `aiohttp.ClientSession`, or `requests` call directly
in `src/tools/`. All outbound HTTP goes through a `SourceAdapter` subclass
whose base-class client enforces `allowed_hosts` and owns retries/timeouts.

**Check:** `grep -r "httpx\|aiohttp\|requests" src/tools/ --include="*.py"`
→ zero matches expected.

**Prevention:** When planning a todo that calls an external API from a tool,
require a `SourceAdapter` intermediary. A new host ⇒ a new or updated adapter.

---

## SI-2 — No secrets or user-input values in errors or logs

**Severity:** Critical

Exception messages and log statements never interpolate credential values,
tokens, or raw user inputs. Raise `AgentError(category, "generic message",
source=…)`. Never call `str(exc)` on exceptions that wrap external-API
responses and then propagate that string to callers or logs.

**Check (f-string interpolation, both quote styles):**
`grep -rn "f[\"'].*{.*\(token\|key\|secret\|password\|cred\)" src/` → zero matches.

**Check (log calls with interpolated values):**
`grep -rn "log\.\(info\|error\|warn\|debug\).*{" src/` → review each match; no match should forward a credential or raw user input.

**Prevention:** When planning error-handling todos, require generic messages.
The SDK's `AgentError` already redacts and maps categories onto each protocol.

---

## SI-3 — Path/URL params through validators in adapters

**Severity:** High

Every variable interpolated into a URL path inside a `SourceAdapter` goes
through `agent_sdk.validation.url_segment(value)` (for string path segments)
or `safe_id(value)` (for identifiers). The `@tool` decorator does not
sanitize inputs — the adapter is the only enforcement point.

**Check:** `grep -n "f\"/.*{" src/sources/` → every match must use
`url_segment` or `safe_id` on the variable, not raw input.

**Prevention:** Todos that add URL-parameter paths must have an AC: "all path
variables go through `url_segment()`/`safe_id()` in the adapter method."

---

## SI-4 — Credentials resolved, never read

**Severity:** High

Adapter and tool code uses `self.credential("field_name")` only. Never
`os.environ`, `os.getenv`, or reading from `settings.*` for a credential
inside `src/tools/` or `src/sources/`. The credential stays scoped to the
adapter's namespace in the encrypted store.

**Check:** `grep -rn "os\.environ\|os\.getenv" src/tools/ src/sources/`
→ zero matches expected.

**Prevention:** Any todo that introduces an upstream credential must use the
credential store path, not env vars.

---

## SI-5 — Auth on all A2A/MCP/AG-UI endpoints

**Severity:** Critical

Every FastAPI router mounted on the app (except `/.well-known/` discovery
routes and `/health`) uses `Depends(require_identity)` or an equivalent SDK
auth dependency. No unauthenticated data path exists on the protocol surfaces.

**Check:** `grep -n "require_identity\|APIRouter\|include_router" src/routes/`
→ every router that serves data must declare auth.

**Prevention:** Todos that add new routes must have an AC that names the auth
dependency. Escape-hatch routes added post-`build_app()` are NOT covered by
SDK auth automatically — they must add `Depends(require_identity)` explicitly.

---

## SI-6 — No vendor/upstream key in `.env`, argv, or logs

**Severity:** Critical

Upstream API keys (e.g. AlphaGeo `api_key`, third-party tokens) live only
in the `EncryptedSqliteStore` under the adapter's namespace. They must never
appear in `.env`, CLI arguments (`sys.argv`), or any log statement.

**Check:** `grep -rn "UPSTREAM\|VENDOR\|_API_KEY\s*=" .env src/` → any match
containing an actual key value (not a placeholder) is a violation.

**Prevention:** Provisioning uses `scripts/set_upstream_credential.py` or the
admin console credential form — never writes vendor keys to `.env` or code.

---

## SI-7 — `allowed_hosts` on every SourceAdapter

**Severity:** High

Every `SourceAdapter` subclass declares a non-empty `allowed_hosts` list.
An empty list or wildcard (`"*"`) disables the SDK's SSRF guard and allows
the adapter to route to any host.

**Check:** `grep -A 3 "class.*SourceAdapter" src/sources/*.py` → every
subclass must have `allowed_hosts = ["hostname.tld"]` (non-empty, no
wildcards).

**Prevention:** Todos adding a new source adapter must have an AC:
"`allowed_hosts` declared with the exact upstream hostname(s); no wildcard."
