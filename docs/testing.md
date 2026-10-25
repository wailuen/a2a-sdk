# Testing agents

`agent_sdk.testing` ships two surfaces: a scriptable fake model for unit/integration
tests and a live chat driver for manual + CI integration testing.

---

## FakeModelClient

```python
from agent_sdk.testing import FakeModelClient, reply, tool_call

fake = FakeModelClient()
fake.script(
    tool_call("widget_kpis", {"widget_id": "w-1"}),   # turn 1: call a tool
    reply("Widget w-1 is active."),                   # turn 2: final text
)
```

Each scripted entry is one model turn; the loop consumes them in order.
`fake.calls` records every `converse` invocation (system, messages,
tools) for assertions. Exhausting the script raises — a test that loops
more turns than scripted fails loudly.

## The fixture pattern

Build an **isolated Agent per test** (ToolSets are stateless and
reusable), inject the fake model, run the app lifespan, and mint an admin
key directly on the store:

```python
@pytest.fixture
def app(settings, fake_model):
    agent = Agent(settings=settings, persona=PERSONA,
                  toolsets=[widgets.tools], model_client=fake_model)
    agent.register_source(SampleApiAdapter, credentials=[...])
    return agent.build_app()

@pytest.fixture
async def client(app):
    async with app.router.lifespan_context(app):
        _, token = app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            yield c
```

Settings for tests: `Settings(DEV_MODE=True, DATA_DIR=str(tmp_path))` —
dev mode supplies a master key and skips `PUBLIC_URL`.

## Stubbing upstreams

Monkeypatch adapter *methods*, not HTTP:

```python
monkeypatch.setattr(SampleApiAdapter, "get_widget", fake_get_widget)
```

This keeps allowed-hosts/credential code out of the test path while the
real adapter still gets constructed through the lifespan (so registration
and injection stay covered). Test adapter HTTP behavior separately if you
add custom request logic.

## What to assert

- A2A: `POST /v1/message:send`, poll `GET /v1/tasks/{id}` to a terminal
  state, assert `artifacts[].metadata.data_type` and part kinds.
- AG-UI: `POST /ag-ui/run`, parse SSE frames, assert the event order and
  your CUSTOM payloads.
- Interrupts: script only the interrupting tool call, assert the
  `input-required` state / interrupt outcome, then resume and assert
  completion.

- MCP: `agent_sdk.testing.mcp.McpTestClient` (alias of `McpClient`) takes a
  base URL, a key file and an ASGI transport. It offers `initialize()`,
  paginated `list_tools()`, `call_tool()`, and for `Agent(mcp_skills="prompts")`
  paginated `list_prompts()` and `get_prompt(name)`. Errors raise `McpError`.

  `McpClient` offers the newest protocol version in `initialize` and sends the
  negotiated one as `MCP-Protocol-Version` on every later request.
  `run_gate(client, samples, expected_count=N)` (CLI: `--expected-count N`)
  checks the `tools/list` count against your tier-1 tool count. The built-in
  `load_skill` tool (`mcp_skills="tool"`) is not counted. It is matched by its
  fixed shape, so your own tier-1 tool named `load_skill` is counted. Pass
  `skills_tool=True` (CLI: `--skills-tool`) to exclude by name instead. For
  each tool with an `outputSchema`, the gate also checks that the call returns
  `structuredContent` that matches the schema; an `outputSchema` with an
  unresolvable `$ref` is a gate failure. `initialize` raises `McpError` when the
  server negotiates a version the SDK does not support.

`ChatDriver` and `agent_sdk.testing.turns` send the A2UI extension header and
capabilities only when the agent card advertises the A2UI extension, and
`turns` adds the card's `supportedCatalogIds` to the declared catalogs. A
resume sends both `taskId` and `contextId`. Non-goal: A2A `additionalInterfaces`
and the card `url` are not followed; these clients drive the SDK's own app on
the client you give them.

See the SDK's own `tests/` and the template's `tests/` for working
examples of all three.

---

## test-chat CLI — live agentic turns

`python -m agent_sdk test-chat` boots the agent in-process and drives a
real agentic turn over AG-UI (default) or A2A.  It prints the query, all
tool calls with arguments, any A2UI surface sequences, and the final reply
as plain text.  No browser required.

### Quick start

```bash
# from your agent project root (where .env lives):

# AG-UI (streaming) — single-shot:
python -m agent_sdk test-chat --app src.main:app "What is the climate risk for NYC in 2050?"

# A2A (poll to completion):
python -m agent_sdk test-chat --app src.main:app --a2a "What is the climate risk for NYC in 2050?"

# interactive REPL (multi-turn, omit the query):
python -m agent_sdk test-chat --app src.main:app

# domain catalog for A2UI:
python -m agent_sdk test-chat --app src.main:app \
  --catalog urn:acme:domain:v1 \
  "Summarise the portfolio risk."

# against a running agent (no in-process boot):
python -m agent_sdk test-chat --url http://localhost:8045 \
  --token ak_xxx_… \
  "Show me the risk dashboard."
```

### Output format

```
YOU  › What is the climate risk for NYC in 2050 under SSP585?
AGENT ›
  [tool] alphageo_get_climate_profile(scenario='SSP585', period='2050', address='Manhattan…') ✓
  [artifact] climate_risk_report
  [A2UI:surface] component='ClimateRiskReport'  catalog=urn:alphageo:climate:v1  lifecycle=[…]
For Manhattan in 2050 under SSP585, the top climate risk is hurricane wind…
```

- **AG-UI**: text streams character-by-character; tool calls and A2UI surfaces appear inline.
- **A2A**: poll dots appear while the task runs; A2UI surfaces and the reply print on completion.

### A2UI capability declaration

The command always declares `{tier: "core+extended", catalogs: [standard-profile-catalog]}`
so Standard Profile components surface without extra flags.  For domain-catalog types (e.g.
`ClimateRiskReport`), add `--catalog <catalog_id>` — the client claim gates the A2UI
translator: omit it and you get the `TextPart` fallback instead.

### Using ChatDriver in integration tests

```python
from agent_sdk.testing import ChatDriver

async def test_full_turn(client):
    """client is an httpx.AsyncClient with a bearer token."""
    driver = ChatDriver(client, extra_catalogs=["urn:acme:v1"])
    messages: list = []
    thread_id = uuid.uuid4().hex

    text = await driver.agui_turn(
        "Summarise Q1 performance.",
        thread_id, messages,
        emit={"text": lambda d: None},  # suppress streaming during test
    )
    assert "Q1" in text

    # Resume an AG-UI interrupt (no user message is added). The tool's
    # resume_handler decides what the payload means; the example agent's
    # publish_note approves when payload.decision is "approved".
    seen: list = []
    await driver.agui_turn("Publish it.", thread_id, messages, emit={"interrupt": seen.append})
    text = await driver.agui_resume(
        seen[0]["id"], thread_id, messages, payload={"decision": "approved"},
    )

    # History rules: agui_turn appends the user message on any RUN_FINISHED and
    # the assistant message only when the reply is non-empty; nothing on
    # RUN_ERROR or a stream with no terminal event. agui_resume appends only a
    # non-empty assistant reply. Reply text from messages with an explicit
    # non-assistant role (for example "developer") is left out.

    # A2A variant
    task = await driver.a2a_turn("Show me the risk scores.", context_id=None)
    assert task["status"]["state"] == "completed"
    reply = ChatDriver.extract_reply(task)
    a2ui_seqs = ChatDriver.extract_a2ui(task)
    assert len(a2ui_seqs) >= 1
    verbs = [next(k for k in m if k != "version") for m in a2ui_seqs[0]]
    assert verbs == ["createSurface", "updateComponents", "updateDataModel"]
```
