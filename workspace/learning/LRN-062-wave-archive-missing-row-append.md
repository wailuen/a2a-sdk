---
id: LRN-062
title: Wave archive silently skips plan.md when no pre-seeded row exists
category: ops
severity: high
source: redteam
date: 2026-06-18
---

## What happened
Wave w020 (a GH-issue wave) was archived to workspace/todos/completed/w020-gh-issues.md but left no trace in plan.md — the table ended at W19 with no W20 row. The wave completed successfully yet was invisible in the plan ledger.

## Root cause
The sdk-wave.js/wave-cycle.js archive step 2 only marks an existing plan.md row ([  ] → [x] ✅); GH-issue waves carry no pre-seeded row, so the step silently no-ops and the wave is never recorded.

## Check
After any wave archive, verify the waveId appears in plan.md:
`grep -c "w020" workspace/todos/plan.md` must return ≥ 1.
Also: `grep -E 'w[0-9]{3}' workspace/todos/completed/ -r | awk -F: '{print $2}' | grep -oE 'w[0-9]+' | sort -u > /tmp/archived.txt && grep -oE 'w[0-9]+' workspace/todos/plan.md | sort -u > /tmp/planned.txt && comm -23 /tmp/archived.txt /tmp/planned.txt` must output nothing.

## Prevention
When planning wave archive steps, ensure the archive logic APPENDS a new [x] ✅ row to plan.md when no existing row matches the waveId — do not assume a pre-seeded row exists. GH-issue waves and any ad-hoc waves will never have a pre-seeded row.
