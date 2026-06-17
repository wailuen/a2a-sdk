---
id: LRN-042
title: buildScenarioPrompt silently drops followUpTurns via JS destructuring default
category: testing
severity: high
source: redteam
date: 2026-06-17
---

## What happened
`harness/workflows/acceptance-api.js` `buildScenarioPrompt()` destructured the
scenario object but omitted `followUpTurns` from the destructured fields. The
function always built single-turn prompts regardless of the scenario definition,
so multi-turn scenario coverage was silently absent from every acceptance run.
No error was raised — the field was simply never read.

## Root cause
JS destructuring with no rest spread (`...rest`) silently discards unknown
fields. `followUpTurns` was added to the scenario schema after the function was
written, and the destructuring pattern was never updated. Because the function
still produced valid output (a single-turn prompt), no test caught the omission.

## Check
```
grep -n 'followUpTurns' harness/workflows/acceptance-api.js
# Must appear in both (a) the destructuring pattern inside buildScenarioPrompt
# and (b) the loop/emit block that builds multi-turn message sequences.
# Zero matches, or a match only in one of the two places, signals the bug is
# still present.
```

## Prevention
When planning schema extensions to scenario objects, ensure every consumer
function (buildScenarioPrompt, scoring, result serialisation) explicitly handles
the new field. Add a unit test that passes a scenario with followUpTurns > 0 and
asserts the emitted prompt array has length > 1; this prevents silent drop on
future schema additions.
