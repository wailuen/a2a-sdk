---
id: LRN-186
title: Protocol advisor filter(Boolean) drops null results (fail-open)
category: security
severity: critical
source: redteam
date: 2026-08-15
---

## What happened
`wave-cycle.js` (1653, 1810) and `sdk-wave.js` (1372, 1473) collect protocol advisors via `.filter(Boolean)` on the parallel() result. A crashed/rejected advisor returns null, gets dropped, never reaches `protoCritical`/`protoHigh`; the wave archives protocol-clean though never audited.

## Root cause
`filter(Boolean)` conflates "advisor crashed" with "found nothing" — the only unguarded result here; every other gate uses `if (!x) { ...blocked }`.

## Check
```
grep -n 'filter(Boolean)' .claude/workflows/wave-cycle.js .claude/workflows/sdk-wave.js
```
Any match on a `parallel(advisorTasks)` result is fail-open; must count nulls, block when >0.

## Prevention
When planning advisor aggregation here, require an explicit null count before filtering — nulls block archive, never drop silently. Cover initial and recheck sites.
