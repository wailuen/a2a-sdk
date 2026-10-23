# Writing tools

A tool is an async function on a `ToolSet`, declared with `@tools.tool`:

```python
from agent_sdk import ToolSet
from agent_sdk.models.content_types import TimeSeriesChart

tools = ToolSet()

@tools.tool(
    tier=1,                      # 1 = query (A2A + MCP), 2 = composite (A2A only)
    tags=["prices", "equities"], # card discovery tags (no default; empty tags log a warning)
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

### Common pitfalls

- Naming the function `foo_tool` registers a tool literally named
  `foo_tool` (the `_tool` suffix is not stripped) — a frequent cause of a
  skill or persona being authored against the wrong tool name. When this
  happens without an explicit `name=` override, the SDK logs a `WARNING`
  at registration time; pass `name="foo"` to `@tools.tool(...)` to fix it.

## Unknown arguments are rejected

A call that carries a key the input model does not declare (by field name or
alias) fails with `ToolInputValidationError`, on the agent loop and on MCP
`tools/call` alike. The model sees the key's name, never its value. A tool
with no input model rejects any argument. `input_schema()` advertises
`additionalProperties: false` only when this is enforced.

To accept extra keys, set `model_config = ConfigDict(extra="allow")` on the
input model, or pass `allow_extra_args=True` to `@tools.tool(...)`. Both make
the schema advertise `additionalProperties: true`. The SDK never edits your
model class.

## "ID A or ID B" inputs

To say that a caller must give at least one of two fields, make both fields
optional and add an `anyOf` of `required` lists through `json_schema_extra`.
The keyword goes unchanged into the schema the model sees and into MCP
`tools/list` (the SDK does not strip or enforce it):

```python
class LookupInput(BaseModel):
    model_config = {
        "json_schema_extra": {"anyOf": [{"required": ["a"]}, {"required": ["b"]}]}
    }

    a: str | None = Field(default=None, description="ID A. Give A or B (at least one).")
    b: str | None = Field(default=None, description="ID B. Give A or B (at least one).")
```

Also say the rule in the field descriptions, and check it inside the tool (or
in a pydantic `model_validator`) so the model gets a clear error when it
ignores the schema.

Caution: some model APIs reject a top-level `anyOf`, `oneOf` or `allOf` in a
tool's input schema. If a model or MCP client you target does this, drop the
`json_schema_extra` and rely on the descriptions plus the validator.

`tools/list` drops pydantic's auto-generated `title` keys from tool schemas;
a field you name `title` is kept.

## MCP annotations

`readOnlyHint`/`destructiveHint` come from `read_only=`. `openWorldHint` is
derived from the function signature, not from `tier` or `read_only`: it is
`True` iff the tool has at least one `SourceAdapter`-backed keyword-only
parameter, `False` otherwise. This is a claim about the SDK's dependency-
injection contract — a tool receives external capability **only** as an
`SourceAdapter` passed by typed keyword-only parameter, never ambiently — so
a tool with no such parameter is closed-world by declared contract.

If a tool reaches an external system by any other route — a nested call into
another tool's function, a contrib source, anything not expressed as its own
`SourceAdapter` parameter — that is a contract violation to fix at the tool,
*or* pass `annotations={"openWorldHint": True}` explicitly to override the
seed (it always wins). A tier-2 composite tool with no adapter parameter and
no explicit override logs a `WARNING` at registration time for exactly this
reason.

An explicit `annotations={...}` always overrides the seeded fields,
field-by-field.

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

### One tool, several card types (tuple `emits`)

A dispatcher tool that returns different content types declares a tuple:

```python
@tools.tool(tier=1, emits=(KpiCard, TimeSeriesChart))
async def dispatch(inp: DispatchInput) -> KpiCard | TimeSeriesChart:
    ...
```

- The card is sent when the result is an instance of any member, labelled
  with that member's `data_type`. A result matching no member gets text only.
- The return annotation must be absent, `Any`, a common superclass of every
  member, or a `Union`/`|` whose non-`None` arms are exactly the members.
- No empty tuple, no duplicates, every member a registered content type
  (inside `a2ui_allowed_components`), and no `MarketBriefing`.
- MCP `outputSchema` is `{"type": "object", "anyOf": [<member schemas>],
  "$defs": {<merged>}}`. Members whose `$defs` share a name with different
  content fail at boot. Raw dict results are coerced into the first member
  that validates.
- The agent card lists `x-sdk.emits` as a list of `data_type` strings, and
  the A2UI extension advertises every member's catalog.
- A `long_running` tool that declares `emits` and resolves to a value
  matching no member gets a text-only artifact (no card).

## Who is calling

`current_identity()` returns the caller's frozen `Identity` inside a tool or a
`SourceAdapter` method, or `None` outside a request. It never carries tokens or
headers.

```python
from agent_sdk.auth import current_identity

who = current_identity()
owner = who.principal_key if who else "anonymous"
```

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

`LoopPolicies.empty_reply_retry` (default `True`): if the model answers
right after a tool result with no tool calls and only blank text, the loop
makes ONE more model call with tools off. It does not use a `max_turns`
turn, its tokens count toward the token budget, and it emits a usage event.
If that call is also blank or fails, the user sees a fixed notice and the
task still ends `ok=True`. No notice is added when a card was already
delivered this turn. No retry runs when the task is sealed, past its
deadline, or out of token budget. Set `False` for the old silent end.

## Reusable values (cross-turn references)

A tool can mark a return value as citable in later turns, instead of
relying on the model to retype it from memory (retyping is where a model
most often substitutes a different, wrong-but-plausible id):

```python
from agent_sdk import Reusable

@tools.tool(tier=1)
async def resolve_entity(inp: LookupInput) -> str:
    entity_id = await source.lookup(inp.name)
    return Reusable(value=entity_id, kind="entity_id", label=inp.name)
```

The loop unwraps `Reusable` before the model sees the result — the model
receives `.value`, exactly as if the tool had returned it directly — and
records the resolution so a later tool call can reference it by token
instead of retyping it: the literal `$ref:<kind>`, or `$ref:<kind>:<label>`
to disambiguate multiple resolutions of the same kind.

An input field opts in to the substitution/validation contract via
`Annotated[<type>, ReuseKind("<kind>")]` on the tool's `input_model`:

```python
from typing import Annotated
from agent_sdk import ReuseKind

class TransferInput(BaseModel):
    entity_id: Annotated[str, ReuseKind("entity_id")]
```

Before invoking such a tool, the loop:

- substitutes a `$ref:<kind>`/`$ref:<kind>:<label>` token with the
  matching resolved value;
- rejects the call with a generic tool error when a raw value is supplied
  that does NOT match any prior resolution of that kind, and at least one
  resolution of that kind exists — this is the check that catches the
  model substituting a wrong id instead of the one it actually resolved;
- rejects the call as ambiguous — a bare `$ref:<kind>`, or ANY raw value
  including one that happens to equal a resolved value — once MORE than
  one resolution of that kind is on record: membership in the union of
  resolved values is not proof a value is the one meant for THIS call.
  The rejection names the kind's own on-record **labels** (display names,
  never a resolved value) so `$ref:<kind>:<label>` — the disambiguation
  move it recommends — is actually constructible from the rejection text
  alone, on every transport;
- passes a raw value through unchanged when no resolution of that kind
  exists yet, or the raw value matches one that does.

**`strict` and `allow_raw_override`** — `ReuseKind(kind, strict=True,
allow_raw_override=False)`:

- `strict=False` turns off the mismatch rejection for that field entirely
  (`$ref` still resolves; a raw value is simply never checked against
  prior resolutions). Use it on a field where the correctness risk of a
  silently-wrong substitution doesn't justify blocking every genuinely new
  value the model or user supplies directly.
- `allow_raw_override=True` lets a call pass `$raw:<value>` to bypass the
  mismatch check for that one call — the escape hatch for a genuinely new,
  legitimate value (without it, a rejected call has no way to succeed
  except retrying the resolver tool). The rejection error never mentions
  this token, by design: it exists to stop a model that hallucinated a
  wrong id, not to be discoverable by that same model. Treat it as a
  deliberate per-field operator opt-in, not a capability every `ReuseKind`
  field gets by default.

**Bounded recovery for a stuck raw value (opt-in, RT-002)** — a field left
at every default (`strict=True`, `allow_raw_override=False`) has no
in-band way out when the model keeps retrying the exact same
wrong-but-plausible raw value: without opting in, it is rejected forever,
and the model can only keep calling the resolver tool until `max_turns`.
`LoopPolicies.reuse_forced_passthrough_limit` **defaults to `0` —
reject-forever** — because this gate exists to catch GH-148's silent
wrong-id substitution, and a correctness gate must never default to
fail-open. Set it to a positive integer to opt IN to the liveness
fallback: after that many consecutive rejections of the *identical* value
on that field, the next call passes it through unchanged instead of
rejecting again, and the loop emits an
`AuditEvent(code="reuse_forced_passthrough")` so the bypass is auditable,
not silent. The budget is scoped to the exact `(tool, field, raw value)`
triple — a sequence of *different* hallucinated ids on the same field is
still rejected forever regardless of this setting; only a genuinely stuck
retry of one identical value recovers once opted in.

**Restrictions:** `ReuseKind` supports a top-level scalar field only —
`str`, `int`, or `<scalar> | None`. A container field
(`Annotated[list[str], ReuseKind(...)]`) or `ReuseKind` on a field of a
nested model raises `TypeError` at `@tools.tool` registration time rather
than shipping a silent no-op.

On a **non-string** scalar (`int`, `float`, `bool`, or those `| None`) the
tool schema the loop advertises to the model widens that property to
`{"anyOf": [<your type>, {"type": "string", ...}]}`, because `$ref:<kind>`
is itself a string token and a provider that constrains tool arguments to
the declared schema (Bedrock Converse among them) would otherwise never
let the model emit it. Your `input_model` is untouched: the token is
replaced with the resolved value of the real type before the tool's own
validation runs, so the tool body still receives an `int` where it
declared one. Every other surface (MCP `tools/list`, the agent card, the
admin console) advertises your schema unwidened.

**Transport carriage:** the mechanism rides the conversation's `messages`
transcript, and cross-turn reuse works on **both A2A and AG-UI**, by two
different routes. A2A's `record.messages` is seeded directly from
`TaskStore.context_messages(context_id)` — the prior task's Converse-format
messages, replayed verbatim — so a `__resolved__` marker folded in turn N
is still part of the model-visible transcript in turn N+1. AG-UI's
`_fold_history` (`agent_sdk/routes/ag_ui.py`) collapses a resent tool-result
block down to plain text, so it can't carry a marker back into `messages`
the same way; instead the route calls
`TaskStore.context_reusable_messages(thread_id, identity)` (`thread_id` and
`context_id` are the same value for an AG-UI task) and passes the result
into `run_task_worker`/`run_loop` as `extra_resolved_messages` — scanned
only to seed the resolved-value index, never appended to `messages` and
never shown to the model, so AG-UI's smaller, text-only transcript is
unchanged. A resolve-then-reference sequence always worked within a single
run/request (the loop's turns inside one request); both transports now also
carry the resolution to the next request on the same context/thread.

**Why `context_reusable_messages()`, not `context_messages()`, on AG-UI
(RT-001):** each new AG-UI `TaskRecord.messages` starts fresh from that
run's own folded text only — it never inherits the prior task's `messages`
the way A2A's does. Seeding from `context_messages()` (the single most
recent terminal task) would decay after exactly one intervening, unrelated
run: as soon as a run with no marker of its own becomes the newest terminal
task, the next run's seed goes empty and `$ref:<kind>` stops resolving —
silently reopening the wrong-but-real-id substitution GH-148 exists to
catch. `context_reusable_messages()` scans EVERY terminal task in the
thread instead, so a marker survives for the life of the conversation.
RT-010: that scan is bounded — only the newest `MAX_REUSABLE_TASKS`
terminal tasks are scanned per call, and each contributes only its
`__resolved__` marker content, never its full messages, since `scan_resolved`
(the sole reader of the result) never looks at anything else.

**Admin privilege must not leak another identity's resolved values into a
caller's tool arguments — on EITHER transport (RT-004, extending RT-009):**
neither `context_reusable_messages()` nor `context_messages()` honours an
admin api_key identity's cross-identity override — both apply the identity
filter even to an admin caller, so neither transport's carrier ever
contains another identity's marker or transcript. `context_messages()`
previously special-cased admin api_key identities (framed as "operator task
inspection") to return a foreign identity's transcript into the admin's own
new task; that bypass fed straight into the model's context on the exact
same request path a same-identity caller uses to continue their own
thread, not a read-only view, so it was the same covert side channel this
paragraph already closed for AG-UI's carrier — it is now removed rather
than mitigated. A same-identity result (including an admin's own prior
task) is unaffected. Genuine operator inspection of another identity's
task remains available, safely, as a read that never seeds a new task's
model context: `GET /v1/tasks/{id}`.

**`TaskStore.context_messages()`/`context_reusable_messages()` caveat:**
these calls are the sole carriers of a prior task's `__resolved__` markers
across a request boundary on A2A and AG-UI respectively. Neither is
abstract on the base `TaskStore` (`agent_sdk/tasks/store.py`) — both return
`[]` by default — so an external durable `TaskStore` that does not override
the one its transport(s) use will not error or warn: it silently starts
every continued A2A task, and every continued AG-UI thread, with an empty
resolved-value index. The mismatch check then silently stops applying: a
raw value passes through unvalidated, while an explicit `$ref:<kind>` token
still fails loudly, since the empty index has no entry to resolve it
against. A single task/run with no continuation is unaffected, since
`run_loop` reads and writes the same in-memory `messages` list (or
`resolved_index`) throughout that one request.

MCP `tools/call`, the admin try-tool endpoint, and the commitments
executor have no conversation transcript to resolve a token against, so
`invoke_any` (the shared dispatch helper behind all three) rejects a
`$ref:`/`$raw:` token on a `ReuseKind` field outright with a generic tool
error — it does NOT hand the literal string to the tool body. Callers on
those three surfaces must supply a raw value. (The agent card's
`x-sdk.inputSchema` is advisory metadata only, not a dispatch path — it
never sees a token to act on either way.)

`Reusable`, `ReuseKind`, and `DeferredResult` are all top-level `agent_sdk`
exports — import them as
`from agent_sdk import Reusable, ReuseKind, DeferredResult`
(`tests/test_public_api_exports.py` pins this; DESIGN.md §4.0 lists all
three as stable-core, strict-SemVer). Their submodule paths,
`agent_sdk.agent.reuse` and `agent_sdk.agent.deferred`, remain valid too.

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
