---
id: LRN-013
severity: high
title: AC "integration note" wording targets the Integration section, not step bodies
---

## Observation
GH-12 acceptance criterion required the integration note in `harness/skills/upgrade/SKILL.md` to reference "SDK provisioning tool" instead of the bare `/new-agent` command. The step 10a body (line 104) was updated to include both flows, but the ## Integration section bullet (lines 266–269) still retained the old `/new-agent`-only phrasing. The AC was therefore not satisfied despite the step body being correct.

## Root Cause
When an AC says "integration note", the implementer updated the nearest prose block (the step body) and considered the task done, without checking the dedicated ## Integration section that also carried the targeted wording. Two locations in the same file contained equivalent phrasing, and only one was updated.

## Prevention
When an AC targets "integration note" wording, treat the ## Integration section as the canonical location and verify it explicitly. Cross-check every occurrence of the targeted phrase in the file before closing the AC — updating one location is not sufficient if the phrase appears in both a step body and a named section.
