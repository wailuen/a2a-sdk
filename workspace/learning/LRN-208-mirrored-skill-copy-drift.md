---
id: LRN-208
title: Authoring SKILL.md fixed, sibling copies left stale
category: protocol
severity: high
source: redteam
date: 2026-08-19
---

## What happened
GH-144's completed-vs-interrupted fix (LRN-103) landed only in
`harness/skills/acceptance/SKILL.md`. Sibling copies
`.claude/skills/acceptance/SKILL.md` and
`template/.claude/skills/acceptance/SKILL.md` — the ones actually executed
(LRN-071) — still tell drivers to reuse `taskId` every turn, so multi-turn
`/acceptance` fails 501/-32004 on turn 2+.

## Root cause
The wave treated the authoring source as the whole contract, never
diffing its sibling copies.

## Check
```bash
diff harness/skills/acceptance/SKILL.md .claude/skills/acceptance/SKILL.md
diff harness/skills/acceptance/SKILL.md template/.claude/skills/acceptance/SKILL.md
```
Both empty; siblings must not match `"same task context"`.

## Prevention
When a SKILL.md has sibling copies under `.claude/` or
`template/.claude/`, diff+update every sibling in the same wave
(LRN-086, LRN-071).
