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
Run: `diff harness/workflows/acceptance-api.js template/.claude/workflows/acceptance-api.js` — output must be empty. Also grep for the stale path: `grep -n '/v1/message/stream' template/.claude/workflows/acceptance-api.js` — must return no matches.

## Prevention
When planning any change to harness/workflows/*.js, include a follow-on step that runs /upgrade harness-sync and verifies byte-equality between harness/workflows/ and template/.claude/workflows/ before closing the task. A harness workflow fix is incomplete until the template copy matches.
