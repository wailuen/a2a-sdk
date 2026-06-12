# {{AGENT_NAME}}

An A2A / AG-UI / MCP agent built on `agent-sdk`.

> Template placeholders: `{{AGENT_NAME}}` (kebab-case agent name),
> `{{AGENT_MODULE}}` (python-safe snake_case), `{{SDK_GIT_URL}}`,
> `{{SDK_SHA}}` (commit SHA), `{{SDK_TAG}}` (tag, comment only).
> The `/new-agent` harness skill substitutes all of them and generates
> `MASTER_KEY` into `.env` — humans never invent keys.

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
