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
/provision [--port 8000] [--skip-tool-call]
```

- `--port` — local port to boot on (default 8000)
- `--skip-tool-call` — omit the live tool-call verification leg (useful when
  credentials are real but no upstream quota is available yet)

## Steps

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
   bootstrap token pattern (the SDK prints a UUID or fixed-format token). Capture
   it into a shell variable, then **immediately delete `$tmplog`** — never leave
   the token in a file.
   Tell the user: "Bootstrap token captured from stdout (not shown). Minting the
   first admin API key now."
   `POST /admin/bootstrap` with the token → receive the first API key.
   Store the key as `ADMIN_KEY` for subsequent calls. Never echo either value.

   **Idempotency:** if `/admin/bootstrap` returns 409 (already bootstrapped), the
   agent was previously provisioned. Skip credential seeding (Phase 3) or prompt:
   "Agent already bootstrapped — re-seed credentials or skip to health-check?"

### Phase 3 — Credential seeding

7. Read `src/sources/` to discover all `SourceAdapter` subclasses and their
   `CredentialField` definitions.

8. For each source, list the required credential fields. Ask the user to supply
   each value **interactively** (one field at a time). Never read from env vars
   or argv — the only safe path is the credential store.

9. For each field value received:
   `POST /admin/credentials/<source_name>/<field_name>` with `{"value": "..."}`.
   Confirm the response is 200. Never log the value.

10. **Health-check each source.**
    `POST /admin/sources/<source_name>/health` — expect `{"status": "ok"}`.
    If any source fails: report which source, the error message (but not the
    credential value), and the remediation (re-seed that field or check the
    upstream service).

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
## Provision — <agent-name>   Port: <port>
.env:           OK
venv:           OK (<python version>)
SDK:            agent-sdk @ <sha7>
Boot:           OK
Bootstrap:      key minted (not shown)
Sources:        <N> seeded
  <source>: health OK | FAIL (<error category>)
Live tool call: PASS | SKIPPED | FAIL (<error category>)
OVERALL:        READY | NEEDS ATTENTION

Next: /agent-verify (full OAuth-chain probes); commit .env is git-ignored.
```

## Rules

- **No secrets in output.** Credential values, the bootstrap token, and the admin
  key are never printed — only their presence/absence and HTTP status codes.
- **Never commit `.env`.** If `.gitignore` is absent or does not exclude `.env`,
  add it before proceeding and warn the user.
- This skill does not run `/agent-verify` — that is the next step. `/provision`
  proves the agent is running and credentials are seeded; `/agent-verify` proves
  the protocol surfaces conform.
