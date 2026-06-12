# agent-sdk

Build production-grade A2A / AG-UI / A2UI agents with an OAuth-protected MCP
surface by writing **only domain code**: tools, source adapters, SKILL.md
files, a persona, and config (~10 files).

```python
from agent_sdk import Agent, ToolSet

tools = ToolSet()

@tools.tool(tier=1, emits=TimeSeriesChart)
async def get_price_history(inp: PriceHistoryInput, *, adapter: EodhdAdapter) -> TimeSeriesChart:
    """Fetch OHLCV history for a symbol."""
    ...

agent = Agent(settings=make_settings(), persona=PERSONA, toolsets=[tools])
app = agent.build_app()
```

What the SDK owns:

- **A2A v0.3.0** (HTTP+JSON + SSE): tasks, streaming, interrupt/resume,
  identity-bound task access, the full error table.
- **AG-UI**: `POST /ag-ui/run` SSE with the frozen CUSTOM event contracts.
- **A2UI v0.9.1**: the frozen Standard Profile v1 content types, translated
  to self-cleaning surfaces over both A2A DataParts and AG-UI CUSTOM events.
- **MCP 2025-06-18 + OAuth 2.1**: Streamable HTTP, PKCE, DCR, token
  rotation, two-value audience enforcement, exact CORS.
- **Agentic loop**: Bedrock Converse, tool tiers, deadlines, token budgets,
  interrupts, skills.
- **Operations**: encrypted credential store, API keys with first-run
  bootstrap, rate limiting, admin/test console, self-checks.

## Documentation

- [Getting started](docs/getting-started.md)
- [Writing tools](docs/tools.md) · [Source adapters](docs/sources.md)
- [Content types & A2UI cards](docs/content-types.md)
- [Protocol surfaces](docs/protocols.md) · [Security model](docs/security.md)
- [Admin console](docs/console.md) · [Deployment](docs/deployment.md) · [Testing](docs/testing.md)
- `DESIGN.md` — full architecture · `CHANGELOG.md` — releases
- `template/` — the ~10-file agent repo the `/new-agent` harness renders

Deployment invariant: **one process, one origin per agent** (see DESIGN.md §2).

## Repo development

```bash
uv venv && uv pip install -p .venv/bin/python -e ".[dev]"
.venv/bin/python -m pytest tests/ -q
.venv/bin/uvicorn agent_sdk.example.main:app --port 8000   # echo-analyst example
```
