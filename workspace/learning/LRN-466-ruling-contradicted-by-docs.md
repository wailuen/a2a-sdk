---
id: LRN-466
title: Wave docs contradict maintainer ruling without re-ruling
category: protocol
severity: high
source: redteam
date: 2026-10-23
---

## What happened
GH-221 part 5 ruling said to document adding `anyOf: [{required:[A]},{required:[B]}]` via `model_config = {"json_schema_extra": ...}`. The landed docs/tools.md says never to put `anyOf`/`oneOf`/`allOf` at the top level and teaches a model_validator pattern. No re-ruling was recorded on the issue.

## Root cause
The wave judged the ruled instruction technically wrong and inverted it silently; a wave-made deviation is a proposal, not a decision.

## Check
Verify that every docs/tools.md statement on top-level `anyOf` matches the ruling on issue 221, or cites a newer ruling comment URL: `grep -n "anyOf" docs/tools.md CHANGELOG.md` and confirm a ruling URL is cited next to any contrary guidance.

## Prevention
When planning, if a ruled AC looks technically wrong, add an escalation step that posts evidence on the issue and waits for a new ruling URL before any contrary change is landed. Never invert a ruled AC in docs or code.
