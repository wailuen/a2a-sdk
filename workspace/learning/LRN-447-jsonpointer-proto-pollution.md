---
id: LRN-447
title: JSON-Pointer setter lacks prototype-pollution guard
category: security
severity: high
source: redteam
date: 2026-10-22
---

## What happened
pointerSet() in agent_sdk/console/static/a2ui.js walks agent-supplied pointer tokens unguarded. An updateDataModel with path "/__proto__/polluted" set ({}).polluted in the admin console page, leaking into later `in` checks and fetch() options.

## Root cause
Untrusted tokens were used as object keys with no blocklist; GH-215 rewrote the path code without closing it.

## Check
Node test folds "/__proto__/x" and "/constructor/prototype/x" and asserts ({}).x === undefined. Also `grep -n "__proto__" agent_sdk/console/static/a2ui.js` must match a guard.

## Prevention
When planning any code that writes by JSON-Pointer or path from agent or tool output, require rejecting __proto__/constructor/prototype tokens, using Object.hasOwn, plus a pollution test.
