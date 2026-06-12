---
name: wave
category: core
description: "Execute one w[NNN] wave: implement todos in parallel groups → unit zero-tolerance redteam → phase zero-tolerance redteam → protocol audit → codify LRNs → archive. Workflow-orchestrated."
---

# /wave — Single-Wave Executor

Execute one `w[NNN]` wave file end-to-end — implement, redteam to zero,
codify, archive. Uses the `wave-cycle` Workflow for deterministic parallel
fan-out and loop control.

## Usage

```
/wave [wave-id | next | status]
```

- `(no args)` / `next` — run the next incomplete wave whose `Depends:` are
  all in `completed/`
- `w001` — run that specific wave
- `status` — progress dashboard: active / completed / deferred counts + dates

## When to use vs /implement

| /wave | /implement |
|-------|------------|
| One wave at a time; you review before proceeding | All waves autonomously |
| Workflow-visible fan-out you can watch live | Model-driven orchestration |
| Manual gating between waves | Hands-off end-to-end preferred |

## Steps — Execute

1. Resolve the target wave file:
   - `w[NNN]` arg → `workspace/todos/active/w[NNN]-*.md`
   - `next` or empty → first incomplete wave in `plan.md` whose every
     `Depends:` is in `completed/`
2. **Hard stop** if any `Depends:` item is not in `completed/` — report which
   dep is missing.
3. Launch the Workflow:
   ```js
   Workflow({
     scriptPath: ".claude/workflows/wave-cycle.js",
     args: { waveFile: "<absolute path to wave file>", today: "<YYYY-MM-DD>" }
   })
   ```
4. After the Workflow returns, display the summary:
   - Todos completed / deferred
   - Unit-redteam rounds per group, phase-redteam rounds
   - Protocol audit triggered (yes/no) and outcome (pass / blocked)
   - LRN entries captured
   - Wave status: ✅ archived, ⚠️ deferred items remain, 🔴 protocol-blocked
5. Suggest next step: `/wave next` or `/todos status`.

## Steps — Status

1. Read `workspace/todos/plan.md`.
2. List `active/`, `completed/`, `deferred/`.
3. Report per-wave: checkbox state, ✅ date (if archived), deferred reason.

## SDK Security Invariants — checked inside the Workflow (fail closed)

| ID | Invariant | Severity |
|----|-----------|----------|
| SI-1 | No raw HTTP in `src/tools/` | Critical |
| SI-2 | Exception text never leaks credentials/tokens/inputs | Critical |
| SI-3 | URL path variables through `url_segment()`/`safe_id()` | High |
| SI-4 | Credentials via `self.credential()` only | High |
| SI-5 | All endpoints require auth | Critical |
| SI-6 | Upstream vendor keys in credential store only | Critical |
| SI-7 | Every adapter has non-empty `allowed_hosts` | High |

## Protocol Audit — automatic conformance gate

Fires after Phase Redteam whenever `Creates:` paths touch a protocol surface:

| Surface | Trigger paths | Advisor |
|---------|---------------|---------|
| A2A + MCP | `src/routes/a2a`, `src/routes/mcp`, `src/routes/oauth`, `src/routes/agent_card`, `src/models/a2a` | `a2a-advisor` |
| AG-UI | `src/routes/ag_ui` | `ag-ui-advisor` |
| A2UI | `src/a2ui/`, `src/models/content_types` | `a2ui-advisor` |
| Cross-protocol seam | any of the above | general-purpose |

Critical protocol findings → one fix round + recheck → if still critical,
archive is **blocked**; wave moves to `workspace/todos/deferred/`.

## Integration

- **`/todos`** generates the wave files that `/wave` executes
- **`/implement`** runs all waves autonomously via model-driven orchestration
  (it does NOT call `wave-cycle.js` — it uses `Agent` calls directly, trading
  Workflow-visible fan-out for unattended end-to-end execution)
- **`/redteam`** can be run standalone between waves
