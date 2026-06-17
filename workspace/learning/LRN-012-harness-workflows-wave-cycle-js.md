---
id: LRN-012
title: wave-cycle.js A2UI audit prompt misstated Standard Profile type counts as Core 7 + Extended 11 instead of Core 6 + Extended 8
category: harness
severity: high
source: redteam
date: 2026-06-14
---

## Observation

Line 586 of `harness/workflows/wave-cycle.js` instructs the A2UI protocol auditor to validate against "Core 7 + Extended 11 Standard Profile types only". The actual SDK defines Core 6 (KpiCard, TimeSeriesChart, ComparisonTable, BarChart, EntityList, MarketBriefing) + Extended 8 (WaterfallChart, MultiCategoryChart, FundPerformance, EmailList, CalendarEvents, UserProfile, UserList, DocumentList) = 14 FROZEN types total, plus 4 RESERVED names that are never emitted. The prompt count 7 + 11 = 18 does not match the implementation.

Canonical sources: `DESIGN.md §5.4` and `agent_sdk/models/content_types.py` lines 1-3 and 205.

## Root Cause

The audit prompt string was written (or last updated) against an earlier draft of the Standard Profile before the type list was finalized. When the profile was trimmed to 14 FROZEN + 4 RESERVED, the hardcoded count in the wave-cycle prompt was not updated in sync with `DESIGN.md` and `content_types.py`.

## Prevention

When the Standard Profile type list changes, update `harness/workflows/wave-cycle.js` in the same commit as `DESIGN.md §5.4` and `content_types.py`. Treat the three files as a single logical unit: any discrepancy between them is a defect. The correct phrase is: "Core 6 + Extended 8 Standard Profile types only (14 FROZEN total; 4 RESERVED names are never emitted)."

## Check

```bash
grep -rn "Core 7\|Extended 11" harness/workflows/wave-cycle.js .claude/workflows/wave-cycle.js
```
Must return nothing. Any match means this learning regressed.

```bash
grep -c "class.*ContentModel" agent_sdk/models/content_types.py
```
Count must be 14 (FROZEN types) plus 4 RESERVED names. If the count changes, update wave-cycle.js and DESIGN.md §5.4 in the same commit.
