---
name: scenario
category: project
description: "Generate real-life, job-to-be-done usage scenarios for an agent-sdk agent from the perspective of a domain professional. Multi-turn by design: each scenario includes an initial query and a reactive follow-up grounded in what the agent actually returns. Writes structured scenario docs to workspace/scenarios/. Uses Opus."
---

# /scenario — Generate agent usage scenarios

Put a domain professional persona in the chair and invent the things they would
actually ask the agent in their working day. Capture each as a structured,
multi-turn scenario spec with an A2UI surface note and a PRD signal.

This is **demand generation**, not feature documentation. Scenarios may exceed
what the agent currently does; that is intentional. Each scenario records whether
it is `buildable | partial | gap` so the catalog doubles as a roadmap signal for
`/analyze`.

## Usage

```
/scenario [persona | theme | count] [notes]
```

Examples:
- `/scenario` — generate a fresh batch (~6) spanning the agent's domain
- `/scenario re-investor` — focus on the real estate investor persona
- `/scenario 4` — generate exactly 4 scenarios
- `/scenario insurance 3` — three scenarios from the insurance underwriter seat
- `/scenario --live` — generate scenarios AND drive each turn 1 live via
  `python -m agent_sdk test-chat --app src.main:app`, writing actual replies
  into the scenario doc

## Steps

1. Parse `$ARGUMENTS` for an optional persona/theme and a count (default ~6).
2. Ensure `workspace/scenarios/README.md` exists. If missing, create it with the
   standard header + an empty table (see `workspace/scenarios/README.md`
   as template).
3. Read existing scenario files to find the highest SCN-NNN so far. New batch
   continues from there.
4. Identify which agent is in scope:
   - Running from an agent repo: read `src/main.py`, `src/tools/`, `src/content.py`
     to understand the domain, tools, and content types.
   - Running from the SDK harness: ask the user which agent to generate for, or
     use `$ARGUMENTS` if it names one.
5. Generate scenarios grounded in the agent's actual tools and content types.
   For each scenario:
   - Assign a domain letter + seat name (e.g. `A — Real estate investment`).
   - Write the turn-1 prompt the way a professional actually types it — terse,
     with real coordinates / entity names / parameter values where relevant.
   - Write the turn-2 reactive follow-up **as if you have just read the turn-1
     reply** — reference specific numbers, hazard names, or recommendations from
     what a realistic agent response would say.
   - Note which tools are called, what A2UI surface is emitted (if any), and
     the PRD signal (what requirement or gap this surfaces).
   - Tag capability: `buildable` (current code handles it), `partial` (handles
     it but with notable gaps), `gap` (requires new tooling or data).
6. Write the scenarios to `workspace/scenarios/NNN-[theme].md` following the
   standard schema (see Output contract below).
7. Update `workspace/scenarios/README.md`: append rows to the table, refresh the
   capability tally, and update the domain map if new domains appear.
8. If `--live` was passed: for each `buildable` scenario's turn 1, run:
   ```
   python -m agent_sdk test-chat --app src.main:app "{{turn_1_prompt}}"
   ```
   Capture the reply and splice it into the scenario doc under a `**Live reply
   (turn 1):**` block. In the scenarios README table, change the scenario's
   `Status` column to `live-tested` (add the `Status` column if not present).
9. Summarise back: number of scenarios, seat/theme mix, top 3 `gap` signals
   worth taking to `/analyze create prd`.

## Output contract

Scenarios are written to files, not dumped in chat — chat gets the summary
and gap shortlist only.

Every scenario follows this schema:

```markdown
### SCN-NNN — Title

**Domain:** letter — name
**Persona:** one-line description of who is asking
**Capability:** buildable | partial | gap
**Tools:** tool_name(key_params, …)  *(one line per discrete tool call)*

**Turn 1 (initial)**
> verbatim user prompt, the way a professional actually types it

**Turn 2 (reactive follow-up)**
> reactive follow-up based on what a realistic turn-1 reply would contain —
> reference specific values, hazard names, or recommendations by name

**A2UI surface:** component type emitted (or "none" if text-only)
**PRD signal:** one sentence: what requirement or gap this surfaces
**Resolution:** *(gap/partial only)* what needs to be built or added to make
  this fully buildable — e.g. "add batch endpoint", "expose indicator X in
  ClimateRiskReport"
```

Rules:
- Prompts are quoted in the user's voice (terse, real entity names).
- Relative dates become absolute (e.g. "next quarter" → "Q3 2026").
- A batch with 100% `buildable` is suspect — push past current capability.
- Each `gap` or `partial` entry must have a non-empty `Resolution:` field.
- A scenario that requires N separate tool calls has N `Tools:` lines.

## Hand-offs

- `gap` / `partial` scenarios → `/analyze create prd` (turn demand into FRs).
- Polished `buildable` scenarios → `python -m agent_sdk test-chat --app src.main:app
  "the verbatim prompt"` to run live.
- Identified PRD signals → `/analyze update prd` to wire into FRs.
