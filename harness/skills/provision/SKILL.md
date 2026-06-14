---
name: provision
category: core
description: "Full zero-to-running setup for a new agent: verify .env, boot the agent, walk the bootstrap-token flow, seed all source credentials into the encrypted store, verify each source's health_check, and confirm a live tool call works."
---

# /provision — Full agent setup walkthrough

One command that takes an agent from a fresh clone (or a fresh `/new-agent`
scaffold) to a fully-operational, credential-loaded, live-verified instance.

## Usage

```
/provision [--port <n>] [--env dev|prod] [--skip-tool-call]
```

- `--port` — local port to boot on (default: read `AGENT_PORT` from `.env`,
  then fall back to 8000)
- `--env` — target environment: `dev` (default) or `prod`; controls which
  ADR-000 credentials file is written (`ADR-000-dev-credentials.md` or
  `ADR-000-prod-credentials.md`)
- `--skip-tool-call` — omit the live tool-call verification leg (useful when
  credentials are real but no upstream quota is available yet)

## Steps

### Phase 0 — Resolve port

Before any other step, resolve the port to use:
- If `--port` was given, use that value.
- Otherwise: read `AGENT_PORT` from `.env` (`grep -E '^AGENT_PORT=' .env | cut -d= -f2`).
  If blank or absent, default to 8000 and warn: "`AGENT_PORT` not set in `.env` —
  using 8000. Run `/setup` to assign a persistent port, or pass `--port <n>`."

All subsequent references to `<port>` in this skill use this resolved value.

### Phase 1 — Pre-flight checks

1. Read `.env` and `.env.example`. Verify:
   - `MASTER_KEY` is set and non-empty (never echo the value — only confirm presence).
     If `.env` doesn't exist yet (fresh scaffold before first run), that's OK — step 3
     will create the venv; the user should generate `MASTER_KEY` first via
     `python -c "import secrets; print(secrets.token_urlsafe(48))"` and write it to
     `.env`. Stop and instruct if `MASTER_KEY` is absent.
   - `PUBLIC_URL` is empty or `http://localhost:<port>` (for local dev).
   - `DEV_MODE` is `true` for local runs.
   - Model backend env var is set (`BEDROCK_MODEL_ARN` + `BEDROCK_REGION`, or
     `AZURE_OPENAI_*`, etc.) — required even in `DEV_MODE`.
   Report any gap as a blocking item with the exact fix.

2. Read `pyproject.toml`. Report the current `agent-sdk` SHA so the operator
   knows which SDK version is running.

3. Check that `.venv/` exists. If not:
   ```bash
   python3.12 -m venv .venv && VIRTUAL_ENV=.venv uv pip install -e ".[dev]"
   ```
   Report any install failure with the full error — do NOT paper over it.

### Phase 2 — Boot + bootstrap

4. Check the port is free before booting:
   ```bash
   lsof -i :<port> -t
   ```
   If a PID is returned, ask the user: "Port `<port>` is in use (PID `<pid>`). Kill
   it and continue, or use the already-running instance, or abort?" Never kill
   silently.

5. Boot the agent, redirecting stdout to a temp file from the start:
   ```bash
   tmplog=$(mktemp /tmp/provision-XXXXXX.log)
   DEV_MODE=true .venv/bin/uvicorn src.main:app --port <port> --workers 1 \
     > "$tmplog" 2>&1 &
   ```
   Run in background. Poll `GET /health` until 200 (timeout 30 s; if it never
   comes up, cat `$tmplog` to show the boot error, then delete the file and stop).

6. **Bootstrap token.** After `/health` returns 200, grep `$tmplog` for the
   bootstrap banner (`=== agent-sdk first-run bootstrap ===`), then extract the
   `token_urlsafe(32)` value on the following indented line. Capture it into a
   shell variable, then **immediately delete `$tmplog`** — never leave the token
   in a file.
   Tell the user: "Bootstrap token captured from stderr (not shown). Minting the
   first admin API key now."
   `POST /admin/api/keys` with the token supplied as the `X-Bootstrap-Token`
   request header → receive the first API key in the response `plaintext` field.
   Store the key as `ADMIN_KEY` for subsequent calls. Never echo either value.

   **Idempotency:** before attempting the bootstrap mint, check whether the agent
   has already been provisioned. The preferred method is checking whether
   `workspace/adr/ADR-000-<env>-credentials.md` already exists. If you want to
   probe the server: `GET /admin/api/keys` without a bearer token returns **401**
   regardless of whether keys exist — it cannot distinguish provisioned from
   unprovisioned via an unauthenticated call. Use the ADR-000 file existence
   check instead.
   - If ADR-000 exists: the prior key is available; skip re-minting and skip
     credential seeding (Phase 3) or prompt to re-seed.
   - If ADR-000 is **missing** but a bootstrap attempt returns 401 ("invalid or
     expired bootstrap token"), the agent was previously bootstrapped and the
     token was already consumed. Warn the user — "Agent already bootstrapped but
     ADR-000 not found. To restore admin access, rotate the API key via the
     admin console and re-run `/provision`." Halt.

6b. **Write ADR-000 credentials file.** Immediately after minting the first
    admin API key (step 6), write the key to a gitignored workspace file so
    skills like `/acceptance` can authenticate autonomously on future runs.
    Create `workspace/adr/` if it does not exist.

    File: `workspace/adr/ADR-000-<env>-credentials.md` (env = `dev` or `prod`)

    ```markdown
    ---
    id: ADR-000-<env>
    env: <env>
    endpoint: http://localhost:<port>
    admin_key: <ADMIN_KEY>
    minted: <ISO date>
    ---
    This file is auto-generated by /provision. It holds the admin API key used
    by /acceptance and other skills for autonomous agent access. Never commit.
    Regenerate by re-running /provision if lost.
    ```

    Never print the key to the terminal — write it only to this file.

    Ensure `workspace/adr/ADR-000-*-credentials.md` is listed in `.gitignore`.
    If `.gitignore` does not already contain this pattern, append:
    ```
    workspace/adr/ADR-000-*-credentials.md
    ```

### Phase 3 — Credential seeding

7. Read `src/sources/` to discover all `SourceAdapter` subclasses and their
   `CredentialField` definitions.

8. For each source, list the required credential fields. Ask the user to supply
   each value **interactively** (one field at a time). Never read from env vars
   or argv — the only safe path is the credential store.

9. For each field value received:
   First check whether the field is already set by inspecting the `"set"` boolean
   returned by `GET /admin/api/credentials` for that source. If `"set": true`,
   ask: "Field `<field_name>` for `<source_name>` is already set. Overwrite? [y/n]"
   Skip the write if the user answers `n`.
   To write (new or overwrite):
   `PUT /admin/api/credentials/<source_name>/<field_name>` with `{"value": "..."}`.
   Confirm the response returns `{"set": true}`. Never log the value.

9b. **Seed the `__model__` namespace (LLM API key).**
    Check whether the LLM API key is already seeded:
    `GET /admin/api/credentials` (with `Authorization: Bearer <ADMIN_KEY>`).
    The endpoint always returns all namespaces — there is no `?source=` filter.
    Inspect `response["model"]["fields"]` and look for the relevant field's
    `"set"` boolean. If `"set": true`, report
    `__model__: already seeded — no action needed` and continue.
    If not set (or the source is absent), prompt the operator to supply the key
    for the configured LLM backend. Use the exact field names from the SDK's
    `_MODEL_FIELDS` — shorthand names like `api_key` do not resolve:
    - OpenAI: `openai_api_key`
    - Azure OpenAI: `azure_openai_api_key` only.
      Note: `endpoint` and `deployment` are non-secret routing values stored as
      env vars (`AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`) in `.env`,
      not in the credential store.
    - Anthropic: NOT YET IMPLEMENTED — skip; do not seed an Anthropic key
      until the SDK adds support. (Field is reserved for future use.)
    Seed each applicable field via `PUT /admin/api/credentials/__model__/<field_name>`
    with `{"value": "..."}`. Confirm `{"set": true}` for each. **Never print the value.**

    **Bedrock credentials** use a dedicated `__bedrock__` namespace, not `__model__`.
    See step 9c below.

9c. **Seed the `__bedrock__` namespace (AWS Bedrock only).**
    Skip this step if the agent is not configured to use Bedrock
    (i.e. `BEDROCK_MODEL_ARN` is not set in `.env`).
    Check: `GET /admin/api/credentials`, then inspect `response["bedrock"]["fields"]`.
    If the fields are already set, report `__bedrock__: already seeded — no action needed`.
    Otherwise prompt the operator to supply:
    - `aws_access_key_id`
    - `aws_secret_access_key`
    - `bearer_token` (optional — only if the deployment uses token-based auth)
    Note: `region` is a non-secret env var (`BEDROCK_REGION`) stored in `.env`,
    not in the credential store — do not prompt for it here.
    Seed via `PUT /admin/api/credentials/__bedrock__/<field_name>` with
    `{"value": "..."}`. Confirm `{"set": true}` for each. **Never print the value.**
    This aligns with `/setup` Phase 3 step 5, Bedrock sub-bullet.

10. **Health-check each source.**
    Call `GET /admin/api/overview` (with `Authorization: Bearer <ADMIN_KEY>`)
    and inspect the `adapters[].healthy` boolean for each adapter. A `false`
    value means the adapter's `health_check()` failed.
    If any adapter has `"healthy": false`: report the adapter name and its
    `healthy: false` status, and advise the user to re-seed that field or
    check the upstream service. (The overview response does not include error
    detail; for deeper diagnostics call `GET /admin/api/tools` or consult the
    agent's health_check logs.)

### Phase 4 — Live tool call (optional)

11. Unless `--skip-tool-call`: find the first tool with a `sample` value in
    `src/tools/`. If no tool has a `sample` value, skip this step and note in
    the report: `Live tool call: SKIPPED (no sample value in any tool)` — this
    is not a failure.
    Otherwise, run it via the A2A endpoint:
    ```
    POST /v1/message:send
    Authorization: Bearer <ADMIN_KEY>
    {"message": {"role": "user", "parts": [{"kind": "text", "text": "<sample>"}]}}
    ```
    Confirm a non-error response and at least one artifact part.

### Phase 5 — Teardown + report

12. Stop the background uvicorn process.

13. Report:

```
## Provision — <agent-name>   Port: <port>   Env: <dev|prod>
.env:            OK
venv:            OK (<python version>)
SDK:             agent-sdk @ <sha7>
Boot:            OK
Bootstrap:       key minted (not shown)
ADR-000:         written to workspace/adr/ADR-000-<env>-credentials.md
__model__:       seeded | already set | MISSING
__bedrock__:     seeded | already set | SKIPPED (not Bedrock)
Sources:         <N> seeded
  <source>: health OK | FAIL (<error category>)
Live tool call:  PASS | SKIPPED | FAIL (<error category>)
OVERALL:         READY | NEEDS ATTENTION

Next: /agent-verify (conformance probes); then /acceptance (domain correctness).
      .env and ADR-000-<env>-credentials.md are gitignored — never commit either.
```

## Rules

- **No secrets in output.** Credential values, the bootstrap token, and the admin
  key are never printed — only their presence/absence and HTTP status codes.
- **Never commit `.env`.** If `.gitignore` is absent or does not exclude `.env`,
  add it before proceeding and warn the user.
- This skill does not run `/agent-verify` — that is the next step. `/provision`
  proves the agent is running and credentials are seeded; `/agent-verify` proves
  the protocol surfaces conform.
