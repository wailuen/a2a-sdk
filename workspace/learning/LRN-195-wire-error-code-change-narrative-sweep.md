---
id: LRN-195
title: Wire error code change must reconcile every learning/skill narrative
category: protocol
severity: high
source: redteam
date: 2026-08-19
---

## What happened
GH-144 changed `message/stream`'s terminal-taskId response to match
`message/send`'s existing `-32004`/501, but LRN-103's "What happened"/"Impact"
prose and `harness/skills/acceptance/SKILL.md:200` still asserted the old
`-32001`/404 for both methods. A redteam or advisor agent reading either
stale artifact would score the corrected code as a regression and push to
revert the fix.

## Root cause
No step in the wave closing a wire-format/error-code change greps
`workspace/learning/` and `harness/skills/` for the old value; narrative
reconciliation was treated as optional cleanup rather than part of the change.

## Check
When a wave changes a JSON-RPC error code, HTTP status, or wire field for an
existing behavior, grep `workspace/learning/*.md` and `harness/skills/**/*.md`
for the old code/value (e.g. `grep -rn -- "-32001" workspace/learning
harness/skills`) and confirm zero stale matches remain outside a documented
"originally recorded X, corrected to Y" note.

## Prevention
When planning a wave that changes an observable wire contract (error code,
status, field shape), add an explicit task to grep learning/skill docs for
the prior value and reconcile every hit in the same wave — never a follow-up.
Sibling modes: LRN-066 (narrative/code drift), LRN-133 (reversed-decision
Check reconciliation).
