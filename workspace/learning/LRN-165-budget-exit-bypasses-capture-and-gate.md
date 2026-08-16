---
id: LRN-165
title: Unit round-cap exit skips codify capture, archive block
category: ops
severity: high
source: redteam
date: 2026-08-15
---

## What happened
Unit redteam's round-cap exit (`uRound >= 5`) in wave-cycle.js and its
sdk-wave.js mirrors writes a deferred note and breaks before
`allHighFindings.push(...)`, setting no blocking flag — surviving
critical/high findings skip Codify; group archives clean.

## Root cause
The budget-exit branch logs a human note but was never wired to the
obligations other exits meet: forward findings, set the flag archive
checks.

## Check
`grep -n "uRound >= 5" {.claude,harness}/workflows/wave-cycle.js
.claude/workflows/sdk-wave.js` — confirm findings push to
`allHighFindings` pre-break, and a flag ORs into archive beside
`protocolBlocked`.

## Prevention
Budget-capped fix loops must exit symmetrically: push surviving
critical/high findings to Codify pre-break, and OR a blocking flag into
archive — a deferred note is not one. Fix all runner copies together.
