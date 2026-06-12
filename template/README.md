# {{AGENT_NAME}}

An A2A / AG-UI / MCP agent built on `agent-sdk`.

> **Using this template?** Two paths — both substitute all placeholders and
> generate a strong `MASTER_KEY`:
>
> **Path A — self-contained (no SDK repo needed):**
> Clone this repo, open in Claude Code, run `/setup`.
> It interviews you, resolves the SDK SHA via `git ls-remote`, substitutes
> all `{{placeholders}}`, writes `MASTER_KEY` to `.env`, and walks first run.
> Then: `/analyze` → `/todos` → `/wave`.
>
> **Path B — SDK context:**
> Run `/new-agent <name> --from-github` (or `/new-agent <name>`) from the
> `a2a-sdk` harness. The SDK repo must be a local sibling.
>
> Template placeholders: `{{AGENT_NAME}}` (kebab-case), `{{AGENT_MODULE}}`
> (snake_case), `{{SDK_GIT_URL}}`, `{{SDK_SHA}}`, `{{SDK_TAG}}`.
> Never substitute these by hand.

## Run locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # /new-agent already generated MASTER_KEY
uvicorn src.main:app --port 8000
```

Console: `http://localhost:8000/admin` — first run prints a single-use
bootstrap token to stdout; paste it into the console to mint the first
admin API key.

## Build the image

The Dockerfile installs `agent-sdk` from a private git repo over SSH using
BuildKit secrets — the key never lands in a layer:

```bash
docker build --ssh default -t {{AGENT_NAME}} .
```

CI runners: load a deploy key into an ssh-agent first
(`eval $(ssh-agent); ssh-add deploy_key`), then pass `--ssh default`.
GitHub's host keys are baked into the image from GitHub's published
fingerprints — the build never runs `ssh-keyscan` (TOFU).

## Deployment invariants

- **Exactly one process.** The task store, SSE queues and rate limiter are
  process-local; the Dockerfile hard-codes `--workers 1` and the SDK
  refuses `WEB_CONCURRENCY > 1`.
- **One origin per agent.** Well-known URIs (agent card, OAuth metadata)
  are origin-rooted; path-prefix deployments need the reverse-proxy
  rewrite rules documented in the SDK's `docs/deployment.md`.
- `PUBLIC_URL` is required outside `DEV_MODE` and drives every advertised
  URL.
