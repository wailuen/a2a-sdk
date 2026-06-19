# LRN-053 — wave scope must union Creates: AND Modifies: paths

| Field      | Value                          |
|------------|--------------------------------|
| Category   | harness                        |
| Severity   | critical                       |
| Source     | redteam (RT-002, w020)         |
| Date       | 2026-06-18                     |
| Wave       | w020                           |

## Finding

`sdk-wave.js` derived every scope set — the empty-scope guard, the unit/phase
redteam scope, the protocol-surface detection, and the protocol-audit file
filters — from `Creates:` paths only (`wave.allCreates` / `group.creates`).
w020 was a modify-only wave (0 `Creates:`, 6 `Modifies:`), so `allCreates`
came back empty and the empty-scope guard false-aborted the wave as a "harness
bug." A modify-only wave that slipped past the guard would have landed with
EMPTY adversarial-review scope and NO protocol audit — a silent gate bypass.

## Pattern

**Creates-only scope derivation** — any wave-runner site that reads scope from
`Creates:` paths alone. Modify-only waves (skill/doc/config edits) carry zero
`Creates:` and are invisible or falsely-aborted.

## Root cause

The wave parser captured only `Creates:` paths into scope. `Modifies:` paths —
the entire surface of an edit-only wave — were never collected, so all
downstream scope consumers saw an empty set.

## Check

```bash
# Every scope consumer in a wave runner must derive from Creates ∪ Modifies.
# Flag any redteam/protocol/guard site reading allCreates or group.creates alone,
# across BOTH wave runners (sdk-wave.js AND both wave-cycle.js copies):
grep -nE 'allCreates|group\.creates' \
  .claude/workflows/sdk-wave.js \
  .claude/workflows/wave-cycle.js \
  harness/workflows/wave-cycle.js
# Each hit must instead use allScope / group.scope (= creates ∪ modifies),
# except the schema, parse prompt, and the derivation block itself.
```

## Prevention

Wave scope (empty-scope guard, redteam scope, protocol-surface detection and
audit filters, archive FR-mapping) MUST derive from `Creates:` ∪ `Modifies:`
paths (`allScope` / `group.scope`). The empty-scope guard fires only when BOTH
are empty. Exclude `[~]` (out-of-repo) and other-repo paths from scope.
Deriving scope from `Creates:` alone false-aborts modify-only waves and lands
them with no review. Note: the union fix was propagated to ALL three wave
runners in this same wave — `sdk-wave.js` and BOTH `wave-cycle.js` copies
(`.claude/workflows/` and `harness/workflows/`) now derive every scope set from
`allScope` / `group.scope`. The Check grep above must come back clean (schema /
parse-prompt / derivation lines only) on all three files.
