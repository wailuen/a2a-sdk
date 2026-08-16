---
id: LRN-147
title: Peer-repo deliverable declared in a wave todo closed without its own commit existing
category: ops
severity: high
source: redteam
date: 2026-08-15
---

## What happened
GH-131/GH-132 named `template/.claude/workflows/wave-cycle.js` (the peer-repo
runtime copy) as a deliverable, per LRN-071/LRN-085. Both waves closed as
complete, but the peer-repo file was never touched — still has the pre-fix
`TODAY` line and none of the GH-132 severity-floor/budget logic. Every agent
scaffolded from the template ships both "fixed" bugs.

## Root cause
Completion was checked with in-repo tests/diffs scoped to a2a-sdk. Nothing in
the close-out gate inspects `template/`'s own git log, so a todo can be marked
done while the peer repo never received a commit or push.

## Check
```bash
test -d template/ && diff harness/workflows/wave-cycle.js template/.claude/workflows/wave-cycle.js
test -d template/ && git -C template/ log --oneline -1 -- .claude/workflows/wave-cycle.js
```
Both must show the change landed; a stale diff or pre-wave SHA means the
deliverable is still open.

## Prevention
When a todo lists a `template/.claude/workflows/*` path as a deliverable, the
close-out gate must diff it against the harness source AND confirm
`git -C template/ log -1` postdates the wave — not just that in-repo tests
pass. Do not archive until both are green.
