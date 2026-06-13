---
name: agent-verify
description: "Boot an agent-sdk agent and verify the whole stack in one pass: run /agent-stack-check (the agent-interop conformance umbrella) against the live endpoint, add the OAuth-chain curl probes that umbrella doesn't own (401+WWW-Authenticate, both PRM endpoints, AS metadata, CORS preflight, GET/DELETE/unknown-session /mcp, token-leak), and an OPTIONAL Playwright console smoke that degrades gracefully without a browser. Produces one advisory report; never fixes. Use after adding tools/sources/settings, or before deploy."
---

# /agent-verify — boot + full-stack verification

One command that proves an agent-sdk agent actually serves a conformant,
correctly-authenticated stack — not just that the code compiles. It is an
**orchestrator**: protocol conformance is delegated to `/agent-stack-check` (which
fans out to the four protocol advisors), and this skill adds the boot, the
OAuth-chain curl probes the umbrella doesn't own, and an optional console smoke.
**Advisory only — it lists findings; it does not edit.**

## Usage

```
/agent-verify [--port <n>] [--prod] [--no-console] [--no-stack-check]
```
- `--port` — local port to boot on (default: read `AGENT_PORT` from `.env`,
  then fall back to 8000).
- `--prod` — boot with a real `PUBLIC_URL` + `MASTER_KEY` (production fidelity: the
  card/OAuth checks need real advertised URLs). Default is `DEV_MODE=true` local.
- `--no-console` — skip the Playwright console leg.
- `--no-stack-check` — skip the conformance umbrella (e.g. when the check kit isn't installed).

## Phase 0 — Resolve port

Before booting, resolve the port:
- If `--port` was given, use that value.
- Otherwise: read `AGENT_PORT` from `.env` (`grep -E '^AGENT_PORT=' .env | cut -d= -f2`).
  If blank or absent, default to 8000 and warn: "`AGENT_PORT` not set in `.env` —
  using 8000. Run `/setup` to assign a persistent port, or pass `--port <n>`."

All subsequent `<port>` references in this skill use this resolved value.

## Phase 1 — Boot the agent

1. Boot one worker (process-local stores require it):
   `DEV_MODE=true BEDROCK_MODEL_ARN=<arn> .venv/bin/uvicorn src.main:app --port <port> --workers 1`
   — or, with `--prod`, set `PUBLIC_URL=http://localhost:<port>` + a real `MASTER_KEY`
   and `DEV_MODE=false` (a non-localhost `PUBLIC_URL` with `DEV_MODE=true` is a hard
   boot failure, by design). **`BEDROCK_MODEL_ARN` is required even in `DEV_MODE`** —
   `build_app()` constructs the model client at boot and DEV_MODE does not relax it
   (DEV_MODE relaxes only the MASTER_KEY/PUBLIC_URL/secure-transport checks). The
   surface probes never invoke the model, so a **syntactically-valid placeholder ARN**
   is enough for a surface-only run; use the real ARN (or a `model_client=`) for a run
   that also exercises tool calls. Run it in the background; capture stdout (the
   first-run **bootstrap token** prints there — it's a secret, refer to it by location).
2. Wait for readiness: poll `GET /health` until 200 (fail fast if it never comes up;
   surface the boot error, not a timeout).
3. Mint a throwaway admin API key from the bootstrap token for the authenticated
   probes. Record `BASE=http://localhost:<port>`.

## Phase 2 — Conformance umbrella (delegate, don't re-derive)

Unless `--no-stack-check`, run the agent-interop umbrella against the live surface:

```
/agent-stack-check . --live <BASE> --all
```

It detects roles per protocol and dispatches `a2a-advisor`, `a2ui-advisor`,
`ag-ui-advisor`, `mcp-advisor` (each applying its `/<p>-check` methodology) plus
the S1–S6 cross-protocol seam audits, returning one deduped, severity-ranked
verdict. **Do not restate protocol rules here** — capture its report verbatim into
this skill's output. If the kit isn't installed, skip this leg and **say so loudly**
in the report (never let a skipped umbrella read as a pass).

## Phase 3 — OAuth-chain curl probes (this skill owns these)

The probes the umbrella doesn't own (DESIGN §12) — run with `curl -i` against
`<BASE>` and assert each:

| Probe | Expect |
|---|---|
| Unauthenticated request to a protected route | `401` **and** `WWW-Authenticate: Bearer resource_metadata="<PRM URL>"`. The SDK always emits the `resource_metadata` param (it's the entry point of Claude.ai's OAuth discovery chain) — **FAIL if the param is absent** (a bare `Bearer realm=…` means a proxy stripped it or the route isn't SDK-served; Claude.ai cannot start discovery without it) |
| `GET /.well-known/oauth-protected-resource` | `200` PRM JSON (`resource` + `authorization_servers`) |
| `GET /.well-known/oauth-protected-resource/mcp` (path-suffixed variant — Claude probes this **before** the bare one; serve both) | `200` PRM whose `resource` is the canonical `/mcp` URL (not the well-known path) |
| `GET /.well-known/oauth-authorization-server` | `200` AS metadata; assert the RFC 8414 required fields `issuer`, `authorization_endpoint`, `token_endpoint`, `response_types_supported`, plus PKCE `code_challenge_methods_supported` (must include `S256`) and a client-registration path — `registration_endpoint` (DCR, what the SDK serves) **or** a CIMD URI. FAIL if no registration path is discoverable |
| CORS preflight `OPTIONS` (Origin = an allowed origin) | `204` + `Access-Control-Allow-Origin` echoing that **specific** origin (never `*`), plus `-Methods`/`-Headers`, **and** `Access-Control-Expose-Headers` listing `WWW-Authenticate` (without it a browser client can't read the 401 challenge, so OAuth discovery never starts — the SDK exposes it; FAIL if missing) |
| `GET /mcp` and `DELETE /mcp` (session lifecycle) | **unauthenticated → `401`** (auth runs before session lookup); with a valid MCP OAuth access token, the documented lifecycle status for each (not 404/405-by-accident) |
| `POST /mcp` with an unknown `Mcp-Session-Id` | **unauthenticated → `401`**; **with a valid token → `404`** (unknown session, not a 500) — the 404 path is only reachable authenticated, so mint/obtain an MCP token (PKCE chain) before asserting it |
| **Token-leak assertion** | no `MASTER_KEY`, bootstrap token, minted key, or credential value appears in any response body, error, log line, or (for `--prod`) the built image's layers / `direct_url.json` |

Each probe failing is a finding with the request, the expected vs actual, and the
owning surface. The token-leak assertion is **Critical** if it ever trips. The
`/mcp` rows are **auth-gated**: every `/mcp` method returns `401` without a bearer,
so obtain an MCP OAuth access token (full PKCE chain) to reach the lifecycle/unknown-
session statuses — otherwise assert only the `401`, and say the deeper check needs a token.

The **session- and JSON-RPC-level** MCP checks — `MCP-Protocol-Version` handling
(bad value → `400`), `Origin` rejection on `/mcp` (DNS-rebinding defense), token
audience (`aud`) binding, and the `initialize` version/capabilities echo — are owned by
the conformance umbrella (Phase 2 → `mcp-advisor`), not these curl probes. If you pass
`--no-stack-check`, **say in the report that those checks did not run** (they are a
coverage gap, not a pass).

## Phase 4 — Console smoke (OPTIONAL — degrades gracefully)

Unless `--no-console` **and only if a browser is available** (Playwright MCP /
installed browser): load `<BASE>/admin`, mint a key via the bootstrap flow, open a
tool with a `sample`, click "Try", and confirm an artifact/A2UI card renders without
a console error. **If no browser is present, skip this leg and mark it
`SKIPPED (no browser)` — never fail the run for a missing browser** (DESIGN §11:
this is an optional leg, brittle on headless runners by design).

## Phase 5 — Report + teardown

Consolidate the three legs into one advisory report; then **tear the booted agent
down** (kill the uvicorn process) and remove any throwaway key/data dir created for
the run.

## Steps

1. Boot (Phase 1); fail fast with the boot error if `/health` never 200s.
2. Run `/agent-stack-check --live` (Phase 2) unless skipped; capture its verdict.
3. Run the OAuth-chain curl probes (Phase 3); record pass/fail per probe.
4. Console smoke (Phase 4) if a browser exists; else mark SKIPPED.
5. **Codify** — for each critical/high finding, invoke `/codify <finding-summary>`
   so the root cause becomes a permanent LRN check wired into future redteam runs.
6. Synthesize the report (Phase 5); **tear down the agent**; hand findings to the
   user. **Do not fix** — point each finding at `/add-tool`, `/add-source`,
   `sdk-advisor`, or the owning `/<p>-check` for remediation.

## Report format

```
## Agent verification — <agent> @ <BASE>   Mode: <dev|prod>
Boot:            <ok | failed: …>
Stack-check:     <verbatim OVERALL verdict | SKIPPED (kit not installed)>
OAuth-chain probes:
  401 + WWW-Authenticate
    (resource_metadata present) PASS|FAIL (…)
  PRM (root)                  PASS|FAIL
  PRM (/mcp suffix)           PASS|FAIL
  AS metadata fields          PASS|FAIL (missing: …)
  CORS preflight              PASS|FAIL
  GET/DELETE /mcp             PASS|FAIL
  unknown-session POST /mcp   PASS|FAIL
  token-leak                  PASS|FAIL  ← Critical if FAIL
Console smoke:    PASS | FAIL | SKIPPED (no browser)
OVERALL:          PASS | FAIL  (FAIL if any Critical/High, or any OAuth-chain probe failed)
Next:             <which skill/advisor owns each open finding>   (no commit made)
```

## Notes

- **Composition, not duplication.** Conformance lives in the check kit; this skill
  owns boot + the curl OAuth chain + console. If a protocol rule seems wrong, fix it
  in that protocol's pair, not here.
- **Graceful degradation is intentional.** A missing browser or a missing check kit
  reduces coverage — the report says exactly which legs ran, so reduced coverage
  never masquerades as a clean pass.
- **No secrets in the report.** Bootstrap tokens, minted keys, and credential values
  are referenced by location/result, never printed.
- **A `DEV_MODE` local boot proves structure, not Claude.ai connectivity.** It confirms
  the OAuth chain is shaped correctly, but the PRM `resource` and AS endpoints will point
  at `http://localhost:<port>` — invalid for a production Claude.ai connector, which
  needs a publicly-routable **HTTPS** `PUBLIC_URL`. Use `--prod` (with a tunnel or a
  deployed instance) for a connectivity-fidelity check; say so if the run was dev-only.
