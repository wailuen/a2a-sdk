---
id: LRN-157
title: Parametrize helper drops missing mirror-repo paths
category: testing
severity: high
source: redteam
date: 2026-08-15
---

## What happened
GH-131/GH-132 declare `template/.claude/workflows/wave-cycle.js` under
`Modifies:`, but `template/` is absent from this checkout, so the copy was
never updated. `_existing_wf_files` in `tests/test_workflows.py` filters
parametrization to paths that exist on disk, silently dropping the missing
axis — tests pass green while the runtime copy agents actually run still
has the old buggy logic.

## Root cause
A path-existence filter treats "file absent" as "skip this case" instead of
"must fail," turning a missing peer-repo deliverable into silent coverage.

## Check
Verify each `Modifies:`-declared peer-repo path has a presence-guard test
(mirroring acceptance-api.js's strict-xfail pattern) that fails/xfails,
not silently skips, when the mirror file is absent.

## Prevention
When a plan declares a peer-repo `Modifies:` path, require a dedicated
presence-guard test (not a filtered parametrize axis) plus a final
`git commit && push` step inside the peer repo checkout.
