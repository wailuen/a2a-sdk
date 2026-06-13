# Research — MCP on Anthropic / Claude Platforms

**Track:** Platform integration. Companion to `mcp-protocol.md` (the spec digest). This file
is the authoritative reference for the `mcp-advisor` agent and `mcp-server` skill on **how an
MCP server actually connects to each Claude surface**, what each surface supports, the
Connectors Directory submission, the icon model, and confirmed Claude.ai client bugs. Cite
this file's sections (P1–P8) when advising on Claude connectivity.

**Sources (Anthropic, fetched 2026-05-31):** `claude.com/docs/connectors/building` and its
sub-pages (`authentication`, `submission`, `review-criteria`, `troubleshooting`, `mcpb`);
`platform.claude.com/docs/en/agents-and-tools/mcp-connector`; `code.claude.com/docs/en/mcp`;
`support.claude.com` connector articles; `modelcontextprotocol.io/quickstart/user`;
`github.com/modelcontextprotocol/mcpb`; `github.com/anthropics/claude-ai-mcp` issues.

> **Core mental model:** "works in Claude Code" ≠ "works on claude.ai." The five surfaces
> differ in transport, capabilities, auth, and icons. **Build to the spec baseline
> `2025-06-18`, then target the specific surface(s) the project needs.**

---

## P0 — The five surfaces at a glance

| Surface | Transport | Capabilities | Auth | Who connects |
|---|---|---|---|---|
| **Claude.ai web / Desktop / mobile — custom connector** | Streamable HTTP (SSE deprecated) | tools, resources (text+binary), prompts | OAuth 2.0 + PKCE/S256; `401`+`WWW-Authenticate` required | **Anthropic cloud** (server-side egress) |
| **Messages API `mcp_servers`** | Streamable HTTP **or** SSE (remote URL only) | **tools only** | Bearer via `authorization_token` (you run OAuth) | Anthropic API backend |
| **Claude Code** | stdio, http(=streamable), sse(deprecated), ws | tools, resources, prompts, **elicitation**, list_changed | OAuth via `/mcp` (loopback callback); DCR/CIMD/pre-reg/static headers | **User's machine** |
| **Claude Desktop — local** | stdio | tools, resources, prompts | none (OS secret vault + `${user_config.*}`) | User's machine |
| **Connectors Directory** | (same as custom connector) | tools, resources, prompts | OAuth 2.0 (DCR/CIMD); reviewed | Anthropic cloud, post-review |

**Capability ceiling everywhere on Anthropic surfaces:** **sampling and resource
subscriptions are not supported** on the hosted connector surface; the Messages API connector
is **tools-only.** Don't design a Claude-targeted server that depends on sampling/elicitation
reaching Claude.ai web. (Claude Code is the exception — it supports elicitation.)

---

## P1 — Claude.ai web / Desktop / mobile — custom remote connectors

A user pastes a **remote MCP server URL**; Claude then connects **from Anthropic's cloud
infrastructure, not the user's device** (true on web, Desktop, Cowork, mobile). So the server
**must be publicly reachable from Anthropic's egress IP ranges** — servers behind a VPN /
corporate firewall / private network won't connect, and a CDN/WAF/bot-manager/rate-limiter
returning 403/429 fails *before* your app sees the request.

**How a user adds one:** Pro/Max → Settings → **Customize → Connectors → "+" → Add custom
connector** → URL. Team/Enterprise → **Organization settings → Connectors** (Owners only).
"Advanced settings" optionally takes an **OAuth Client ID + Client Secret** (only for
confidential-client servers; optional otherwise).

**Transport:** **Streamable HTTP** (legacy HTTP+SSE deprecating). No stdio.

**Plan tiers:** Free (limited to **one** custom connector), Pro, Max, Team, Enterprise.
**Org admin (Team/Enterprise):** only **Owners** add org connectors; controls only *narrow*
access (read-only vs write, approval gates) — never grant more than the source system permits.

**Limits:** result size ~**150,000 characters**; tool timeout **300 seconds**.

**OAuth — the load-bearing facts:**
- Unauthenticated request → **`401`** + `WWW-Authenticate: Bearer
  resource_metadata="https://.../.well-known/oauth-protected-resource"`. **The `401` is
  required — Claude does NOT honor `WWW-Authenticate` on a `200`.** Return a real HTTP 401,
  not an MCP-level JSON error.
- Protected Resource Metadata `resource` field must **exactly** match your MCP server URL;
  `authorization_servers` array required.
- AS metadata must advertise `"code_challenge_methods_supported": ["S256"]` — Claude sends a
  PKCE `code_challenge` with `code_challenge_method=S256` on every authorize.
- **OAuth callback URI:** **`https://claude.ai/api/mcp/auth_callback`** — handled
  **server-side by Anthropic**; your AS redirects to it and the browser just follows. There
  are **no browser-side fetches** from the callback to your server; all post-redirect traffic
  comes from Anthropic egress IPs. *(Note: only the `claude.ai` callback is documented;
  a `claude.com` equivalent is not confirmed in Anthropic docs. Register additional callbacks
  only if the submission form asks.)*
- **Auth types:** `oauth_dcr` (RFC 7591 DCR) and `oauth_cimd` (Client ID Metadata Document)
  work out-of-the-box; `none` (authless) supported; `oauth_anthropic_creds` and
  `custom_connection` require contacting `mcp-review@anthropic.com`. **Static bearer tokens /
  query-param credentials are NOT supported.**
- **Token refresh:** Claude refreshes reactively on `401` and proactively up to 5 min before
  expiry. Return RFC 6749 error codes (e.g. `invalid_grant`), rotate refresh tokens for public
  clients, accept `Content-Type: application/x-www-form-urlencoded` at the token endpoint.

**Required server endpoints (custom connector):**

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST <mcp-path>` | Bearer | all JSON-RPC (initialize, tools/list, tools/call) |
| `GET <mcp-path>` | Bearer | optional SSE channel — `405` is valid if not offered (never 200+JSON/HTML) |
| `/.well-known/oauth-protected-resource` | none | RFC 9728 PRM |
| `/.well-known/oauth-authorization-server` | none | RFC 8414 AS metadata (fallback `/.well-known/openid-configuration`) |
| `POST <registration>` | none | RFC 7591 DCR (or use CIMD) |
| `GET <authorize>` | login gate | redirects to the Anthropic callback |
| `POST <token>` | none | PKCE token exchange |

**CORS** (every response + OPTIONS preflight → 204):
```
Access-Control-Allow-Origin: https://claude.ai
Access-Control-Allow-Methods: GET, POST, DELETE, OPTIONS
Access-Control-Allow-Headers: Authorization, Content-Type, Mcp-Session-Id, Accept, Last-Event-ID, MCP-Protocol-Version
Access-Control-Expose-Headers: WWW-Authenticate, Mcp-Session-Id
```
`WWW-Authenticate` **MUST** be in `Expose-Headers` — without it the browser can't read the 401
challenge.

---

## P2 — Messages API MCP connector (`mcp_servers`)

Lets the Messages API call remote MCP servers directly — no separate client. **Remote-URL
only; tools only.** Resources, prompts, sampling, elicitation are ignored by this parameter.

- **Beta header (current):** `anthropic-beta: mcp-client-2025-11-20` (deprecated:
  `mcp-client-2025-04-04`).
- **Request shape (current):** server connection in `mcp_servers`, tool gating in `tools` via
  an `mcp_toolset`:
```json
{
  "mcp_servers":[{"type":"url","url":"https://example.com/mcp","name":"example-mcp",
                  "authorization_token":"YOUR_TOKEN"}],
  "tools":[{"type":"mcp_toolset","mcp_server_name":"example-mcp",
            "default_config":{"enabled":true,"defer_loading":false},
            "configs":{"some_tool":{"enabled":false}}}]
}
```
  `type` only `"url"`; `url` must be `https://`; `name` unique, referenced by exactly one
  toolset. **Allowlist** = `default_config.enabled:false` + enable specific tools in `configs`;
  **denylist** = leave on + disable specific. Precedence: `configs` > `default_config` >
  defaults.
- **Auth:** OAuth bearer via `authorization_token` — **you run/refresh the OAuth flow
  yourself**; the API doesn't. (MCP Inspector can grab a token for testing.)
- **Transports:** both Streamable HTTP and SSE work (remote URL exposed over HTTP).
- **Response blocks:** `mcp_tool_use`, `mcp_tool_result` (carry `server_name`/`tool_use_id`).
- **Availability:** Claude API, Claude on AWS, Microsoft Foundry. **Not** Bedrock or Vertex.
  Works in Message Batches. **Not ZDR-eligible.**
- **Migration 04-04 → 11-20:** the old `tool_configuration`(`enabled`/`allowed_tools`) on the
  server object is removed → move gating into an `mcp_toolset`; `allowed_tools` →
  `default_config.enabled:false` + enable in `configs`. For large tool sets use
  `defer_loading` + the Tool search tool.

---

## P3 — Claude Code

- **Transports:** `http` (recommended; `streamable-http` is a JSON alias), `sse`
  (deprecated), `stdio` (local), `ws` (JSON/`add-json` only, header-auth only, no OAuth).
- **Add:** flags go **before** the name; `--` separates name from stdio command:
```bash
claude mcp add --transport http  notion  https://mcp.notion.com/mcp
claude mcp add --transport http  secure  https://api.example.com/mcp --header "Authorization: Bearer TOKEN"
claude mcp add --transport stdio --env KEY=val airtable -- npx -y airtable-mcp-server
claude mcp add-json weather '{"type":"http","url":"https://api.weather.com/mcp"}'
```
- **Manage:** `claude mcp list|get <name>|remove <name>`; `/mcp` (in-session status + OAuth
  login); `claude mcp reset-project-choices`; `claude mcp add-from-claude-desktop`.
- **Scopes & files:** `local` (default; current project; `~/.claude.json`), `project` (shared,
  commit `.mcp.json` at repo root; needs interactive approval), `user` (all your projects;
  `~/.claude.json`). Precedence high→low: local → project → user → plugin → claude.ai
  connectors (matched by name for scopes, by endpoint for plugins/connectors; the winning
  entry is used whole, not merged). `.mcp.json` supports `${VAR}` / `${VAR:-default}`.
- **OAuth for remote http/sse:** `401` **or** `403` flags the server in `/mcp` for login; a
  `WWW-Authenticate` header enables auto-discovery (RFC 9728 → RFC 8414). **Loopback callback**
  `http://localhost:PORT/callback` (pin with `--callback-port`). Pre-registered creds via
  `--client-id`/`--client-secret` (or `MCP_CLIENT_SECRET`); CIMD auto-discovery; `oauth.scopes`
  / `oauth.authServerMetadataUrl` / `headersHelper` configurable in `.mcp.json`.
- **Capabilities:** tools, **resources** (`@server:proto://path`), **prompts**
  (`/mcp__server__prompt`), **elicitation** (form + URL, auto-dialog), **list_changed**,
  channels (server-push). Tool search on by default. Output warn at 10k tokens, cap 25k
  (`MAX_MCP_OUTPUT_TOKENS`). Per-server `timeout` ms.
- **claude.ai connectors inside Claude Code:** auto-available only when active auth is the
  Claude.ai subscription login (not API key / Bedrock / Vertex). Disable with
  `ENABLE_CLAUDEAI_MCP_SERVERS=false`.
- **Enterprise:** `managed-mcp.json` with `allowedMcpServers`/`deniedMcpServers`.

> **Validation shortcut:** `claude mcp add --transport http <url>` is the cheapest correctness
> probe. If the CLI connects and lists tools, the server's transport + OAuth are sound — any
> claude.ai web failure is then a known client bug (P7), not a server defect.

---

## P4 — Claude Desktop local (stdio)

Two mechanisms, both **local stdio**:
- **`claude_desktop_config.json`** (Settings → Developer → Edit Config):
  macOS `~/Library/Application Support/Claude/claude_desktop_config.json`,
  Windows `%APPDATA%\Claude\claude_desktop_config.json`:
```json
{ "mcpServers": { "filesystem": {
    "command": "npx",
    "args": ["-y","@modelcontextprotocol/server-filesystem","/Users/me/Desktop"],
    "env": {} } } }
```
  Restart to load. Logs: macOS `~/Library/Logs/Claude/mcp*.log`, Windows `%APPDATA%\Claude\logs\`.
- **Desktop Extensions (MCPB):** a **`.mcpb`** zip (legacy `.dxt`) bundling the local stdio
  server + `manifest.json` + optional `icon.png`. One-click install, deps bundled, offline, no
  OAuth. CLI: `npm i -g @anthropic-ai/mcpb`; `mcpb init` → `mcpb pack` → `mcpb validate`.
  `user_config` auto-generates a settings UI; secrets in the OS vault; `${user_config.api_key}`
  substituted at launch; `privacy_policies` array required in manifest (v0.2+). Admin allowlist
  exists for enterprise.

---

## P5 — Connectors Directory submission

The reviewed catalog (`claude.ai/directory`). Directory connectors use the same MCP infra as
custom connectors/Claude Code.

**Requirements** (`/submission` + `/review-criteria`):
- **OAuth 2.0** for any authenticated service (static bearer / query-param creds rejected).
- **Privacy policy** — HTTPS URL; covers collection, use/storage, third-party sharing,
  retention, contact. **Missing/incomplete = immediate rejection.**
- **Documentation with usage examples** — public setup + usage (a blog/help-center article
  works), live by publish date. (Practically, include **≥3 usage examples.**)
- **Test account** — credentials with populated sample data + step-by-step setup so a reviewer
  unfamiliar with your service can authorize and verify end-to-end.
- **Tool annotations** — every tool needs a `title` and the applicable `readOnlyHint:true` or
  `destructiveHint:true`. **Missing annotations is the single most common rejection reason.**
  Tool names ≤ **64 chars**. A tool mixing safe (GET/HEAD/OPTIONS) and unsafe
  (POST/PUT/PATCH/DELETE) methods is rejected.
- **Logo + favicon** assets (logo via URL or SVG upload; favicon verification).
- **MCP App screenshots** (if applicable): PNG, ≥1000px wide, 3–5 images, cropped to the
  response.
- **Production readiness** — GA date + which surfaces tested; beta/non-prod rejected.
- Run **MCP Inspector** (servers) / `claude plugin validate` (plugins; plugins also need a
  public GitHub repo) before submitting.

**Contact:** `mcp-review@anthropic.com` (support, Anthropic-held-creds auth types, firewall
issues reaching the form). **Review timeline:** Anthropic says only *"varies with queue
volume"* — **no fixed SLA is published; don't promise one.**

---

## P6 — Connector icons (two-tier model)

Claude.ai has **two connector tiers with different icon behavior**:

| Tier | How added | Icon | Why |
|---|---|---|---|
| **Connectors Directory** (Gmail, Drive, Slack, Notion…) | curated by Anthropic | branded logo | logo submitted at review, stored Anthropic-side |
| **Custom remote connectors** (user-added URL) | user pastes URL | generic globe | no runtime icon mechanism today (issue #152) |

**To get a branded icon in Claude.ai web today, the only working path is Directory submission**
(P5) — the logo/favicon supplied at review is stored on Anthropic infra and keyed to the
connector. *(Anthropic docs confirm the submission ingests a logo/favicon; they do NOT
explicitly document the runtime "not fetched live" mechanism — treat the exact mechanism as
inferred, not spec'd.)*

**`serverInfo.icons` (MCP 2025-11-25, SEP-973):** implement it anyway for portability — Claude
Desktop local extensions and other MCP clients honor it — but **gate it on
`negotiated == "2025-11-25"`** (the type doesn't exist in 2025-06-18). Shape:
```json
"serverInfo":{"name":"my-server","title":"Display Name","version":"1.0.0",
  "icons":[{"src":"data:image/svg+xml;base64,<...>","mimeType":"image/svg+xml","sizes":["any"]},
           {"src":"https://<host>/icon-128.png","mimeType":"image/png","sizes":["128x128"]}]}
```
Data URIs preferred (no external fetch). **It will NOT brand a custom remote connector in
Claude.ai web today.**

**Confirmed dead-ends for custom-connector branding** (all render the globe): `serverInfo.icons`
(any version) · `/favicon.ico` · `/favicon.svg` · `<link rel="icon">` at root · `logo_uri` in
DCR response · RFC 8414 / OIDC `logo_uri`. **MCPB local extensions** are the separate exception
— a packaged `icon.png` (512×512 rec.) renders locally in Claude Desktop.

---

## P7 — Confirmed Claude.ai client-side bugs (no server fix)

Reported under `github.com/anthropics/claude-ai-mcp`. When the server passes the Claude Code
CLI probe (P3) but fails in claude.ai web, suspect one of these:

| Issue | Symptom | Status | Workaround |
|---|---|---|---|
| [#291](https://github.com/anthropics/claude-ai-mcp/issues/291) | OAuth completes; GET polls ~5s; POST initialize never sent | closed "not planned" | expose SSE endpoint; use CLI |
| [#155](https://github.com/anthropics/claude-ai-mcp/issues/155) | Bearer never attached to POST after OAuth (web) | open | `claude mcp add --transport http` |
| [#217](https://github.com/anthropics/claude-ai-mcp/issues/217) | web skips OAuth discovery (401×3 → silent fail) | closed "not planned" | use CLI |
| [#248](https://github.com/anthropics/claude-ai-mcp/issues/248) | proxy allowlist blocks non-listed hosts | closed "not planned" | request allowlist / use CLI |
| [#246](https://github.com/anthropics/claude-ai-mcp/issues/246) | "Couldn't reach" before any traffic, `ofid_*` refs | open | check WAF; allowlist Anthropic IPs |
| [#152](https://github.com/anthropics/claude-ai-mcp/issues/152) | custom connector shows globe, no icon | open | Directory submission (P5/P6) |

**Troubleshooting handle:** Claude.ai connector errors carry a reference ID starting `ofid_` —
copy it into support/GitHub issues. The two UI errors ("Couldn't reach the MCP server" /
"Authorization with the MCP server failed") each cover several root causes.

---

## P8 — "Couldn't connect" — ordered debug checklist (Claude.ai)

1. URL publicly routable from Anthropic egress? (no RFC1918, no IPv6-only, WAF/CDN/bot-manager
   not returning 403/429 before the app)
2. Unauthenticated `POST <mcp-path>` → real **`401`** + `WWW-Authenticate: Bearer
   resource_metadata=...` (not a 200, not an MCP JSON error)?
3. `/.well-known/oauth-protected-resource` → valid JSON, `resource` **exactly** = MCP URL,
   `authorization_servers` present?
4. `/.well-known/oauth-authorization-server` → `registration_endpoint` (or CIMD) +
   `code_challenge_methods_supported:["S256"]`?
5. `WWW-Authenticate` in `Access-Control-Expose-Headers`? OPTIONS preflight → 204 with the CORS
   headers (P1)?
6. No cross-host redirects on the MCP URL?
7. Token `aud` == canonical MCP URL (exact string, RFC 8707)?
8. `GET <mcp-path>` returns `text/event-stream` or **405** (never 200+JSON/HTML)?
9. **`claude mcp add --transport http <url>` succeeds in the CLI?** → server is correct; a web
   failure is a known client bug (P7).

`GET /agent/health` is **not** a documented Claude.ai requirement (appears in some infra
probes); a `{"status":"ok"}` stub is harmless but optional.

---

## P9 — Hard-won connector failure modes (field learnings)

Distilled from a production Claude.ai connector (the `bunkerwire`/`spge-market-data` server)
and its red-team passes. These are the bugs that *passed every HTTP check and still failed* —
the expensive ones to diagnose. Treat each as a MUST-check.

**P9.1 — Version-future `initialize` field → silent "Authorization with the MCP server
failed" (CRITICAL).** The single most misleading connector bug. OAuth completes, both
`POST /mcp` calls (`initialize` + `tools/list`) return **HTTP 200**, and *then* the UI shows
**"Authorization with the MCP server failed."** It is **not** an OAuth/token problem. Claude.ai
runs a **strict schema validator on the `initialize` result for the negotiated revision**; any
field not defined in that revision (e.g. `serverInfo.icons`, a 2025-11-25/SEP-973 field, emitted
while negotiating `2025-06-18`) makes the validator reject the response as malformed — surfaced
as an auth failure, not an HTTP/JSON-RPC/protocol error.
- **Build rule:** the common-path `serverInfo` is `{name, version}` (+ `title` where defined).
  **Gate every version-future field on `negotiated_version == "<revision-that-defines-it>"`.**
  Add a test asserting `"icons" not in result.serverInfo` on the standard path.
- **Debug rule:** when "Authorization failed" appears **after** a 200 on `POST /mcp`, inspect
  the **JSON-RPC `initialize` response body first** (schema validity for the negotiated
  version), *not* the OAuth/token layer.

**P9.2 — A `401`'s `WWW-Authenticate` is derived from request data and must degrade, never
escalate.** If you build the `resource_metadata` URL from the request (`Host`/base-URL
resolver), that resolver can itself raise on a malformed `Host`. If the raise happens inside the
auth-`except` block, it escapes and the global handler turns your **401 into a 503** — a status
oracle, and it drops the RFC 9728 discovery header Claude needs. **Wrap the header derivation in
try/except**: on failure, return the 401 **without** the header rather than letting it change the
status. Probe: unauthenticated request with a malformed `Host` (e.g. `Host: :::bad`) → must still
be **401** (header-less), not 503.

**P9.3 — PRM is probed path-suffixed first.** Claude tries
`/.well-known/oauth-protected-resource/<mcp-path>` **before** the bare
`/.well-known/oauth-protected-resource`. Serve **both**; the suffixed variant's `resource` must
still be the exact canonical MCP URL.

**P9.4 — Omit `scope` from the token response when empty.** Per RFC 6749 §5.1, don't emit
`"scope":""` — omit the field entirely when there are no scopes. An empty-string scope trips
some validators.

**P9.5 — `https://claude.ai` must be hardcoded into allow-origins, not env-gated.** A connector
that only adds the claude.ai origin when an env var is set will silently fail in any environment
where that var is unset. And **never** `allow_origins=["*"]` on an app that also mounts
auth-bearing routes (CORS is set once at app construction; later routes inherit it) — drive the
allowlist from a validated config field that rejects `"*"`.

**P9.6 — No cross-host redirects on the MCP URL.** A 30x from the MCP path to a different
hostname strips the `Authorization` header. The MCP endpoint must serve content directly.

**P9.7 — SSE escape hatch for bug #291.** If Streamable HTTP stalls in claude.ai web (#291 —
GET polled every ~5s, `initialize` POST never sent), exposing a legacy SSE pair
(`GET /mcp/sse` + `POST /mcp/messages`) alongside the Streamable HTTP endpoint is a working
fallback. Keep both transports live.
