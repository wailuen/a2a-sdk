---
name: acceptance
category: quality
description: "Autonomous acceptance gate: generate 30+ scenario seed files, drive live multi-turn conversations against a provisioned agent on BOTH A2A (POST /v1/message:stream SSE) and AG-UI (POST /ag-ui/run SSE) transports in parallel, judge-score each turn 1–10 for content coherency per transport, self-heal failures (classify → fix → restart → re-test), and reach 100% pass on both paths before returning. Optional --ux path runs the same scenarios sequentially through the admin test console via Playwright, adding a rendering fidelity score per A2UI component type. Requires /provision to have run (reads admin key from workspace/adr/ADR-000-<env>-credentials.md). Never exits with open failures."
---

# /acceptance — Autonomous acceptance gate

Drives the agent to 100% domain correctness after `/agent-verify` confirms
protocol conformance. This skill is **self-completing**: it classifies and
fixes every failure autonomously, restarting the server as needed, and does
not return until all scenarios pass or the round budget is exhausted.

## Usage

```
/acceptance [--env dev|prod] [--url <base-url>] [--ux] [--scenario <id>]
            [--rerun-failing] [--regenerate] [--transport a2a|agui|both]
```

- `--env` — which ADR-000 to read for the admin key (`dev` default)
- `--url` — override the endpoint (default: `endpoint` from ADR-000)
- `--ux` — run UX path via Playwright (sequential, adds rendering fidelity score)
- `--scenario acceptance-NNN` — run one specific scenario only
- `--rerun-failing` — re-run scenarios that failed in `latest.json`
- `--regenerate` — rebuild all seed files (preserves hand-annotated fields:
  `expected_tools`, `expected_content_types`, `max_turns`)
- `--transport a2a|agui|both` — restrict which API path(s) to test (`both` default)

## Lifecycle position

```
/wave         → build + zero-tolerance redteam + protocol conformance
/agent-verify → A2A/AG-UI/A2UI/MCP conformance + OAuth chain
/provision    → boot real server, seed credentials, write ADR-000   ← prerequisite
/acceptance   → domain correctness: 30+ scenarios × 2 transports, self-healing to 100%
/acceptance --ux → same + rendering fidelity through the rendered UI
```

---

## Phase 0 — Pre-flight

1. **Protocol conformance gate (mandatory).** Before marking acceptance passed,
   run `/agent-stack-check` at full scope (no `--only`/`--skip` flags). All
   High and Critical findings must be resolved. This gate applies even when the
   feature wave did not touch protocol surfaces — pre-existing regressions are
   caught here, not in the wave redteam. Do not proceed to Phase 1 until
   `/agent-stack-check` exits clean at High/Critical severity.

   Also run `/redteam` with **no scope argument** (full scope). A wave-scoped
   redteam (e.g., `/redteam w006`) only covers changed code — pre-existing
   protocol surface bugs on untouched routes will not be detected (LRN-002).
   Both checks must be clean before Phase 1 begins.

2. **Read ADR-000's endpoint only.** From `workspace/adr/ADR-000-<env>-credentials.md`
   take just the `endpoint` line (`grep -E '^endpoint:' <file>`; use it as base URL
   unless `--url` was passed). Never open or print the whole file — it holds
   `admin_key`, which the mint and teardown commands below load themselves. If the
   file does not exist, stop: "Run `/provision` first — ADR-000-<env>-credentials.md
   not found."

   **Mint a service key (GH-182).** The admin key is used only for this step
   and for teardown. Mint a non-admin service key and use it for every
   protocol call (A2A, AG-UI, MCP); a service key keeps working with
   `AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS=true` but cannot open `/admin`.
   Run this ONE self-contained command (GH-183/GH-184). Bash state does not
   persist between tool calls, so the command sets its own variables and loads
   `ADMIN_KEY` from the ADR-000 file itself; never paste the admin key into the
   command. Replace `<base_url>`, `<run-id>` and `<env>` first. The mint response
   is piped into the parser and never reaches the transcript. If the server is
   an SDK older than v0.15.0 it ignores `service` and mints an ordinary key; the
   parser then revokes that key and stops with "this SDK does not support service
   keys; upgrade to v0.15.0+". On success it writes the key to `SERVICE_KEY_FILE`
   (a fresh `mktemp` file, mode 600, checked before writing) and prints only the `key_id` and that file path (the path is not secret).

   ```bash
   export BASE_URL="<base_url>" KEY_LABEL="acceptance-<run-id>"
   export SERVICE_KEY_FILE="$(mktemp "${TMPDIR:-/tmp}/acc-key-XXXXXX")"
   export ADMIN_KEY="$(python3 -c 'import re,sys; m=re.search(r"^admin_key:\s*(\S+)", open(sys.argv[1]).read(), re.M); print(m.group(1) if m else "")' workspace/adr/ADR-000-<env>-credentials.md)"
   (umask 077
   printf 'Authorization: Bearer %s\n' "$ADMIN_KEY" \
     | curl -s -X POST "$BASE_URL/admin/api/keys" -H @- -H "Content-Type: application/json" \
         -d "{\"label\":\"$KEY_LABEL\",\"service\":true}" \
     | python3 -c '
   import json, os, subprocess, sys
   try:
       d = json.loads(sys.stdin.read())
   except ValueError:
       d = None
   ok = isinstance(d, dict) and d.get("service") is True and isinstance(d.get("plaintext"), str)
   if not ok:
       kid = d.get("key_id") if isinstance(d, dict) else None
       if isinstance(kid, str) and kid:
           subprocess.run(["curl", "-s", "-o", "/dev/null", "-X", "DELETE",
                           os.environ["BASE_URL"] + "/admin/api/keys/" + kid, "-H", "@-"],
                          input="Authorization: Bearer " + os.environ["ADMIN_KEY"] + "\n",
                          text=True, check=False)
       sys.exit("this SDK does not support service keys; upgrade to v0.15.0+")
   fd = os.open(os.environ["SERVICE_KEY_FILE"], os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
   st = os.fstat(fd)
   if st.st_uid != os.getuid() or (st.st_mode & 0o777) != 0o600:
       os.close(fd)
       sys.exit("service key file is not private; refusing to write")
   with os.fdopen(fd, "w") as f:
       f.write(d["plaintext"])
   print(d["key_id"], os.environ["SERVICE_KEY_FILE"])
   ')
   ```

   Keep the printed `key_id` as `<service_key_id>` and the printed path as
   `<service_key_file>`. The key itself lives only in that file; never print it. Do not pass the
   admin key to sub-agents.

3. **Confirm server is alive.**
   ```bash
   curl -sf <base_url>/health
   ```
   If this fails, stop: "Agent not running at <base_url>. Start it with
   `DEV_MODE=true .venv/bin/uvicorn src.main:app --port <port> --workers 1`
   then re-run `/acceptance`."

4. **Read agent context.** Read `src/persona.py` (or equivalent) for the
   agent name and description. Read all `@tools.tool` decorated functions in
   `src/tools/` — capture name, `emits=` type, and docstring for each.
   This becomes `agentContext` passed to the workflow.

5. **Determine scenario target:**
   - `--scenario acceptance-NNN` → run that one file only
   - `--rerun-failing` → read `workspace/scenarios/results/latest.json`,
     extract all scenario IDs where `passed == false`
   - default → all `workspace/scenarios/acceptance-*.md` files

---

## Phase 1 — Seed generation (first run or --regenerate)

If no `workspace/scenarios/acceptance-*.md` files exist (first run), OR
`--regenerate` was passed, generate the seed files now.

**On `--regenerate`:** For each existing file, read and preserve any fields
that are hand-annotated (non-empty `expected_tools`, `expected_content_types`,
or explicit `max_turns`). Rewrite the `seed_query`, `name`, `category` fields
only. Files with all fields hand-annotated are left untouched.

### Generating seeds

Generate at least 30 seed files covering these dimensions, derived from the
agent's actual tools, content types, and persona:

| Dimension | Target count | Pattern |
|---|---|---|
| Happy path per tool | 2 × N_tools | One typical call; one with different valid inputs |
| Multi-turn depth | 4–5 | Query that naturally invites 4–5 follow-ups |
| Input edge cases | 4–5 | Missing optional fields; boundary values; unusual but valid inputs |
| A2UI content type coverage | 1 per `emits=` type | Query that exercises each declared content type |
| Skill activation | 1–2 per `src/skills/*.md` | Phrase that should trigger each skill |
| Interrupt/resume | 2–3 if ActionGate present | Approve path; deny path |
| Error / degraded | 2–3 | Query likely to hit upstream error or edge in tool logic |

Write each seed file as:

```markdown
---
name: <kebab-case-name>
category: <dimension>
seed_query: "<verbatim query the way a domain professional would type it>"
expected_tools: [<tool_name>, ...]      # optional; leave [] if unsure
expected_content_types: [<TypeName>, ...] # optional; leave [] if unsure
max_turns: 5                             # optional; omit to use default (3–5)
---
```

File path: `workspace/scenarios/acceptance-NNN.md`
Start numbering from the highest existing acceptance-NNN + 1.

Update `workspace/scenarios/README.md` with one row per new file.

---

## Phase 1.5 — MCP tools gate

Runs after Phase 1 and before any model run (Phase 2A/2B). Requires
`agent-sdk >=0.18.0` (`agent_sdk.testing.mcp`). It calls every tier-1 tool
directly over MCP, so a broken tool fails here with its name instead of
showing up as a judged conversation.

**Samples.** The service key from Phase 0 cannot open `/admin` (so it cannot
read `GET /admin/api/tools`), and `tools/list` does not carry `sample=`. Take
each tier-1 tool's `sample=` from the `@tools.tool(...)` decorators already
read in Phase 0 step 4 and write them to a JSON file (not secret):
`{"tool_name": {"arg": "value"}, "other_tool": null}`. Use `null` when the
tool has no `sample=`. Never fetch samples with the admin key, never put any
key in `.env`, in argv, or in this file.

**Run** (the key is read from `<service_key_file>`; there is no key argument):

```bash
python -m agent_sdk.testing.mcp --base-url <base_url> --key-file <service_key_file> \
  --samples-file <samples.json> --expected-count <N tier-1 tools> \
  [--allow-error <tool>]... [--opt-in <tool>]... [--skills-tool]
```

It does, in order:

1. `initialize`, then `tools/list` (all pages). Fails when the tool count
   differs from the registered tier-1 count, an input field has no
   description, an `inputSchema` has `$ref` or `$defs`, or the list is over
   the size budget (default 120000 bytes, `--size-budget`).
   The built-in `load_skill` tool is not counted (matched by its fixed shape,
   so a domain tier-1 tool named `load_skill` is counted; `--skills-tool`
   excludes by name).
2. One `tools/call` per tool with its `sample=` args, only when the tool is
   read-only (`annotations.readOnlyHint == true`, i.e. `read_only=True`).
   - `sample=None`: skipped with a warning (not a failure).
   - Not read-only: skipped with a warning, even with a `sample=`, so a
     sample never sends mail or writes a record on every run. Opt-in is off
     by default; name a tool with `--opt-in <tool>` only when its sample is
     safe to run every time.
   - Interrupt (`isError: true` whose text ends with `MCP_INTERRUPT_SUFFIX`
     from `agent_sdk.routes.mcp`): reported "needs user input, skipped" as a
     warning; the gate goes on.
   - Any other `isError: true` not on the allow-list (`--allow-error <tool>`,
     use sparingly and record why): the gate stops at once. Stop acceptance
     before any model run and report the tool name and its `sample=` args.
   - A tool with an `outputSchema` whose result has no `structuredContent`
     (a void result is fine), has `structuredContent` that does not match the
     schema, or has a schema with an unresolvable `$ref`: the gate stops at
     once. Stop acceptance before any model run and report the tool name.

Output names the tool and `sample=` args only. It never prints the
Authorization header or the raw `tools/call` error body (SI-2, SI-6). Exit
code 1 means stop; copy the `FAIL:` lines into the report and fix the tool
before re-running.

---

## Phase 2A — Dual-path API (A2A + AG-UI, default)

Each scenario runs on **both** transports concurrently. A scenario passes only
when **both** paths score ≥ 7. Use `--transport a2a|agui` to restrict to one.

### Setup

1. **Read all target seed files** into a `scenarios` array: parse each file's
   YAML frontmatter into `{id, name, category, seedQuery, expectedTools,
   expectedContentTypes, maxTurns}`.

2. **Determine run ID.** List `workspace/scenarios/results/run-*.json`. Next
   run ID is the highest number + 1 (zero-padded to 3 digits: `run-001`).
   Create `workspace/scenarios/results/` if it does not exist.

### A2A transport (per scenario, parallel)

Drive each scenario via `POST /v1/message:stream` (colon, SSE) or
`POST /v1/message:send` (colon, non-streaming), authenticated with
`Authorization: Bearer <service_key>`. The body is a **flat** `MessageSendParams`
object — there is **no** JSON-RPC envelope (`jsonrpc`/`method`/`id`/`params`).
The path separator is a colon (`:stream`), not a slash; the slash form is not
a routed endpoint and returns 404/405. (See `tests/test_gh71_acceptance_api_stream.py`.)

**Turn 1 — A2A request:**
```json
POST /v1/message:stream
Authorization: Bearer <service_key>
Content-Type: application/json

{
  "message": {
    "role": "user",
    "messageId": "<uuid4-hex>",
    "parts": [{"kind": "text", "text": "<seed_query>"}]
  }
}
```
`messageId` is **required** — omitting it returns `-32602` (invalid params).
Use a fresh UUID per turn.

Parse the SSE stream line-by-line (`data:` frames). Each frame is a flat event
carrying a `kind` field (no `method`/`params` wrapper). Extract:
- Reply text: from `kind: "status-update"` events, read
  `status.message.parts[]` and collect `kind: "text"` parts' `text`.
- A2UI / content types: from `kind: "artifact-update"` events, read
  `artifact.parts[]`; for `kind: "data"` parts, the content type is
  `metadata.data_type` (or `metadata.mimeType`, or the artifact `name`).
- Task id: from the first `status-update` event's `taskId` (or the initial
  `kind: "task"` event); reuse it on later turns.
- Tool usage is **not** observable on the A2A stream (the protocol surfaces
  text/data artifacts, not tool-call events) — infer tools from the reply
  content and matched content types.

**Score A2A turn (1–10):**
- 9–10: reply is relevant, complete, A2UI types match `expected_content_types`
- 7–8: relevant and complete; minor type mismatch
- 5–6: partial answer; expected content type missing
- 3–4: off-topic; task errored but recovered
- 1–2: task status `failed`, timeout, or no useful output

**Multi-turn A2A:** For turns 2–N (up to `maxTurns`), the correct field to
include depends on the state of the prior task:

- If the prior task ended in `input-required` OR `auth-required` state (non-terminal
  interrupt states per A2A spec §interrupt, task is still live and waiting), send
  `taskId` to continue that specific task:
  ```json
  { "message": { "role": "user", "messageId": "<new-uuid4-hex>", "taskId": "<task-id>", "parts": [ ... ] } }
  ```
- Otherwise (prior task ended `completed`, `failed`, or any other terminal state),
  send `contextId` (captured from the turn-1 SSE stream) with **no `taskId`**,
  so the server creates a new task within the same conversation context instead of
  re-addressing a terminal task (which would return 400 / -32004):
  ```json
  { "message": { "role": "user", "messageId": "<new-uuid4-hex>", "contextId": "<context-id>", "parts": [ ... ] } }
  ```

**Turn helper (GH-210).** Scenario agents do not write their own scripts. Each turn runs
`ACC_QUERY=... python -m agent_sdk.testing.turns --transport a2a|agui --base-url ... --key-file <keyFile> --run-key ...`
(`agent_sdk >= 0.18.0`). The helper reads the key from the key file only, allows 3
concurrent turns across all scenarios (file locks; `--slots N` to change), and retries
HTTP 429, "too many requests" text, a failed task or an empty reply with exponential
back-off inside a 540 s budget. AG-UI messages are restored after a failed attempt and
A2A ids are saved only on success. If retries run out on rate limiting it returns
`failureClass: "rate-limited"`.

The helper captures `contextId` from `kind:"task"` and
`kind:"status-update"` SSE events on turn 1, persists it to
`/tmp/acc-{RUN_KEY}-a2a-ctx.txt`, and persists the last observed `state` to
`/tmp/acc-{RUN_KEY}-a2a-state.txt`. On turns 2+, it reads both files to
determine which field to send.

### AG-UI transport (per scenario, parallel)

Drive each scenario via `POST /ag-ui/run` SSE, authenticated with
`Authorization: Bearer <service_key>`. Start a **fresh** conversation — do not
reuse A2A task state.

**Turn 1 — AG-UI request:**
```json
POST /ag-ui/run
Authorization: Bearer <service_key>
Content-Type: application/json
Accept: text/event-stream

{
  "threadId": "<scenario-id>-<uuid4-hex>",
  "runId": "<scenario-id>-<uuid4-hex>-t1",
  "messages": [{"role": "user", "content": "<seed_query>"}]
}
```
Use a **per-invocation UUID suffix** on `threadId` (not a bare deterministic
`<scenario-id>`) so concurrent runs of the same scenario do not share thread
state and contaminate each other (LRN-040).

Parse the SSE stream: collect AG-UI events. Extract:
- Reply text: concatenate `delta`/`content` from all `TEXT_MESSAGE_CONTENT` events
- A2UI artifacts: `CUSTOM` events carrying the A2UI payload (or `tool_start`
  / `artifact` callbacks when driven via `ChatDriver.agui_turn`)
- Tool usage: `TOOL_CALL_START` events to verify `expected_tools`

**Score AG-UI turn (1–10):** same 1–10 scale as A2A transport.
Map AG-UI events to the same criteria — `RUN_ERROR` = 1–2;
partial TEXT with no artifact when one is expected = 5–6; full match = 9–10.

**Multi-turn AG-UI:** For turns 2–N, append the agent's reply to `messages`
and send a new `/ag-ui/run` request with the **same** per-invocation `threadId`
and an incremented `runId`.

### Workflow invocation

```
// Using scriptPath instead of name: Workflow({name}) drops args in Claude Code's named-workflow resolver; remove once upstream bug is fixed.
// Path note: when running from the SDK repo (the normal context for /acceptance),
// git rev-parse --show-toplevel gives the repo root regardless of CWD subdirectory.
// When running from an agent repo (seeded via /new-agent or /upgrade), this skill
// lives at .claude/skills/acceptance/SKILL.md and acceptance-api.js is seeded to
// .claude/workflows/acceptance-api.js — use that path instead:
//   scriptPath: `${require('child_process').execSync('git rev-parse --show-toplevel').toString().trim()}/.claude/workflows/acceptance-api.js`

// Secret externalisation (GH-89 / SI-2): the workflow sandbox has no CommonJS
// require(), so the key file must be written HERE (in the skill caller context)
// before Workflow() is invoked.  Pass only the file path; never pass the raw key.
const _runId  = require('crypto').randomUUID()
const _keyFile = <service_key_file>  // created by the Phase 0 mint step with { mode: 0o600 }; do not rewrite it

Workflow({
  scriptPath: `${require('child_process').execSync('git rev-parse --show-toplevel').toString().trim()}/harness/workflows/acceptance-api.js`,
  args: {
    scenarios: <parsed scenarios array>,
    baseUrl: <base_url>,
    keyFile: _keyFile,   // path to chmod-600 temp file containing the service key
    agentContext: {name, description, tools: [{name, emits, description}]},
    onlyIds: <[] for full run, or list of IDs for --rerun-failing>,
    transports: ["a2a", "agui"],  // or ["a2a"] / ["agui"] with --transport flag
    runId: _runId,
  }
})

// Do NOT unlink _keyFile here: it is the only copy of the service key and is
// reused by every Phase 3 re-run and Phase 2B. It is removed in the
// 'Service key teardown' section.
```

**Teardown:** do NOT revoke the service key here. It must stay valid for the
Phase 3 fix-loop rounds and Phase 2B, and across server restarts. Revoke it only
at the true exit points (see "Service key teardown" below).

The workflow fans out all scenarios × transports in parallel. Each scenario
agent runs both transport legs and returns a `SCENARIO_RESULT` with
`a2aMinScore`, `aguiMinScore`, `passed` (true iff both ≥ 7).

### Stream and write results

3. **Stream results** as each scenario completes:
   ```
   acceptance-001 [happy-path]  A2A=9  AGUI=9  PASS  turns=3
   acceptance-002 [edge-case]   A2A=8  AGUI=4  FAIL  turns=3  class=transport-divergence
   acceptance-003 [multi-turn]  A2A=3  AGUI=3  FAIL  turns=4  class=code-bug
   ...
   ```

4. **Write run results** to `workspace/scenarios/results/run-<NNN>.json`:
   ```json
   {
     "runId": "run-001",
     "env": "dev",
     "baseUrl": "http://localhost:8000",
     "transports": ["a2a", "agui"],
     "scenarios": [ <all SCENARIO_RESULT objects> ]
   }
   ```
   Also write/overwrite `workspace/scenarios/results/latest.json`.
   Per-scenario `history`: append `{runId, a2aMin, aguiMin, passed}`.

5. **If all pass → done.** Print final report and exit.

6. **If any fail → fix loop** (Phase 3).

---

## Phase 3 — Autonomous fix loop (max 5 rounds)

Run this loop until all scenarios pass or 5 rounds are exhausted.

### Round structure

```
Round N:
  1. Collect failing scenarios (passed == false) from the last run
  2. Group by failureClass
  3. Dispatch fix agents (parallel within class)
  4. Restart server (if code was changed)
  5. Re-run only the failing scenarios via acceptance-api workflow
  6. If all pass → done
  7. If round == 5 and still failing → escalate (Phase 3b)
```

### Fix dispatch by failure class

**`transport-divergence`** — one transport path passed but the other failed for
the same scenario. The domain logic is correct; the wire format diverges:
- If A2A passed but AG-UI failed: inspect the AG-UI `/ag-ui/run` SSE event stream.
  Common causes: missing `TEXT_MESSAGE_CONTENT` events, wrong `CUSTOM` A2UI
  payload, or `RUN_ERROR` emitted instead of graceful reply.
- If AG-UI passed but A2A failed: inspect the A2A `message:stream` SSE events.
  Common causes: `kind: "artifact-update"` MIME/`data_type` mismatch,
  `status.state: "failed"` on the task, or reply text buried in a non-text Part.
- The route code lives in the SDK (`agent_sdk/routes/`), which this repo cannot
  change. File it with `/sdk-issue`, attaching both transports' event streams.
  Mark the scenario ESCALATED and exclude it from further rounds; it does not
  block other scenarios from reaching 100%.

**`code-bug`** — wrong tool logic, wrong output format, tool errored (fails on
BOTH transports with the same root cause):
- Spawn an implementer agent for each affected file. Brief: failing scenario +
  turn + judge rationale + actual reply vs expected tool/type.
- Agent fixes the code. Runs `pytest -q tests/` after.
- Server restart required before re-test.

**`content-type-gap`** — agent did not emit the expected A2UI content type
(fails on both transports — the type is never produced):
- Check `src/content.py` (or equivalent). Is the type registered?
  Is `emits=` set on the tool?
- Spawn implementer to add/fix `emits=` annotation and/or type registration.
- Server restart required.

**`persona-gap`** — agent lacks the capability entirely:
- This cannot be fixed within the acceptance loop. Log: "Scenario <id> requires
  a capability not in the current wave. File as a gap via `/analyze update prd`."
- Mark this scenario ESCALATED and exclude it from further rounds.
  (A persona-gap does NOT block other scenarios from reaching 100%.)

**`rate-limited`** — the server throttled the turns (HTTP 429 / "too many requests")
even after helper retries:
- Infrastructure, not an agent defect. Never score these turns 1–2 and never spawn a fix.
- Re-run the scenario later with fewer slots (`--slots 1`) or fewer parallel scenarios.
  Does not count toward the 100% pass gate until re-run.

**`upstream-issue`** — source adapter / credential failure:
- Spawn a diagnose agent: read the source adapter + check health via
  `GET /admin/api/overview` (admin bearer) and read `adapters[].healthy` for
  that source. Report the error category.
- If credentials missing: prompt user to re-seed via `/provision`.
- If adapter bug: spawn implementer to fix.
- Server restart required if code was changed.

**`bad-scenario`** — seed query is malformed or unanswerable:
- Regenerate only that seed file (respecting hand-annotated fields).
- No server restart needed.

### Server restart procedure

After any code change:
```bash
# Resolve port from .env (same source as /provision used)
PORT=$(grep -E '^AGENT_PORT=' .env | cut -d= -f2)
PORT=${PORT:-8000}

# Kill the running server
lsof -i :$PORT -t | xargs kill -9 2>/dev/null

# Wait for port free
sleep 2

# Restart
tmplog=$(mktemp /tmp/acc-restart-XXXXXX.log)
DEV_MODE=true .venv/bin/uvicorn src.main:app --port $PORT --workers 1 \
  > "$tmplog" 2>&1 &

# Wait for health (base_url from ADR-000)
until curl -sf <base_url>/health > /dev/null; do sleep 1; done
rm -f "$tmplog"
```

Admin key from ADR-000 and the service key both remain valid across restarts
(they are stored in the credential store, not in memory). Do not revoke the
service key between rounds.

### Phase 3b — Escalation (round 5 exhausted)

If 5 rounds complete and scenarios still fail:
```
ACCEPTANCE INCOMPLETE — round budget exhausted.

Remaining failures:
  <scenario-id>  class=<class>  min=<score>  <rationale>
  ...

Recommended actions:
  transport-divergence → inspect failing transport route (ag_ui.py or a2a.py) → fix → /acceptance
  persona-gap          → /analyze update prd → add FR → /wave → /acceptance
  code-bug             → /debug <scenario-id> rationale  → fix → /acceptance
  upstream-issue       → /diagnose source <name>
  rate-limited         → re-run /acceptance --scenario <id> with fewer slots (no fix)
  bad-scenario         → /acceptance --scenario <id> --regenerate
```

Write the above to `workspace/scenarios/results/run-<NNN>-escalation.md`.

---

## Phase 2B — UX path (`--ux`)

Same pre-flight (Phase 0). Same seed files. All scenarios run **sequentially**
in a single Playwright session. Each turn earns two scores:

- **Content coherency (1–10)** — same criteria as API path
- **Rendering fidelity (1–10)** — did every A2UI component the agent emitted
  render correctly and behave as intended?

A scenario turn passes only if **both** scores ≥ 7.

### Setup

Open the admin test console:
```
browser_navigate: <base_url>/admin
browser_snapshot: confirm /admin loaded
```

**OBO detection:** If the agent config (read from `src/config.py`) has OBO
enabled (`contrib.obo` imported or `OBO_*` env vars present), the console
requires user login before tool calls work. In that case:

```
browser_snapshot: look for a login/authenticate button or redirect
If login UI detected:
  → Print: "OBO agent detected. Please complete login in the browser, then press Enter."
  → Wait for user to press Enter
  → browser_snapshot: confirm authenticated state (no login prompt visible)
```

Once authenticated (or if OBO not needed), the session persists for all
30 scenarios.

### Per-scenario UX execution

For each scenario (sequential — NO parallelism):

**Turn 1:** Type the seed query into the console chat input.
```
browser_type: <chat-input-selector> "<seed_query>"
browser_press_key: Enter
browser_wait_for: agent response (look for reply text or A2UI card appearing)
browser_snapshot: capture DOM state after response
```

**Score turn 1:**

*Content coherency (1–10):* Read the reply text and/or A2UI component content
from the DOM snapshot. Score using the same 1–10 criteria as the API path.

*Rendering fidelity (1–10):* For each A2UI component type that appeared in
the DOM, exercise its full intended purpose:

| Component type | Full UX test |
|---|---|
| `Text` / `Heading` / `Paragraph` | Content rendered, no truncation or overflow |
| `Image` | Loads without broken-img; alt text present |
| `Button` | `browser_click` → observe the resulting action or agent message |
| `DataTable` | Rows populated; if `sortable` prop → `browser_click` column header → confirm order changes; if `filterable` → `browser_type` filter → confirm rows narrow |
| `Form` | `browser_fill_form` with empty required fields → confirm validation error; fill valid → `browser_click` submit → confirm agent receives the payload |
| `Chart` | Renders without console error; `browser_hover` a data point → confirm tooltip appears with correct values |
| `KpiCard` | Value populated; trend indicator present and direction correct |
| `Card` / container types | Sub-components all rendered; no empty slots |
| `Timeline` | Events ordered; timestamps formatted |
| `Progress` | Value within 0–100; visual indicator matches value |
| Surface lifetime | After the 3-message open sequence completes, the card DOM element is still present (the SDK emits no `deleteSurface`; GH-214) |
| Multi-turn card updates | After turn 2+, `updateComponents` changes are reflected in the DOM |

Check browser console for JS errors: `browser_console_messages`. Any error
related to A2UI rendering lowers the rendering fidelity score.

Score rendering fidelity:
- 9–10: All components rendered; all interactions behaved correctly; no console errors
- 7–8: Rendered correctly; minor gap (e.g. tooltip slow but present)
- 5–6: Rendered but an interaction failed or a field is missing
- 3–4: Component appeared but non-functional
- 1–2: Component missing, crashed, or blocking console error

**Generate follow-up and run turns 2–5** using the same pattern: type the
query, wait for response, snapshot, score both dimensions.

**Scenario complete:** Record both score arrays. Min of the minimum content
score and minimum fidelity score determines pass (both must be ≥ 7).

### UX fix loop

Same round structure as Phase 3, with one addition:

- **Rendering fidelity failure** (min fidelity < 7 but content ≥ 7): the
  agent responded correctly but the UI didn't render it properly. This is
  an A2UI translator or SDK bug, not a domain code bug. Spawn an implementer
  agent briefed on the specific component type that failed and the console
  error (if any). After fix, restart server and re-establish Playwright session.

- **Re-establish session:** After a server restart in the UX path, navigate
  back to `/admin`. For OBO agents, check if the session is still active
  (`browser_snapshot`); if the login prompt reappears, pause for user login
  again.

---

## Results format

```
workspace/scenarios/results/
  run-001.json      ← full results for this run
  run-002.json
  latest.json       ← always a copy of the most recent run (with history)
  run-NNN-escalation.md  ← only written when round budget exhausted
```

Each scenario in `latest.json` carries a `history` array showing score
trajectory across all runs:
```json
{
  "scenarioId": "acceptance-001",
  "history": [
    {"runId": "run-001", "a2aMin": 9, "aguiMin": 4, "passed": false},
    {"runId": "run-002", "a2aMin": 9, "aguiMin": 9, "passed": true}
  ]
}
```

---

## Final report format

```
## Acceptance — <agent-name>   Run: <run-id>   Env: <env>

Scenarios:   <N> total  |  <P> passed  |  <F> failed  |  <E> escalated
Transports:  A2A + AG-UI  (both must be ≥ 7 to pass)
Min score:   A2A <n>/10  |  AG-UI <n>/10  (threshold: 7 each)
Rounds used: <R>/5

Results:
  acceptance-001  [happy-path]       A2A=9  AGUI=9  PASS  turns=3
  acceptance-002  [edge-case]        A2A=8  AGUI=8  PASS  turns=4
  acceptance-003  [content-type]     A2A=9  AGUI=9  PASS  turns=3    fidelity=9  (UX only)
  acceptance-004  [interrupt-resume] A2A=9  AGUI=4  FAIL  turns=3    class=transport-divergence
  acceptance-005  [multi-turn]       A2A=3  AGUI=3  FAIL  turns=4    class=code-bug
  ...

Transport verdicts:
  A2A path:   PASS | FAIL (<n> scenarios failed)
  AG-UI path: PASS | FAIL (<n> scenarios failed)

OVERALL:  PASS (all scenarios ≥ 7 on both transports) | INCOMPLETE (escalated) | FAIL (open failures)

Next:  /acceptance --ux (if dual-path API just passed)
       /wave → /acceptance (if persona-gap scenarios were escalated)
```

---

## Service key teardown (always, even on failure)

Revoke the service key with the admin key, then delete the key file, only at
the true exit points: after the final report, on Phase 3b escalation, and on any
abort. Load `ADMIN_KEY` in the same command as the mint (never inline it):

```bash
export BASE_URL="<base_url>" SERVICE_KEY_ID="<service_key_id>" SERVICE_KEY_FILE="<service_key_file>"
export ADMIN_KEY="$(python3 -c 'import re,sys; m=re.search(r"^admin_key:\s*(\S+)", open(sys.argv[1]).read(), re.M); print(m.group(1) if m else "")' workspace/adr/ADR-000-<env>-credentials.md)"
printf 'Authorization: Bearer %s\n' "$ADMIN_KEY" | curl -s -o /dev/null -w '%{http_code}\n' -X DELETE "$BASE_URL/admin/api/keys/$SERVICE_KEY_ID" -H @-
rm -f "$SERVICE_KEY_FILE"
```

Never revoke between fix-loop rounds or before Phase 2B.

## Rules

- **Protocol calls use the service key only.** The admin key mints and revokes
  the service key and does nothing else (GH-182).

- **Never exit with open failures.** The fix loop runs until all scenarios pass
  or 5 rounds are exhausted. Partial success is not a success.
- **No secrets in output.** The service key (minted in Phase 0) is written to
  a chmod-600 temp file (a `mktemp` path, `acc-key-XXXXXX`) by the workflow before
  sub-agents are spawned. Sub-agents receive the path to that file, not the key
  value itself. The key is therefore absent from the prompt strings that appear
  in harness transcripts. Never print or log the resolved key value to the
  terminal or to any workspace file. Never share harness transcript output
  externally — the resolved token is not embedded in prompts but the temp-file
  path is, which still constitutes an indirect reference.
- **Persona-gap escalations do not block.** If a scenario is escalated as
  `persona-gap`, the rest continue toward 100%.
- **Server restart is safe.** The credential store persists; the admin key in
  ADR-000 remains valid. Only restart when code has changed.
- **UX path is additive.** Run the API path first; run `--ux` only after the
  API path is 100%. Both must pass before the agent is considered accepted.
