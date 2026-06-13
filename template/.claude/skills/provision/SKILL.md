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
   - **Model backend routing vars** (non-secret) are set:
     - Bedrock: `BEDROCK_MODEL_ARN` + `BEDROCK_REGION` — required even in `DEV_MODE`.
     - OpenAI: `OPENAI_MODEL` must be set; `OPENAI_BASE_URL` optional.
     - Azure OpenAI: `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_DEPLOYMENT` must be set.
     - The LLM API key is **NOT expected in `.env`** — it is seeded in Phase 3 below
       (into the encrypted credential store). Do NOT treat a missing
       `OPENAI_API_KEY` in `.env` as a gap; it is correct for it to be absent.
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
   bootstrap token pattern (the SDK prints a UUID or fixed-format token). Capture
   it into a shell variable, then **immediately delete `$tmplog`** — never leave
   the token in a file.
   Tell the user: "Bootstrap token captured from stdout (not shown). Minting the
   first admin API key now."
   `POST /admin/bootstrap` with the token → receive the first API key.
   Store the key as `ADMIN_KEY` for subsequent calls. Never echo either value.

   **Idempotency:** if `/admin/bootstrap` returns 409 (already bootstrapped), the
   agent was previously provisioned. Check whether
   `workspace/adr/ADR-000-<env>-credentials.md` already exists:
   - If it exists: the prior key is available; skip re-writing and skip
     credential seeding (Phase 3) or prompt to re-seed.
   - If it is **missing**: warn the user — "Agent already bootstrapped but
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

7. **LLM model-backend API key** (skip for Bedrock — IAM auth, no key needed).

   If `OPENAI_MODEL` or `AZURE_OPENAI_ENDPOINT` is set in `.env`:

   a. Check whether the key is already stored:
      ```
      GET /admin/api/credentials
      Authorization: Bearer <ADMIN_KEY>
      ```
      Examine `response.model.fields`:
      - For OpenAI: check `{"name": "openai_api_key", "set": true}`
      - For Azure: check `{"name": "azure_openai_api_key", "set": true}`

   b. If already set → print "LLM key: already seeded — skipped." and continue.
      **Do not re-prompt.** This is the idempotency gate that eliminates the
      "asked over and over" problem.

   c. If not set → ask the user **once** for the key (never echo it):
      ```
      PUT /admin/api/credentials/__model__/<field_name>
      Authorization: Bearer <ADMIN_KEY>
      {"value": "<key>"}
      ```
      Where `<field_name>` is `openai_api_key` (OpenAI) or `azure_openai_api_key`
      (Azure). Confirm 200. Never log the value.

   Note: the agent must be restarted after seeding so `_build_model_client()`
   re-reads the store. The teardown in Phase 5 and any subsequent boot will
   pick it up automatically.

8. **Source credentials.** Read `src/sources/` to discover all `SourceAdapter`
   subclasses and their `CredentialField` definitions.

9. For each source, list the required credential fields. Ask the user to supply
   each value **interactively** (one field at a time). Never read from env vars
   or argv — the only safe path is the credential store.

   **Idempotency:** before prompting for a field, check its `"set"` status from
   `GET /admin/api/credentials`. If `"set": true`, skip and print "already seeded."

10. For each field value received:
    ```
    PUT /admin/api/credentials/<source_name>/<field_name>
    Authorization: Bearer <ADMIN_KEY>
    {"value": "<value>"}
    ```
    Confirm 200. Never log the value.

11. **Health-check each source.**
    `POST /admin/api/sources/<source_name>/health` — expect `{"status": "ok"}`.
    If any source fails: report which source, the error message (but not the
    credential value), and the remediation (re-seed that field or check the
    upstream service).

### Phase 4 — Live tool call (optional)

12. Unless `--skip-tool-call`: find the first tool with a `sample` value in
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

13. Stop the background uvicorn process.

14. Report:

```
## Provision — <agent-name>   Port: <port>   Env: <dev|prod>
.env:            OK
venv:            OK (<python version>)
SDK:             agent-sdk @ <sha7>
Boot:            OK
Bootstrap:       key minted (not shown)
ADR-000:         written to workspace/adr/ADR-000-<env>-credentials.md
LLM key:         Bedrock/IAM (no key) | seeded → __model__ | already seeded (skipped)
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
