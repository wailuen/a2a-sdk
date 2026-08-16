---
id: LRN-163
title: Sync guard blind to cross-runner gate drift (wave-cycle.js vs sdk-wave.js)
category: sdk
severity: high
source: redteam
date: 2026-08-15
---

## What happened
The RT-004 archive hard-block for a missing `template/` checkout
(`templateDirExists` schema field, step 0 `test -d template`, and the
`declaresTemplateScope && templateDirExists === false` block) landed only in
the three wave-cycle.js copies. `.claude/workflows/sdk-wave.js` has neither
`templateDirExists` nor `declaresTemplateScope`, yet SKILL.md's wave skill
launches `sdk-wave.js` — the runner that actually executed the wave — so the
one gate built to catch this class never fired. Direct LRN-131 recurrence.

## Root cause
The byte-identical sync guard only enforces parity across the three
wave-cycle.js copies of each other; it still has no cross-runner check
against sdk-wave.js, so a gate added to wave-cycle.js drifts silently.

## Check
`grep -c templateDirExists .claude/workflows/sdk-wave.js .claude/workflows/wave-cycle.js`
— both must report the same nonzero count; same for `declaresTemplateScope`.

## Prevention
Any archive-gate clause added to wave-cycle.js must be ported to
sdk-wave.js in the same change. Add a tests/test_workflows.py parity case
asserting both runners' `ARCHIVE_INTENT_SCHEMA.required` sets are identical,
not just the three wave-cycle.js copies against each other.
