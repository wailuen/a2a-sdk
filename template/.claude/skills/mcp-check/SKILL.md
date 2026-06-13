---
name: mcp-check
description: "Audit an MCP server for Claude.ai connector + spec conformance (2025-06-18 baseline). Static code audit + optional live curl/CLI probes across the OAuth discovery chain, token flow, CORS, Streamable HTTP transport, and the field-proven failure modes (incl. the version-future initialize trap). Portable, project-agnostic. Use when the user wants to verify/debug whether an MCP server will connect to Claude.ai, or check spec compliance before a Directory submission."
---

# /mcp-check — MCP server conformance & Claude.ai connector audit

Runs a systematic audit of an MCP server against the **MCP 2025-06-18** spec + the confirmed
Claude.ai failure modes. **Portable / project-agnostic** — discover the project, don't assume
its layout, language, or routes.

This skill is the **mechanical audit**; the **`mcp-advisor` agent** is the deep-reasoning
expert (design questions, "how should I build X", remediation strategy). Run this for a
repeatable pass/fail sweep; dispatch `mcp-advisor` for judgment calls. Both read the same kit:
`.claude/reference/mcp-protocol.md` (§) and `.claude/reference/mcp-claude-platforms.md` (P).

## Usage

```
/mcp-check [--live <base-url>] [--cli]
```
- no flag → static code audit only (read source, run tests)
- `--live <url>` → also probe the running endpoint with curl
- `--cli` → also run the `claude mcp add --transport http <url>` end-to-end validation

## Step 0 — Discover (never assume)

Locate, by search not by hardcoded path: the MCP transport/route handler (Streamable HTTP
POST+GET, or stdio), the OAuth routes + `/.well-known/*` handlers, the CORS config, the token
mint/verify logic, and the `initialize` handler. Note the **declared `protocolVersion`** and
the **target surface** (custom connector / Messages API / Claude Code / Desktop / Directory) —
the applicable rules differ per surface (`mcp-claude-platforms.md P0`). If it's a pure stdio
local server, skip the OAuth/CORS layers and focus on transport + stdout hygiene.

## What this checks

### Layer 1 — OAuth discovery chain  (`§11`, `P1`)
| Check | Spec |
|---|---|
| `/.well-known/oauth-protected-resource` has `resource` (== canonical MCP URL) + `authorization_servers` | RFC 9728 |
| Served at **both** bare and path-suffixed `/.well-known/oauth-protected-resource/<mcp-path>` (Claude probes suffixed first) | P9.3 |
| **If server also exposes a non-MCP surface (e.g. A2A `/v1`):** PRM `resource` must cover that surface too — scope to base origin, not just `/mcp` — otherwise A2A 401 `WWW-Authenticate` points consumers to the wrong resource scope | RFC 9728 seam |
| `/.well-known/oauth-authorization-server` has `registration_endpoint` (or CIMD) + `code_challenge_methods_supported:["S256"]` + **`scopes_supported`** array (RFC 8414 RECOMMENDED; empty array if no scopes enforced — omission prevents scope-aware clients from discovering what to request) | RFC 8414 |
| DCR `POST <register>` accepts `redirect_uris`, returns 201 with `client_id` | RFC 7591 |
| Unauthenticated `POST <mcp>` → real **`401`** + `WWW-Authenticate: Bearer resource_metadata=...` (not 200, not a JSON error) | RFC 9728 §5.1 / P1 |

### Layer 2 — OAuth token flow  (`§11`)
| Check | Spec |
|---|---|
| **Authorize endpoint pre-validates PKCE BEFORE serving the login UI** — missing/blank `code_challenge` or `code_challenge_method != "S256"` must return 400 (or redirect `error=invalid_request`) before the user ever sees a login form. Checking only at the token endpoint is insufficient: a compromised auth code issued without a `code_challenge` can be exchanged without the verifier. | OAuth 2.1 §4.3 |
| PKCE **S256 enforced at token exchange** (not merely accepted; `plain` rejected; `code_verifier` validated) | OAuth 2.1 |
| **Token endpoint is a PUBLIC endpoint** — it MUST NOT require a pre-existing Bearer token (it authenticates via `client_id`/`code`/`code_verifier` from the request body). If any resource-server auth middleware wraps the token endpoint, the flow is broken for public clients. Verify the middleware exclusion list explicitly includes `/oauth/token`. | RFC 6749 §3.2 / MCP §11 |
| **Token endpoint error responses use RFC 6749 §5.2 format**: `{"error": "<code>", "error_description": "..."}` with `error` ∈ {`invalid_request`, `invalid_grant`, `unsupported_grant_type`, `invalid_client`}. A `{"category","message","source"}` shape (typical of internal error handlers) is non-conformant — OAuth 2.1 clients (including Claude.ai) key on the `error` field to distinguish grant failures and cannot self-correct without it. Note: this applies to the **token endpoint only** — other auth-guarded routes may use the server's internal error format. | RFC 6749 §5.2 |
| Token `aud` == canonical MCP URL (no trailing-slash mismatch) | RFC 8707 |
| Refresh-token grant binds `client_id` from **token metadata**, asserts == caller before secret check / mint | LRN — RFC 6749 §6 |
| Audience `resource` is validated-at-issue **and** persisted in token metadata **and** checked at the resource server | LRN — three-AC rule |
| Refresh token rotated on use (public clients) | OAuth 2.1 §4.3.1 |
| `scope` **omitted** from token response when empty (not `""`) | RFC 6749 §5.1 / P9.4 |
| No new credential kind silently widened a shared auth dependency to admin/other routes | LRN — re-assert per surface |

### Layer 3 — CORS  (`P1`, `§12`)
| Check | Pass condition |
|---|---|
| `https://claude.ai` in allow-origins, **hardcoded not env-gated**, never `"*"` on auth-bearing app | P9.5 |
| `WWW-Authenticate` in `Access-Control-Expose-Headers` | required for the browser 401 flow |
| `MCP-Protocol-Version`, `Mcp-Session-Id`, `Authorization`, `Accept`, `Last-Event-ID` in `Allow-Headers` | post-init |
| OPTIONS preflight → 204 with the above | |

### Layer 4 — Streamable HTTP transport  (`§10`, `P1`)
| Check | Spec |
|---|---|
| `GET <mcp>` → `text/event-stream` or **405** (never 200 JSON/HTML) | transport |
| `POST <mcp>` → `application/json` (or SSE) for JSON-RPC requests; **202** for notification/response inputs | transport |
| `protocolVersion` echoed in `initialize` (echo-if-supported) | lifecycle |
| **`initialize` result carries NO version-future field** (e.g. `serverInfo.icons` only if negotiated `2025-11-25`) | **P9.1 — critical** |
| `tools/list` → `{tools:[{name,inputSchema,...}]}`; tool failures use `isError:true`, not JSON-RPC error | §4, §9 |
| `MCP-Protocol-Version` required post-init; `Mcp-Session-Id` lifecycle (400 missing / 404 expired); `Origin` validated | §10 |
| stdio servers: **stdout is MCP-only** (logs → stderr) | §10 |

### Layer 5 — Known failure-mode scan  (`P7`, `P9`)
For each confirmed cause, verify the server is not affected:
| Failure | Check |
|---|---|
| **"Authorization failed" *after* `POST /mcp` 200** | `initialize` result is schema-valid for the negotiated version — no version-future field (P9.1). **Inspect the JSON-RPC body, not OAuth.** |
| 401 flips to 503 on malformed `Host` | `WWW-Authenticate` derivation wrapped in try/except → degrades to header-less 401 (P9.2) |
| `WWW-Authenticate` not CORS-exposed | in `Expose-Headers` |
| Cross-host redirect strips Authorization | MCP URL serves directly, no 30x to a different host (P9.6) |
| `GET <mcp>` non-SSE 200 | returns SSE or 405 |
| PRM `resource` ≠ token `aud` | same canonical URL both places |
| #291 (initialize POST never sent) / #155 (Bearer not attached) — **web client bugs** | flag as WARN; SSE escape hatch (P9.7) + CLI validation is the mitigation, no server fix |

### Layer 6 — Live probes (`--live <url>`)
```bash
BASE="<url from args>"   # e.g. https://api.example.com   MCP="$BASE/mcp"

# 1. Unauthenticated MCP → must be 401 with WWW-Authenticate
curl -si -X POST -H "Content-Type: application/json" -H "Origin: https://claude.ai" "$MCP" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}' \
  | grep -iE "HTTP/|WWW-Authenticate|access-control"

# 2. Malformed Host → must STILL be 401 (not 503)   [P9.2]
curl -si -X POST -H "Host: :::bad" -H "Content-Type: application/json" "$MCP" -d '{}' | grep -iE "HTTP/"

# 3. Protected Resource Metadata — bare AND path-suffixed   [P9.3]
curl -sf -H "Origin: https://claude.ai" "$BASE/.well-known/oauth-protected-resource" | python3 -m json.tool
curl -sf "$BASE/.well-known/oauth-protected-resource/mcp" | python3 -m json.tool

# 4. Authorization Server Metadata — must show S256 + registration_endpoint
curl -sf "$BASE/.well-known/oauth-authorization-server" | python3 -m json.tool

# 5. CORS: WWW-Authenticate exposed on preflight?
curl -si -H "Origin: https://claude.ai" -X OPTIONS "$MCP" | grep -i "access-control"

# 6. GET <mcp> → text/event-stream or 405
curl -si -H "Origin: https://claude.ai" "$MCP" | grep -iE "HTTP/|content-type"
```

### Layer 7 — CLI end-to-end validation (`--cli`, always recommend)
```bash
claude mcp add --transport http <mcp-url>   # then `/mcp` to OAuth-login + list tools
claude mcp list                              # should show connected
claude mcp remove <name>
```
**If the CLI connects and lists tools, the server's transport + OAuth are sound.** Any remaining
claude.ai-web-only failure is a known client bug (P7), not a server defect.

## Steps
1. Step 0 discovery — find the handlers, declared version, target surface.
2. Run each layer against the code with `file:line` evidence; mark PASS / FAIL / WARN.
3. If `--live` / `--cli`, run the probes and fold results in.
4. For each FAIL: state the **exact symptom Claude.ai would show**, the fix, and the file:line.
5. For WARN (client bugs): give the CLI/SSE mitigation.
6. For design-level or ambiguous findings, **dispatch the `mcp-advisor` agent** rather than guessing.
7. If a new, generalizable failure mode surfaces, note it for the kit
   (`.claude/reference/mcp-claude-platforms.md` P-section or `mcp-protocol.md`).

## Report format
```
## MCP Connector Audit — <date>
Target surface: <custom connector | API | Claude Code | Desktop | Directory>
Declared protocolVersion: <...>   Mode: <static | live | cli>

Layer 1 OAuth Discovery:  [PASS] ...   [FAIL] ... (symptom → fix @ file:line)
Layer 2 Token Flow:       ...
Layer 3 CORS:             ...
Layer 4 Transport:        ...
Layer 5 Known Failures:   [WARN] #291 — mitigate via SSE escape hatch + CLI
Summary: N pass / M fail / K warn
Verdict: will-it-connect-to-Claude.ai? <yes/no>   conformant-2025-06-18? <yes/no>
Next action: <cheapest-unblock-first remediation, or "dispatch mcp-advisor for X">
```
