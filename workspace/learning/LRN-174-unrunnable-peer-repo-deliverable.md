---
id: LRN-174
title: Wave executes with a declared template/ deliverable it cannot reach
category: ops
severity: high
source: redteam
date: 2026-08-15
---

## What happened
GH-131/GH-132 both declared `template/.claude/workflows/wave-cycle.js`
(LRN-071/085 peer-repo annotation) as a deliverable with an explicit
`git -C template/ commit && push` step, but `template/` doesn't exist in
this checkout. Neither fix reached the copy `/wave` actually executes;
`test_wave_cycle_is_harness_template_shared` and
`test_acceptance_api_is_harness_template_shared` both `xfail` instead of
failing, so pytest reports green over an unlanded deliverable (w036 RT-001,
still open — recurs as RT-005).

## Root cause
The precondition (peer checkout present) is checked only by the runtime
guard degrading to xfail, not by a planning-time gate — so a wave is let to
execute and "complete" against a target it structurally cannot reach.

## Check
```bash
test -d template/ || echo MISSING
pytest -q tests/test_workflow_sync.py -rA | grep -c XFAIL   # must be 0
```

## Prevention
At Parse phase, when any todo's Creates:/Modifies: names a `template/*`
path, hard-block the wave unless `test -d template/` is true — require a
clone-first todo rather than letting execution proceed and the propagation
guard silently xfail.
