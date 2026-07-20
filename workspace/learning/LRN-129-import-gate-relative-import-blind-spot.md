---
id: LRN-129
title: Import gate only resolves absolute imports, misses relative
category: ops
severity: high
source: redteam
date: 2026-07-20
---

## What happened
GH-118's archive gate (sdk-wave.js step 5b) only parses
`from agent_sdk... import ...`. All of `agent_sdk/routes/` uses relative
imports (36 `from ..`, 0 absolute). LRN-119's case —
`from ..common.origin import guard_origin` — is spelled `from ..`, so a
compliant agent skips it and archives an untracked module clean.

## Root cause
The gate anchors on one import spelling (absolute), missing the
codebase's dominant relative style — its own motivating case.

## Check
Verify step 5b resolves `from .`/`from ..` against the importing file's
package dir, not just `agent_sdk.*`-absolute. Also confirm
`import agent_sdk.<mod>` and `from agent_sdk import X` are covered.

## Prevention
Any import-scanning/lint gate here must resolve BOTH absolute and
relative (`from .`/`from ..`) forms — relative is the dominant
intra-package style.
