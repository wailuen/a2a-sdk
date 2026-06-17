---
id: LRN-040
title: Deterministic THREAD_ID in acceptance-api.js causes concurrent-run contamination
category: testing
severity: high
source: redteam
date: 2026-06-17
---

## What happened
`harness/workflows/acceptance-api.js` constructs `THREAD_ID = s.id + "-agui"` where
`s.id` is the scenario identifier — a static, deterministic string. Concurrent runs
of the same scenario (e.g. two CI jobs executing the same acceptance scenario in
parallel) share the same AG-UI thread ID and the same `/tmp/acc-{s.id}-agui-msgs.json`
scratch file. Messages from one run bleed into the other, corrupting the scoring
evidence and producing false-pass or false-fail results — a harness-contamination
failure class that was missing from `SCENARIO_RESULT_SCHEMA`.

## Root cause
The THREAD_ID was designed for single-run sequential execution. No UUID suffix was
added to isolate per-invocation state, and `additionalProperties: false` in
`SCENARIO_RESULT_SCHEMA` blocked the `harness-contamination` `failureClass` enum
value needed to classify this failure mode when it occurs.

## Check
```
grep -nE 'THREAD_ID = .*-agui' harness/workflows/acceptance-api.js
# Must show the value carries a per-invocation UUID suffix after the GH-53 fix.
# Example of correct output:
#   THREAD_ID = s.id + "-agui-" + invocationUUID
```

## Prevention
Any tmp file or thread-ID derived from a scenario ID must include a per-invocation
UUID suffix (e.g. `crypto.randomUUID()`) to guarantee isolation across concurrent
runs. Add `harness-contamination` to `SCENARIO_RESULT_SCHEMA.failureClass` enum
and document its classification rule in FINAL SCORING. Audit all `/tmp/acc-*`
filename literals for the same UUID scoping.
