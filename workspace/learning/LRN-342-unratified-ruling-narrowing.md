---
id: LRN-342
title: Wave narrowed a maintainer ruling and docs claimed otherwise
category: protocol
severity: high
source: redteam
date: 2026-10-13
---

## What happened
The GH-167 ruling said standalone titles, names, summaries and as-of headers keep ASCII. EntityList names and summaries, KpiCard/ComparisonTable titles and EmailList previews still used _sanitize_cell. CHANGELOG and DESIGN.md section 4.0 said otherwise, and a test asserted the opposite of the AC.

## Root cause
The wave kept the old sanitizer on slots the ruling named, without escalating, and the docs described the plan rather than the code.

## Check
Verify the AC test asserts 'Smith, John' unchanged for EntityList names. Verify each slot listed in the CHANGELOG GH-167 entry and DESIGN.md section 4.0 uses safe_line_text in content_types.py. Otherwise a maintainer approval URL must be in the wave file.

## Prevention
When planning, ensure any narrowing of a ruling is escalated and its approval URL recorded before release. CHANGELOG and DESIGN must list slots that actually changed.
