# Getting started — manual path

The recommended path is the Claude Code harness — see the [README](../README.md)
for the full guided workflow (`/new-agent` → `/provision` → `/wave` → `/agent-verify`).

This page covers the **manual equivalent**: installing the SDK, assembling an agent
by hand, and running it locally without the harness.

## Install

Pin by SHA — tags are mutable, SHAs aren't:

```toml
# pyproject.toml
dependencies = [
    "agent-sdk @ git+ssh://git@github.com/wailuen/a2a-sdk.git@<sha>",  # vX.Y.Z
]
```

```bash
python3.12 -m venv .venv
VIRTUAL_ENV=.venv uv pip install -e ".[dev]"
```

If you use the `obo` contrib module (MSAL on-behalf-of), add the extra:

```toml
"agent-sdk[obo] @ git+ssh://git@github.com/wailuen/a2a-sdk.git@<sha>",
```

## Assemble

```python
# src/main.py
from pathlib import Path
from agent_sdk import Agent, CredentialField
from .config import make_settings
from .persona import PERSONA
from .sources.sample_api import SampleApiAdapter
from .tools import widgets

agent = Agent(
    settings=make_settings(),
    persona=PERSONA,
    skills_dir=Path(__file__).parent / "skills",
    toolsets=[widgets.tools],
)
agent.register_source(SampleApiAdapter, credentials=[
    CredentialField(name="api_token", label="Sample API token", secret=True),
])
app = agent.build_app()
```

Everything is explicit: nothing registers via import side effects. All wiring
mistakes (unknown adapter annotation, duplicate tool name, unknown `emits` type,
repeated `register_source`) raise at `build_app()` — never at call time.

## Environment

Copy `.env.example` → `.env` and fill in:

| Variable | Notes |
|----------|-------|
| `MASTER_KEY` | ≥32 chars, CSPRNG — generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Never invent by hand. |
| `PUBLIC_URL` | Required outside `DEV_MODE`; drives every advertised URL |
| `BEDROCK_REGION` + `BEDROCK_MODEL_ARN` | Default model backend. Required even in `DEV_MODE`. |
| `DEV_MODE` | `true` relaxes: key strength, `PUBLIC_URL`, OAuth transport checks — nothing else |
| `CORS_ORIGINS` | Explicit list, never `*` |
| `DATA_DIR` | Encrypted credential store location (default: `data/`) |

`DEV_MODE=true` with a non-localhost `PUBLIC_URL` refuses to boot, as does
`WEB_CONCURRENCY > 1` — see [deployment.md](deployment.md).

## Run

```bash
DEV_MODE=true .venv/bin/uvicorn src.main:app --port 8000 --workers 1
```

First boot with an empty key store prints a single-use bootstrap token to stdout.
Open `http://localhost:8000/admin`, paste it to mint the first admin API key, then
add each source's credentials. The bootstrap token and minted key are secrets —
never log or echo them.

Once running:

```
POST /v1/message:send           A2A  (Authorization: Bearer <key>)
POST /ag-ui/run                 AG-UI SSE
/mcp                            MCP via OAuth 2.1 (Claude.ai) or API key
GET /.well-known/agent-card.json  agent card
GET /admin                      admin + test console
GET /health                     health check
```

## Run tests

```bash
.venv/bin/pytest tests/ -q
```

Tests use `agent_sdk.testing` (`FakeModelClient`, `reply`, `tool_call`) against
an isolated `Agent` instance. Never call the live model backend in tests. See
[testing.md](testing.md) for patterns.

## Next

- [Writing tools](tools.md) — tiers, `emits`, `sample`, interrupt/resume
- [Source adapters](sources.md) — `SourceAdapter`, `CredentialField`, `allowed_hosts`
- [Content types & A2UI cards](content-types.md)
- [Protocol surfaces](protocols.md) · [Security model](security.md)
- [Admin console](console.md) · [Deployment](deployment.md) · [Testing](testing.md)
