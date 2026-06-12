# Writing tools

A tool is an async function on a `ToolSet`, declared with `@tools.tool`:

```python
from agent_sdk import ToolSet
from agent_sdk.models.content_types import TimeSeriesChart

tools = ToolSet()

@tools.tool(
    tier=1,                      # 1 = query (A2A + MCP), 2 = composite (A2A only)
    emits=TimeSeriesChart,       # structured artifact type (optional)
    sample={"symbol": "AAPL"},   # console "Try" sample (optional)
)
async def get_price_history(inp: PriceHistoryInput, *, api: EodhdAdapter) -> TimeSeriesChart:
    """Fetch OHLCV history for a symbol."""   # docstring = tool description
    ...
```

Rules the decorator enforces:

- The function must be `async`.
- At most **one positional parameter** typed as a pydantic `BaseModel` —
  that is the input model; its JSON schema is what the model and MCP
  clients see. A no-input tool simply omits it.
- Adapters are **keyword-only parameters** annotated with the adapter
  class. Injection is exact-class match, resolved at `build_app()` against
  `register_source(...)` registrations; a missing registration fails the
  boot. There is no `source=` kwarg — annotations are the single source of
  truth.
- Tool name = `__name__` (override with `name=`); duplicates across all
  toolsets raise at boot.

## Tiers

- **Tier 1 (query):** exposed on A2A *and* MCP `tools/list`. 130s timeout.
- **Tier 2 (composite):** A2A only — typically multi-step or interactive
  (interrupts). 180s timeout.

## `emits=` — structured artifacts

When a tool returns an instance of its `emits` type, the SDK fans it out
to every protocol from one return value:

- **A2A:** a dual-part artifact — `TextPart` plain-text fallback +
  `DataPart` carrying the A2UI message sequence (capability-gated).
- **AG-UI:** `CUSTOM` events — `AGENT_ARTIFACT` (raw data) and
  `A2UI_UPDATE` (renderable card).
- **MCP:** the tool's `outputSchema` and `structuredContent`.

`emits` must be a registered content type — a Standard Profile type or a
domain card you registered ([content-types.md](content-types.md)). Unknown
types fail `build_app()`.

## Errors

Raise `AgentError(category, message, source=...)`. It becomes a tool
*result* the model can react to — never a crash, never a leaked secret
(write generic messages; the SDK also redacts known patterns). Any other
exception is folded to an opaque `"tool '<name>' failed"`.

## Interrupts (human-in-the-loop)

```python
raise ToolInterrupt(
    reason="confirmation",                 # "auth..." → A2A auth-required state
    message="Publish this note?",
    response_schema={...},                 # JSON Schema for the client form
    resume_handler=confirmed,              # async fn(user_value) -> tool result
)
```

The task parks in `input-required`/`auth-required`; the wall-clock deadline
suspends while parked. Resume arrives via A2A `message:send` with `taskId`,
or an AG-UI run with `resume=[{interruptId, status, payload}]` — identity
bound either way. `status` may be the protocol literal (`"resolved"` /
`"cancelled"`) with the decision in `payload.decision`, or the SDK shorthand
(`"approved"` / `"rejected"`) directly in `status` (see protocols.md). Without a `resume_handler`, the raw user response is
folded back to the model as the tool result.

## Loop policies

Per task: max 20 turns, 600s deadline (interrupt-suspended), 200k token
budget *across resumes*, and a task-local result cache (an identical
`(tool, args)` call is served from cache, not re-invoked). Tune via
`BaseAgentSettings` or `LoopPolicies`.

## Skills

Markdown files under `skills_dir` with frontmatter:

```markdown
---
name: widget-briefing
description: How to produce a widget status briefing
---
...instructions...
```

The catalog (name + description) is appended to the system prompt; the
model loads full bodies on demand via the built-in `load_skill` tool. Keep
personas short; put per-job procedure in skills.
