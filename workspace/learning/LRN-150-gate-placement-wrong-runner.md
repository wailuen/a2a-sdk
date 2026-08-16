---
id: LRN-150
title: Gate ported to the runner where it can never fire
category: sdk
severity: high
source: redteam
date: 2026-08-15
---

## What happened
RT-004: the RT-014 peer-repo check (`peerRepoAnnotations`) landed in wave-cycle.js
only, which runs in downstream repos lacking `harness/workflows/`/`template/`, so
it can never fire there. sdk-wave.js runs in a2a-sdk — the only repo with the
harness→template gap — and ran this wave, letting RT-001 through.

## Root cause
LRN-131's "port to every runner" rule was followed without checking which
runner's layout can trigger the guarded condition.

## Check
`grep -rc peerRepoAnnotations .claude/workflows/{sdk-wave,wave-cycle}.js` — both
nonzero; `PLAN_RT_SCHEMA.required` lists `peerRepoAnnotations` in both.

## Prevention
Before landing a harness/peer-repo gate, identify which runner's layout can
exhibit the condition (sdk-wave.js=a2a-sdk, wave-cycle.js=downstream) and land it
there first, then port for parity — one runner alone isn't enough.
