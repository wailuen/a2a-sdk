---
name: new-agent
description: "Scaffold a new agent-sdk agent from the template. Interviews for name/domain/sources/auth/contrib, preflights git access to the SDK repo, renders the template with all placeholders substituted, generates a strong MASTER_KEY into .env (never invented by hand, never echoed), seeds the new repo's .claude/ with the in-repo harness skills + sdk-advisor, then walks first run + the admin console. Use when the user wants to start a brand-new A2A/AG-UI/MCP agent on agent-sdk."
---

# /new-agent — scaffold a new agent-sdk agent

Turns an interview into a working, template-footprint agent repo: protocol
surfaces (A2A, AG-UI, A2UI, MCP, OAuth, console) are SDK behavior, so this skill
only fills in the thin domain layer and the deployment ceremony the SDK can't
generate for you (a real `MASTER_KEY`, a verified git pin, console-minted keys).

**This skill writes files and runs a local boot. It does NOT commit anything**
(the SDK standing rule: commits only when the user asks). It also never prints a
secret it generates — the `MASTER_KEY` goes into `.env` and the user is told it's
there, not shown.

## Usage

```
/new-agent [name] [--dir <parent>] [--sdk-ref <tag-or-sha>] [--no-run]
```
- `name` — kebab-case agent name (prompted if omitted).
- `--dir` — parent directory for the new repo (default: cwd's parent of the SDK, i.e. a sibling of the SDK repo).
- `--sdk-ref` — pin the SDK at this tag/SHA (default: the current `HEAD` of the SDK repo, resolved to a tag + SHA).
- `--no-run` — scaffold only; skip the first-run/console walkthrough.

## Phase 0 — Interview (one pass, confirm before writing)

Collect, then echo back a summary for confirmation before touching disk:

1. **Name** — kebab-case (`acme-research`). Derive `{{AGENT_MODULE}}` = snake_case
   (`acme_research`); reject names that aren't valid once snake-cased.
2. **Domain / persona** — one or two sentences: what the agent does and its voice.
   Becomes `src/persona.py`'s `PERSONA`.
3. **Upstream sources** — for each external API the agent will call: a short name
   (snake_case → `source_name`), its base host(s) (→ `allowed_hosts`), and its auth
   shape (bearer token / api-key header / OAuth client-credentials / none). Each
   becomes a `SourceAdapter` via `/add-source` — scaffold one stub per source now,
   flesh out later.
4. **Client auth model** — how callers authenticate to THIS agent: API keys (admin
   console mints them) and/or the built-in OAuth 2.1 chain for MCP. Both are SDK
   behavior; the choice only affects what you demo in the walkthrough. Note for the
   user: a Claude.ai MCP connector reaches `/mcp` over the SDK's DCR-based OAuth chain
   (auto-scaffolded) — static bearer tokens / query-param credentials are not supported
   on that surface, so "API keys" governs the console/admin path, not the MCP client.
5. **Model backend** — Bedrock (v1 default) or another `ModelClient` (e.g. OpenAI,
   via the seam). Bedrock needs `BEDROCK_REGION` + `BEDROCK_MODEL_ARN`.
6. **Contrib modules** — any of `action_gate`, `obo`, `commitments`, `webhooks`.
   **Warn that contrib is EXPERIMENTAL** (DESIGN §4.0/§9): provisional, may change
   in minors, excluded from SemVer. They import from `agent_sdk.contrib.<name>` with
   no extra — **except `obo`, which needs the `[obo]` extra** (MSAL): if chosen, pin
   the SDK as `agent-sdk[obo] @ git+…` in `pyproject.toml`. Don't wire contrib by
   default; webhooks also needs a post-build `app.include_router(...)` (DESIGN §10.3),
   which `/add-source`/manual wiring handles, not this scaffold.

## Phase 1 — Preflight git access (before rendering, DESIGN §10.1)

The template installs the SDK from a **private git repo**; resolve auth now so
week one isn't auth plumbing.

1. Determine the SDK pin: `--sdk-ref`, else `git -C <sdk-repo> rev-parse HEAD` for
   the SHA and `git -C <sdk-repo> describe --tags --abbrev=0` (if any) for the tag.
   These fill `{{SDK_SHA}}` (the immutable pin) and `{{SDK_TAG}}` (comment only).
   `{{SDK_GIT_URL}}` is the **scheme-less host/path** of the SDK's `origin` (the part
   pip appends after a `git+<scheme>://` prefix) — e.g. `git@github.com/org/sdk.git`
   for SSH, or `github.com/org/sdk.git` for HTTPS. Do **not** paste a full `ssh://`/
   `https://` origin in raw: the template's dependency line already carries the
   `git+ssh://` prefix (`agent-sdk @ git+ssh://{{SDK_GIT_URL}}@{{SDK_SHA}}`), so a raw
   scheme would render `git+ssh://https://…` and break `pip install`.
2. **Verify access** to that URL with the transport the user will actually use:
   - SSH: `ssh -T git@github.com` (or the relevant host) — expect the
     authenticated greeting; a permission denial means fix keys before continuing.
   - HTTPS+token: a `git ls-remote <url>` with the token in the credential helper.
   Report the result. **Do not proceed to render if access fails** — surface the
   exact remediation (load a deploy key / configure the credential helper) instead
   of generating a repo that can't `pip install`.

## Phase 2 — Render the template

1. Copy `template/` → `<parent>/<name>/` (the ~10-file repo in DESIGN §10.2). Do
   not copy `__pycache__`, `.pytest_cache`, or any `.env` (only `.env.example`).
2. Substitute **every** placeholder across all files (they appear in `.env.example`,
   `CLAUDE.md`, `Dockerfile`, `pyproject.toml`, `README.md`, and `src/`):
   `{{AGENT_NAME}}`, `{{AGENT_MODULE}}`, `{{SDK_GIT_URL}}`, `{{SDK_SHA}}`,
   `{{SDK_TAG}}`. After substitution, grep the tree for `{{` — any survivor is a bug.
   **If the user's transport is HTTPS** (the Phase 1 HTTPS+token branch), also rewrite
   the dependency line's scheme in `pyproject.toml` from `git+ssh://` to `git+https://`
   (the template defaults to SSH, DESIGN §10.1). Sanity-check the rendered line is a
   valid pip VCS URL — exactly one scheme, the SHA after `@` — before installing.
3. Rename source stubs to match the interview: one `src/sources/<source>.py` per
   declared source (start from `sample_api.py`), and wire each into `src/main.py`'s
   `register_source(...)` + `toolsets=[...]`. Drop the sample widget tool/source if
   the user declared real ones; keep them as a worked example if they didn't.
4. Ensure `.gitignore` excludes `.env`, `/data`, `.venv`, `__pycache__` — a secret
   or the credential DB must never be committable.

## Phase 3 — Generate MASTER_KEY (never invented, never echoed)

1. Generate a strong key:
   `python -c "import secrets; print(secrets.token_urlsafe(48))"` (≥32 chars,
   CSPRNG — satisfies the SDK's strength check, DESIGN §6).
2. Copy `.env.example` → `.env` and write the key into the `MASTER_KEY=` line.
   **Write it to the file only.** Never print the key to the chat, a log, or a
   command that would land it in shell history (no `echo $KEY`). Tell the user:
   "`MASTER_KEY` generated and written to `.env` (git-ignored). Rotate later with
   `python -m agent_sdk rotate-master-key` — offline only."
3. Leave `PUBLIC_URL` empty and `DEV_MODE=false` as shipped; the walkthrough runs
   in `DEV_MODE=true` locally (which relaxes exactly the MASTER_KEY/PUBLIC_URL/
   secure-transport checks, nothing else). Production needs a real `PUBLIC_URL`.

## Phase 4 — Seed the repo's .claude/ (harness, per-repo)

Copy the in-repo harness subset from this plugin into `<name>/.claude/` so the
team can extend the agent from inside its own repo:

- `skills/add-tool/`, `skills/add-source/`, `skills/agent-verify/`  → `<name>/.claude/skills/`
- `agents/sdk-advisor.md` → `<name>/.claude/agents/sdk-advisor.md`
- `skills/scenario/`, `skills/codify/`, `skills/analyze/` → `<name>/.claude/skills/`

Do **not** copy `new-agent` (run-once, from outside). The plugin root is the
directory **two levels up** from this `SKILL.md` (i.e. `<plugin>/skills/new-agent/../..`
= `<plugin>/`; going only one level up gives `<plugin>/skills/`, not the root).
`/agent-verify` additionally relies on the globally-installed check kit
(`agent-stack-check` + the four protocol advisors); note that in the handoff if
the kit isn't present.

Also seed the workspace template: copy `harness/workspace/` → `<name>/workspace/`
(all subdirectory `README.md` files, no content files). The workspace is where all
working documentation lives — PRDs, ADRs, todos, learnings, components, and scenarios.

## Phase 5 — First run + console walkthrough (skip with `--no-run`)

1. Create the venv with a **Python ≥3.12** interpreter and install:
   `python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"`. The SDK requires
   `>=3.12`; a 3.11 venv installs the template but fails resolving the `agent-sdk` git
   dependency. If the SDK install fails on auth (not version), point back to Phase 1 —
   don't paper over it.
2. Run the template's tests (`.venv/bin/python -m pytest -q`) to confirm a green
   baseline before the user adds anything.
3. Fill in the model backend before booting: set `BEDROCK_MODEL_ARN` (+
   `BEDROCK_REGION`) in `.env`. **It's required even in `DEV_MODE`** — `build_app()`
   constructs the model client at boot and DEV_MODE doesn't relax it. (A non-Bedrock
   backend instead passes a `model_client=` to `Agent`.) Then boot locally:
   `DEV_MODE=true .venv/bin/uvicorn src.main:app --port 8000 --workers 1`
   (one worker is mandatory — task store/SSE/rate-limiter are process-local).
4. Walk the console: open `http://localhost:8000/admin`; the first run prints a
   single-use **bootstrap token to stdout** — paste it into the console to mint the
   first admin API key. Then: add each source's credentials (stored encrypted,
   never in env), and use a tool's `sample` "Try" button to confirm an artifact
   renders. The bootstrap token and minted key are secrets — refer to them by
   location, don't echo them.
5. Tear the dev server down when the walkthrough is done.

## Steps

1. Interview (Phase 0); **confirm the summary** before writing.
2. Preflight git access (Phase 1); stop with remediation if it fails.
3. Render + substitute + wire sources (Phase 2); grep for surviving `{{`.
4. Generate `MASTER_KEY` into `.env` (Phase 3) — never echoed.
5. Seed `.claude/` + `workspace/` (Phase 4).
6. First run + console walkthrough (Phase 5) unless `--no-run`.
7. Hand off: "next, `/add-source` to flesh out each upstream, `/add-tool` to add
   tools, then `/agent-verify`. Use `/scenario` to generate usage scenarios,
   `/codify` to capture learnings, and `/analyze` to document PRDs and ADRs."
   Remind: no git commit was made.

## Report format

```
## New agent scaffolded — <name>
Repo:        <parent>/<name>   (SDK pinned @ <tag> / <sha7>)
Sources:     <n> adapter stub(s): <names>
Contrib:     <none | list>  (EXPERIMENTAL)
MASTER_KEY:  generated → .env (not shown; rotate via python -m agent_sdk rotate-master-key)
Tests:       <pass/fail summary>
Dev boot:    <ok @ :8000 | skipped (--no-run)>
Seeded:      .claude/skills/{add-tool,add-source,agent-verify,scenario,codify,analyze} + agents/sdk-advisor.md
             workspace/{prd,adr,todos,learning,components,scenarios}/README.md
Next:        /add-source · /add-tool · /agent-verify · /scenario · /analyze   (no commit made)
```

## Notes

- **Never invent or display a key.** `MASTER_KEY`, bootstrap tokens, and minted API
  keys are CSPRNG-generated by the SDK/this skill and only ever land in `.env` or
  the console — referenced by location, never pasted into chat.
- **One origin per agent** is the supported topology; `PUBLIC_URL` drives every
  advertised URL. Path-prefix deployments need the reverse-proxy rewrites in
  `docs/deployment.md` — flag that only if the user asks for a sub-path.
- **No commit.** Scaffolding leaves an uncommitted repo on purpose; the user runs
  `git init`/commit when they choose.
