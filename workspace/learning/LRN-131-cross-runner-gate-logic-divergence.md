---
id: LRN-131
title: Cross-runner gate logic diverges when a fix lands in only one runner
category: sdk
severity: high
source: redteam
date: 2026-07-20
---

## What happened
The RT-004 four-way disambiguation for the GH-118 archiveIntent import cross-check was
added to sdk-wave.js but never ported to wave-cycle.js. All 3 byte-identical copies of
wave-cycle.js (`.claude/workflows/`, `harness/workflows/`, `template/.claude/workflows/`)
still use the older 2-branch resolution, so pkg-path-as-MODULE and sub-package mis-resolutions
in the ABSOLUTE and RELATIVE-with-module-path from-import steps are silently never flagged —
reintroducing the exact LRN-119 ImportError-at-boot class the gate exists to prevent.

## Root cause
The byte-identical sync guard only enforces parity across the three wave-cycle.js copies of
each other; it has no cross-runner check between sdk-wave.js and wave-cycle.js, so a gate-logic
refinement made in one runner silently drifts from the other.

## Check
`grep -c "itself names a MODULE and" .claude/workflows/sdk-wave.js .claude/workflows/wave-cycle.js`
— both files must report the same nonzero count. Also diff the archiveIntent import-resolution
prose block between the two runners on every wave-cycle.js edit.

## Prevention
When planning a fix to shared archiveIntent/gate prompt logic, require the planner to identify
every runner implementing that gate (currently sdk-wave.js AND wave-cycle.js x3 copies) and port
the change to all of them in the same wave — never treat the byte-identical-copy sync guard as
sufficient. Prefer extracting the shared prose into one constant both runners import/reference.
