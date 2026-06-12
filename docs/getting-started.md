# Getting started

`agent-sdk` turns ~10 files of domain code into a full agent: A2A v0.3.0,
AG-UI, A2UI Standard Profile artifacts, an OAuth-protected MCP server, an
agent card, and an admin console — all from one `Agent` assembly.

The fastest path is the Claude Code harness: `/new-agent` interviews you,
renders `template/`, generates `MASTER_KEY`, and walks the first run. This
page is the manual equivalent.

## Install

```toml
# pyproject.toml — pin by commit SHA (tags are mutable; SHAs aren't)
dependencies = [
    "agent-sdk @ git+ssh://git@github.com/<org>/agent-sdk.git@<sha>",  # tag vX.Y.Z
]
```

## Assemble

```python
# src/main.py — the whole file
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

Everything is explicit: nothing registers via import side effects, and all
wiring mistakes (unknown adapter annotation, duplicate tool name, unknown
`emits` type, repeated `register_source`) raise at `build_app()` — never at
call time.

## Run

```bash
uvicorn src.main:app --port 8000
```

First boot with an empty key store prints a single-use bootstrap token.
Open `http://localhost:8000/admin`, paste it, mint your admin API key, and
enter the source credentials. Then:

- `POST /v1/message:send` — A2A (`Authorization: Bearer <key>`)
- `POST /ag-ui/run` — AG-UI SSE
- `/mcp` — MCP via OAuth (connect from Claude.ai) or API key
- `/.well-known/agent-card.json` — the card

## Environment

| Variable | Notes |
|---|---|
| `MASTER_KEY` | ≥32 chars, generated, encrypts the credential store |
| `PUBLIC_URL` | required outside dev; drives every advertised URL |
| `BEDROCK_REGION`, `BEDROCK_MODEL_ARN` | v1 model backend (or pass `model_client=`) |
| `DEV_MODE` | relaxes exactly: key strength, `PUBLIC_URL`, OAuth transport checks |
| `CORS_ORIGINS` | explicit list, never `*` |
| `DATA_DIR` | encrypted credential DB location |

`DEV_MODE=true` with a non-localhost `PUBLIC_URL` refuses to boot. So does
`WEB_CONCURRENCY > 1` — see [deployment](deployment.md).

## Next

- [Writing tools](tools.md) · [Source adapters](sources.md)
- [Content types & A2UI cards](content-types.md)
- [Protocol surfaces](protocols.md) · [Security model](security.md)
- [Admin console](console.md) · [Deployment](deployment.md) · [Testing](testing.md)
