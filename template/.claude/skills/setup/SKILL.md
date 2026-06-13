---
name: setup
description: "Bootstrap an agent-template clone into a working agent: interview for name/domain/sources/auth/model/contrib, preflight SDK git access via git ls-remote (no local SDK repo required), substitute all {{placeholders}} across every file, generate MASTER_KEY into .env, write .harness-manifest.json, then walk first run + console. Run once, from inside the freshly-cloned template repo. After setup: /analyze → /todos → /wave."
---

# /setup — Bootstrap a cloned agent-template

Turns a freshly-cloned `wailuen/agent-template` repo into a fully-initialized,
running agent — no SDK repo required. It does exactly what `/new-agent` does for
its scaffolded repos, but starting from a clone you already have.

**Run this once, from inside the cloned repo.**

## Usage

```
/setup [--sdk-url <git-url>] [--sdk-ref <tag-or-sha>] [--no-run]
```

- `(no args)` — interactive; uses the canonical SDK URL, resolves latest SHA
- `--sdk-url` — override the SDK git URL (default: `git@github.com:wailuen/a2a-sdk.git`)
- `--sdk-ref` — pin to a specific SHA or tag instead of resolving latest HEAD
- `--no-run` — scaffold only; skip the first-run + console walkthrough

**URL formats (important distinction):**
- `{{SDK_GIT_URL}}` placeholder (pip use): scheme-less, slash form —
  e.g. `git@github.com/wailuen/a2a-sdk.git`. Pip prepends `git+ssh://` → full pip
  VCS URL: `git+ssh://git@github.com/wailuen/a2a-sdk.git`.
- `git ls-remote` (git-native use): strip the `git+` prefix — use
  `ssh://git@github.com/wailuen/a2a-sdk.git`. Never pass `git+ssh://` to `git
  ls-remote`; that prefix is pip-only and git does not understand it.

## Idempotency guard

Before starting, check whether placeholders are already substituted:

```bash
grep -rn '{{' . --include='*.toml' --include='*.py' --include='*.md' \
  --include='*.json' --include='*.txt' --include='*.example' --include='Dockerfile' \
  --exclude-dir='.claude' --exclude-dir='.venv' --exclude-dir='__pycache__'
```

If this returns **no matches**: placeholders are already filled — this agent is
already initialized. Ask: "Agent appears already initialized. Re-run setup? [y/n]"
- `n` → stop: "Already set up — use `/provision`, `/add-tool`, `/add-source` to
  continue building."
- `y` → proceed (re-run scenario; see Phase 3 for `.env` handling).

## Phase 0 — Interview (one pass, confirm before writing)

Collect, then echo back a summary for confirmation before touching any file:

1. **Name** — kebab-case (`acme-research`). Derive `{{AGENT_MODULE}}` = snake_case
   (`acme_research`); reject names that aren't valid once snake-cased.
2. **Domain / persona** — one or two sentences: what the agent does and its voice.
   Becomes `src/persona.py`'s `PERSONA`.
3. **Upstream sources** — for each external API: a short name (snake_case →
   `source_name`), its base host(s) (→ `allowed_hosts`), and its auth shape
   (bearer token / api-key header / OAuth client-credentials / none).
4. **Client auth model** — how callers authenticate to this agent: API keys (admin
   console) and/or the built-in OAuth 2.1 chain for MCP. Note: a Claude.ai MCP
   connector uses DCR-based OAuth automatically — static bearer tokens are not
   supported on that surface.
5. **Model backend** — Bedrock (default) or another `ModelClient`. Collect:
   - Bedrock: `BEDROCK_REGION` (e.g. `us-east-1`) and `BEDROCK_MODEL_ARN` (the
     full `arn:aws:bedrock:…` string). Both required even in `DEV_MODE`.
   - Azure OpenAI / OpenAI: collect the relevant endpoint and key env var names.
   - Other: note the env vars needed.
6. **Contrib modules** — any of `action_gate`, `obo`, `commitments`, `webhooks`.
   **Warn that contrib is EXPERIMENTAL** (may change in minors, excluded from
   SemVer). `obo` requires the `[obo]` extra (MSAL); this will modify the
   dependency line in `pyproject.toml`.

7. **Dev port** — scan ports 8000–8020 for availability and present the options:
   ```bash
   python3 -c "
   import socket
   free = []
   for p in range(8000, 8021):
       try:
           s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
           s.bind(('', p)); s.close(); free.append(str(p))
           if len(free) >= 5: break
       except OSError: pass
   print(' '.join(free) if free else '(none free in 8000-8020)')
   "
   ```
   Present: "Available ports: `<list>`. Use `<first>` (recommended) or enter another:"
   Wait for the user's choice (Enter = accept first suggestion). This becomes
   `AGENT_PORT` in `.env`. If all 8000–8020 are taken, let the user enter any port.

Echo the full summary. Wait for explicit confirmation before proceeding.

## Phase 1 — Preflight git access

Unlike `/new-agent`, there is no local sibling SDK repo. Access is always via the
remote.

1. **Determine SDK git URL.**
   - If `--sdk-url` is provided, use it.
   - Otherwise, default is `git@github.com:wailuen/a2a-sdk.git`.
   - Confirm with the user: "SDK URL: `<url>`. Press Enter to accept or type a
     different URL." This allows fork overrides without a flag.
   - **Fork warning:** if the URL does not contain `wailuen/a2a-sdk`, emit:
     "This agent will be pinned to a fork (`<url>`). Verify this is intentional."

2. **Verify SSH access** (if SSH URL):
   ```bash
   ssh -T git@github.com
   ```
   Expect the GitHub authenticated greeting. On failure emit:
   "SSH access to `github.com` failed. Load your key: `ssh-add ~/.ssh/id_ed25519`.
   For CI, ensure the key is in `SSH_AUTH_SOCK`."
   Offer HTTPS fallback: "Switch to `https://github.com/wailuen/a2a-sdk.git`? [y/n]"
   If yes, re-run this phase with HTTPS. Do not stop without offering the fallback.

3. **Resolve the target SHA** (capture to a variable — do not echo raw output):
   - If `--sdk-ref` is a 40-char hex SHA: use it verbatim. Warn: "SHA `<sha7>`
     provided — cannot validate remotely without a full fetch; `pip install` will
     fail if this SHA does not exist in the SDK repo."
   - If `--sdk-ref` is a tag (e.g. `v1.3.0`): resolve with
     `git ls-remote ssh://git@github.com/<path> refs/tags/v1.3.0` (or
     `git ls-remote https://github.com/<path> refs/tags/v1.3.0` for HTTPS).
     Extract the SHA from the first field.
   - Otherwise (no `--sdk-ref`):
     ```bash
     SHA=$(git ls-remote ssh://git@github.com/<path> HEAD | awk '{print $1}')
     ```
     Note: use `ssh://` (not `git+ssh://`) for `git ls-remote`. Extract only the
     40-char SHA field — do not echo the raw `git ls-remote` output to chat.
   - Stop with the exact error if unreachable.

4. **Resolve the tag** (comment-only, `{{SDK_TAG}}`):
   ```bash
   git ls-remote --tags ssh://git@github.com/<path>
   ```
   Find the most recent semver tag (e.g. `v1.3.0`). If none, use `"HEAD"`.

5. **Derive URLs for the template:**
   - `{{SDK_GIT_URL}}` (pip, scheme-less): `git@github.com/wailuen/a2a-sdk.git`
     (note: slash form — pip constructs `git+ssh://git@github.com/wailuen/...`)
   - For `git ls-remote` calls (this phase only): `ssh://git@github.com/wailuen/...`
     These two forms are different by design; do not confuse them.

## Phase 2 — Substitute placeholders

Substitute **every** `{{PLACEHOLDER}}` across all files in the repo. Files that
contain them: `CLAUDE.md`, `.env.example`, `Dockerfile`, `pyproject.toml`,
`README.md`, `src/persona.py`, `src/config.py`, `src/main.py`,
`src/sources/sample_api.py`, and `.claude/.harness-manifest.json`.

Placeholders to substitute:
- `{{AGENT_NAME}}` → the kebab-case name from Phase 0
- `{{AGENT_MODULE}}` → the snake_case module name
- `{{SDK_GIT_URL}}` → the scheme-less URL (e.g. `git@github.com/wailuen/a2a-sdk.git`)
- `{{SDK_SHA}}` → the 40-char SHA from Phase 1
- `{{SDK_TAG}}` → the resolved tag from Phase 1

**Note on `.env.example`:** Phase 2 substitutes it before Phase 3 copies it to
`.env`. Phase 3 picks up the already-substituted version.

**Special handling:**
- **HTTPS transport**: rewrite the dependency line's scheme from `git+ssh://` to
  `git+https://` in `pyproject.toml`.
- **`obo` selected in Phase 0**: insert `[obo]` between the package name and `@`
  so the line reads `"agent-sdk[obo] @ git+ssh://{{SDK_GIT_URL}}@{{SDK_SHA}}"`.

**Verify substitution** — after all substitutions, run two checks:

*Check 1 — no survivors (outside `.claude/`):*
```bash
grep -rn '{{' . --include='*.toml' --include='*.py' --include='*.md' \
  --include='*.json' --include='*.txt' --include='*.example' --include='Dockerfile' \
  --exclude-dir='.claude' --exclude-dir='.venv' --exclude-dir='__pycache__'
```
Any match is a bug — stop and show the file and line.
Note: `.claude/` is excluded because skill docs contain `{{placeholder}}` examples
that are intentional. `.claude/.harness-manifest.json` is verified separately in
Phase 4.

*Check 2 — well-formed pip VCS URL in `pyproject.toml`:*
```bash
grep -E 'git\+(ssh|https)://[^@]+@[0-9a-f]{40}' pyproject.toml
```
If this grep returns no match, the SHA was not substituted correctly (e.g. partial
SHA, wrong format). Stop: "ERROR: malformed or missing pip VCS URL in
`pyproject.toml`."

**Wire sources:**
- Rename `src/sources/sample_api.py` → `src/sources/<first_source>.py`.
- For each additional declared source, copy the stub and rename to
  `src/sources/<nth_source>.py`.
- Wire each into `src/main.py`'s `register_source(...)` and `toolsets=[...]`.
- Drop the sample widget tool/source if real sources were declared; keep as worked
  example if none were declared.

**Create `.gitignore`** (if absent):
```
.env
/data
.venv
__pycache__
.pytest_cache
*.pyc
```

## Phase 3 — Generate MASTER_KEY

1. Generate and write the key atomically — never send it to stdout:
   ```bash
   python - <<'EOF'
   import secrets, pathlib
   key = secrets.token_urlsafe(48)
   env = pathlib.Path('.env')
   if env.exists():
       content = env.read_text()
       env.write_text(content.replace('MASTER_KEY=\n', f'MASTER_KEY={key}\n', 1)
                             .replace('MASTER_KEY= \n', f'MASTER_KEY={key}\n', 1))
   else:
       content = pathlib.Path('.env.example').read_text()
       env.write_text(content.replace('MASTER_KEY=\n', f'MASTER_KEY={key}\n', 1))
   EOF
   ```
2. **If `.env` did not exist:** the script above creates it from `.env.example` with the key already set. Also write the model backend vars collected in Phase 0 (e.g. `BEDROCK_MODEL_ARN=`, `BEDROCK_REGION=`) and the chosen port (`AGENT_PORT=<port>`) into the new `.env`.
   **If `.env` already exists (re-run):** the script updates only the `MASTER_KEY=` line in-place. Update `AGENT_PORT=` only if it is currently blank. Warn: "Existing `.env` preserved — only `MASTER_KEY` regenerated. Verify `BEDROCK_MODEL_ARN`, `BEDROCK_REGION`, and `AGENT_PORT` are still set if required."
3. **The key never leaves the file.** Never print or echo it to chat, a log, or shell history. Tell the user:
   "`MASTER_KEY` generated and written to `.env` (git-ignored). Rotate later with
   `python -m agent_sdk rotate-master-key` — offline only."
4. Leave `PUBLIC_URL` empty and `DEV_MODE=false`; the walkthrough runs in
   `DEV_MODE=true` locally.

## Phase 4 — Manifest verification

The template ships `.claude/.harness-manifest.json` with `{{SDK_SHA}}`
placeholders. Phase 2 already substituted those with the real SHA (the manifest
is explicitly included in the Phase 2 substitution pass, but excluded from the
Phase 2 survivor grep since `.claude/` is excluded there). Verify here:
```bash
grep '{{' .claude/.harness-manifest.json
```
Any match means Phase 2 missed the manifest — stop and re-run substitution on
that file before proceeding. The manifest is the anchor for `/upgrade`'s conflict
detection and must be clean.

## Phase 5 — First run + console walkthrough

**If `--no-run` was set:** skip this phase entirely. Print:
"Scaffold complete. Run `/provision` when ready to boot and walk the console."
Then go directly to the Handoff.

**Otherwise:**

1. Create the venv and install:
   ```bash
   python3.12 -m venv .venv
   VIRTUAL_ENV=.venv uv pip install -e ".[dev]"
   ```
   If `uv` is not installed: fall back to `.venv/bin/pip install -e ".[dev]"`.
   If install fails on auth (SDK URL unreachable), point back to Phase 1
   remediation. Don't paper over it.

2. Run the template tests:
   ```bash
   .venv/bin/python -m pytest -q
   ```
   Confirm a green baseline before adding anything.

3. **Read the chosen port:**
   ```bash
   PORT=$(grep -E '^AGENT_PORT=' .env | cut -d= -f2)
   PORT=${PORT:-8000}
   ```
   **Check the port is free:**
   ```bash
   lsof -i :$PORT -t
   ```
   If a PID is returned: "Port `$PORT` is in use (PID `<pid>`). Kill it,
   pick a different port (update `AGENT_PORT` in `.env`), or abort?"
   Never kill silently.

4. Boot:
   ```bash
   DEV_MODE=true .venv/bin/uvicorn src.main:app --port $PORT --workers 1
   ```
   One worker is mandatory (task store / SSE / rate-limiter are process-local).
   Run in background, redirect stdout to a temp file.

5. Walk the console: open `http://localhost:$PORT/admin`. The first run prints a
   single-use **bootstrap token to stdout** — grep the temp file for it and paste
   into the console to mint the first admin API key. Delete the temp log file
   immediately after capturing the token. Then: add each source's credentials
   (stored encrypted, never in env), and confirm a tool renders in the "Try"
   panel.
   The bootstrap token and minted key are secrets — refer to them by location,
   don't echo.

6. Tear the dev server down when the walkthrough is done.

## Steps

1. **Idempotency guard** — grep for `{{` outside `.claude/`; ask before re-running.
2. **Phase 0 — Interview** — name, domain, sources, auth, model backend + ARN, contrib; confirm before writing.
3. **Phase 1 — Preflight git access** — confirm SDK URL, verify SSH, resolve SHA + tag via `git ls-remote` (not `git+ls-remote`); stop on failure; offer HTTPS fallback.
4. **Phase 2 — Substitute placeholders** — all files including manifest; wire sources; grep survivors outside `.claude/`; verify pip VCS URL format.
5. **Phase 3 — Generate MASTER_KEY** — write to `.env` (create or update-in-place); write model backend vars; never echoed.
6. **Phase 4 — Manifest verification** — confirm `.claude/.harness-manifest.json` has no remaining `{{`.
7. **Phase 5 — First run** (skip with `--no-run`) — install venv; test; port check; boot; bootstrap token → admin key; tear down.
8. **Handoff.**

## Report format

```
## Agent initialized — <name>
SDK:         <tag> @ <sha7>
Sources:     <n> stub(s): <names>
Contrib:     <none | list>  (EXPERIMENTAL)
MASTER_KEY:  generated → .env (not shown)
AGENT_PORT:  <port> → .env
Tests:       <pass/fail>
Dev boot:    <ok @ :<port> | skipped (--no-run)>
Manifest:    .claude/.harness-manifest.json ✓

## Development lifecycle

  1. /analyze      — create a PRD: what tools does this agent need?
                     what upstream sources? what domain invariants?
  2. /todos        — break the PRD into vertical-slice waves
                     (workspace/todos/plan.md + w001-*.md)
  3. /wave w001    — implement → unit redteam → phase redteam →
     /wave w002      protocol audit → codify → archive
     ...             zero-tolerance: no finding survives a wave
  4. /agent-verify — full A2A + MCP + OAuth-chain conformance check

  Day-2 operations:
     /add-source   — add a new upstream API adapter
     /add-tool     — add a new tool to an existing source
     /redteam      — adversarial review at any point (SI-1…SI-7)
     /debug        — root-cause a stall or unexpected failure
     /diagnose     — classify a runtime failure to its exact layer
     /provision    — re-seed credentials or walk a new environment
     /upgrade      — bump the SDK pin + sync harness files
     /sdk-issue    — report a bug in the SDK itself (not agent code)
```

## Rules

- **Never invent or display a key.** `MASTER_KEY`, bootstrap tokens, and minted
  API keys are CSPRNG-generated and only ever land in `.env` or the console.
- **No commit is made.** The user reviews, then commits when ready.
- **`.env` preservation on re-run.** Only update the `MASTER_KEY=` line; never
  overwrite the entire `.env` file on a re-run. User-set values must be preserved.
- **HTTPS fallback.** If SSH fails, offer the HTTPS alternative before stopping.
- **Secrets hygiene (SI-2).** No credential value, token, or MASTER_KEY ever
  appears in a log line, error message, or chat output. The bootstrap temp log is
  deleted immediately after token capture.
- **`git ls-remote` vs pip VCS URLs.** `git ls-remote` takes `ssh://` or `https://`
  URLs. The `git+ssh://` prefix is pip-only. Never pass `git+ssh://` to `git
  ls-remote`.
