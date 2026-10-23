---
id: LRN-453
title: Gate inputs re-read from model-relayed text are not deterministic
category: ops
severity: high
source: redteam
date: 2026-10-22
---

## What happened
`deriveGroupDeps` and `groupIsHeld` in wave-cycle.js read `t.body` from the model's Parse output, not the wave file. If Parse summarises or truncates a todo body, its `Depends:` line or HUMAN GATE marker vanishes silently, and a held group is dispatched.

## Root cause
The "deterministic cross-check" re-read text the model had already relayed, so GH-208's root cause (deps only from model parse) remained.

## Check
`grep -n "deriveGroupDeps\|groupIsHeld" harness/workflows/wave-cycle.js` shows deps and hold state come from the preflight script output; test that Parse aborts when a script-found todo id is missing from the model's groups.

## Prevention
When planning workflow gates, source dependency and hold data from a script reading the wave file directly, union it with model output, and abort on any id mismatch. Never treat model-relayed text as a cross-check.
