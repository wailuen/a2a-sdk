---
id: LRN-182
title: Ported gate keeps wrong runner's source-root path dialect
category: sdk
severity: high
source: redteam
date: 2026-08-15
---

## What happened
GH-132 required offendingUndeclaredScope land identically in all wave
runners. The port kept sdk-wave.js's `agent_sdk/**.py` glob (schema,
comments, prompt) in wave-cycle.js, whose downstream repos keep source
under `src/` — a permanent no-op there.

## Root cause
"Identically" was read as byte-identical text, not dialect-translated.
wave-cycle.js:88 already documents AUTH_SURFACE's per-runner dialect; not
applied here. Same leak recurs in offendingUndeclaredImports.

## Check
`grep -n agent_sdk .claude/workflows/wave-cycle.js
harness/workflows/wave-cycle.js` — zero matches in schema/prompt text
(must read `src/**.py`).

## Prevention
Porting a gate across runners requires a per-runner dialect translation
step (src/ vs agent_sdk/), citing AUTH_SURFACE as template, plus a test
asserting each mirror keeps its own dialect string.
