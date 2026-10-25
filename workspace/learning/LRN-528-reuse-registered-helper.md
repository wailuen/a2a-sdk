---
id: LRN-528
title: Planned "Reuses C-NNN" helpers must import the component
category: sdk
severity: high
source: redteam
date: 2026-10-25
---

## What happened
`is_json_content_type` in agent_sdk/common/body.py re-implemented lowercase/drop-parameters instead of calling C-079 `normalize_media_type`. The GH-251 plan said it reuses C-079.

## Root cause
The implementer copied the normalization one-liner rather than importing the registered component, leaving two copies of the rule.

## Check
`grep -rn '.split(";", 1)\[0\].strip().lower()' agent_sdk/` must match only agent_sdk/common/media.py.

## Prevention
When a plan says "Reuses: C-NNN", require an import of that symbol in the todo's acceptance criteria. Only the logic specific to the new helper stays local.
