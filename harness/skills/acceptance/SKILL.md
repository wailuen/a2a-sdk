---
name: acceptance
category: quality
description: "Autonomous acceptance gate: generate 30+ scenario seed files, drive live multi-turn AG-UI conversations against a provisioned agent, judge-score each turn 1–10 for content coherency, self-heal failures (classify → fix → restart → re-test), and reach 100% pass before returning. Optional --ux path runs the same scenarios sequentially through the admin test console via Playwright, adding a rendering fidelity score per A2UI component type. Requires /provision to have run (reads admin key from workspace/adr/ADR-000-<env>-credentials.md). Never exits with open failures."
---

# /acceptance — Autonomous acceptance gate

Drives the agent to 100% domain correctness after `/agent-verify` confirms
protocol conformance. This skill is **self-completing**: it classifies and
fixes every failure autonomously, restarting the server as needed, and does
not return until all scenarios pass or the round budget is exhausted.

## Usage

```
/acceptance [--env dev|prod] [--url <base-url>] [--ux] [--scenario <id>]
            [--rerun-failing] [--regenerate]
```

- `--env` — which ADR-000 to read for the admin key (`dev` default)
- `--url` — override the endpoint (default: `endpoint` from ADR-000)
- `--ux` — run UX path via Playwright (sequential, adds rendering fidelity score)
- `--scenario acceptance-NNN` — run one specific scenario only
- `--rerun-failing` — re-run scenarios that failed in `latest.json`
- `--regenerate` — rebuild all seed files (preserves hand-annotated fields:
  `expected_tools`, `expected_content_types`, `max_turns`)

## Lifecycle position

```
/wave         → build + zero-tolerance redteam + protocol conformance
/agent-verify → A2A/AG-UI/A2UI/MCP conformance + OAuth chain
/provision    → boot real server, seed credentials, write ADR-000   ← prerequisite
/acceptance   → domain correctness: 30+ scenarios, self-healing to 100%
/acceptance --ux → same + rendering fidelity through the rendered UI
```

---

## Phase 0 — Pre-flight

1. **Read ADR-000.** Open `workspace/adr/ADR-000-<env>-credentials.md`.
   Parse the YAML frontmatter: extract `endpoint` (use as base URL unless
   `--url` was passed) and `admin_key`. If the file does not exist, stop:
   "Run `/provision` first — ADR-000-<env>-credentials.md not found."

2. **Confirm server is alive.**
   ```bash
   curl -sf <base_url>/health
   ```
   If this fails, stop: "Agent not running at <base_url>. Start it with
   `DEV_MODE=true .venv/bin/uvicorn src.main:app --port <port> --workers 1`
   then re-run `/acceptance`."

3. **Read agent context.** Read `src/persona.py` (or equivalent) for the
   agent name and description. Read all `@tools.tool` decorated functions in
   `src/tools/` — capture name, `emits=` type, and docstring for each.
   This becomes `agentContext` passed to the workflow.

4. **Determine scenario target:**
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

## Phase 2A — API path (default, parallel)

1. **Read all target seed files** into a `scenarios` array: parse each file's
   YAML frontmatter into `{id, name, category, seedQuery, expectedTools,
   expectedContentTypes, maxTurns}`.

2. **Determine run ID.** List `workspace/scenarios/results/run-*.json`. Next
   run ID is the highest number + 1 (zero-padded to 3 digits: `run-001`).
   Create `workspace/scenarios/results/` if it does not exist.

3. **Invoke the acceptance-api workflow:**
   ```
   Workflow({
     name: 'acceptance-api',
     args: {
       scenarios: <parsed scenarios array>,
       baseUrl: <base_url>,
       adminKey: <admin_key>,
       agentContext: {name, description, tools: [{name, emits, description}]},
       onlyIds: <empty [] for full run, or list of IDs for --rerun-failing>
     }
   })
   ```

4. **Stream results** as each scenario completes (the workflow fan-out is
   parallel; log each result as soon as its agent returns):
   ```
   acceptance-001 [happy-path]  PASS  min=9  turns=3
   acceptance-002 [edge-case]   FAIL  min=4  turns=3  class=code-bug
   ...
   ```

5. **Write run results** to `workspace/scenarios/results/run-<NNN>.json`:
   ```json
   {
     "runId": "run-001",
     "env": "dev",
     "baseUrl": "http://localhost:8000",
     "scenarios": [ <all SCENARIO_RESULT objects> ]
   }
   ```
   Also write/overwrite `workspace/scenarios/results/latest.json` with the
   same content. Update per-scenario score history in latest.json:
   for each scenario, append `{runId, minScore, passed}` to a `history` array.

6. **If all pass → done.** Print final report and exit.

7. **If any fail → fix loop** (Phase 3).

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

**`code-bug`** — wrong tool logic, wrong output format, tool errored:
- Spawn an implementer agent for each affected file. Brief: failing scenario +
  turn + judge rationale + actual reply vs expected tool/type.
- Agent fixes the code. Runs `pytest -q tests/` after.
- Server restart required before re-test.

**`content-type-gap`** — agent did not emit the expected A2UI content type:
- Check `src/content.py` (or equivalent). Is the type registered?
  Is `emits=` set on the tool?
- Spawn implementer to add/fix `emits=` annotation and/or type registration.
- Server restart required.

**`persona-gap`** — agent lacks the capability entirely:
- This cannot be fixed within the acceptance loop. Log: "Scenario <id> requires
  a capability not in the current wave. File as a gap via `/analyze update prd`."
- Mark this scenario ESCALATED and exclude it from further rounds.
  (A persona-gap does NOT block other scenarios from reaching 100%.)

**`upstream-issue`** — source adapter / credential failure:
- Spawn a diagnose agent: read the source adapter + check credentials via
  `POST /admin/sources/<name>/health`. Report the error category.
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

Admin key from ADR-000 remains valid across restarts (it's stored in the
credential store, not in memory).

### Phase 3b — Escalation (round 5 exhausted)

If 5 rounds complete and scenarios still fail:
```
ACCEPTANCE INCOMPLETE — round budget exhausted.

Remaining failures:
  <scenario-id>  class=<class>  min=<score>  <rationale>
  ...

Recommended actions:
  persona-gap     → /analyze update prd → add FR → /wave → /acceptance
  code-bug        → /debug <scenario-id> rationale  → fix → /acceptance
  upstream-issue  → /diagnose source <name>
  bad-scenario    → /acceptance --scenario <id> --regenerate
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
| `deleteSurface` lifecycle | After the 4-message sequence completes, the card DOM element is gone |
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
    {"runId": "run-001", "minScore": 4, "passed": false},
    {"runId": "run-002", "minScore": 9, "passed": true}
  ]
}
```

---

## Final report format

```
## Acceptance — <agent-name>   Run: <run-id>   Env: <env>   Path: API|UX

Scenarios:   <N> total  |  <P> passed  |  <F> failed  |  <E> escalated
Min score:   <n>/10  (threshold: 7)
Rounds used: <R>/5

Results:
  acceptance-001  [happy-path]       PASS  turns=3  min=9
  acceptance-002  [edge-case]        PASS  turns=4  min=8
  acceptance-003  [content-type]     PASS  turns=3  min=9    fidelity=9  (UX only)
  acceptance-004  [interrupt-resume] FAIL  turns=3  min=4  class=code-bug
  ...

OVERALL:  PASS (all scenarios ≥ 7) | INCOMPLETE (escalated) | FAIL (open failures)

Next:  /acceptance --ux (if API path just passed)
       /wave → /acceptance (if persona-gap scenarios were escalated)
```

---

## Rules

- **Never exit with open failures.** The fix loop runs until all scenarios pass
  or 5 rounds are exhausted. Partial success is not a success.
- **No secrets in output.** The admin key is read from ADR-000 but never
  printed to the terminal.
- **Persona-gap escalations do not block.** If a scenario is escalated as
  `persona-gap`, the rest continue toward 100%.
- **Server restart is safe.** The credential store persists; the admin key in
  ADR-000 remains valid. Only restart when code has changed.
- **UX path is additive.** Run the API path first; run `--ux` only after the
  API path is 100%. Both must pass before the agent is considered accepted.
