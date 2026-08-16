---
id: LRN-075
title: Harness workflow fixes don't propagate to template peer repo
category: ops
severity: high
source: redteam
date: 2026-06-15
---

## What happened
A round of GH-71 bug fixes was applied to harness/workflows/acceptance-api.js (wrong stream path, JSON-RPC envelope, missing messageId, stale event parsing, bare s.id paths, missing followUpTurns, missing harness-contamination enum value). The template peer repo's copy at template/.claude/workflows/acceptance-api.js was not updated, so every new agent scaffolded from the template ships all the bugs that were just fixed.

## Root cause
template/ is an independent git repo (gitignored at .gitignore:38), so changes to harness/workflows/*.js are never automatically reflected in the template copy. The /upgrade harness-sync step is the only propagation path, and it was not run after the fixes landed.

## Check
`template/` is a peer-repo checkout (wailuen/a2a-agent-template, LRN-071) and is not
always present locally. Guard on its presence on the same line as the grep/diff (see
LRN-054) — a guard on its own line, even conditionally indented, is still flagged as
a dead-path guard:

```bash
test -d template/ && diff harness/workflows/acceptance-api.js template/.claude/workflows/acceptance-api.js
test -d template/ && grep -n '/v1/message/stream' template/.claude/workflows/acceptance-api.js
```

The diff must be empty and the grep must return no matches.

## Prevention
When planning any change to harness/workflows/*.js, include a follow-on step that runs /upgrade harness-sync and verifies byte-equality between harness/workflows/ and template/.claude/workflows/ before closing the task. A harness workflow fix is incomplete until the template copy matches.
