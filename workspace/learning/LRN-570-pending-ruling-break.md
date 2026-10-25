---
id: LRN-570
title: No wave-added break may ship with Ruling PENDING
category: sdk
severity: high
source: redteam
date: 2026-10-25
---

## What happened
The reserved-hook TypeError in `_Wire.__pydantic_init_subclass__` shipped as a Breaking bullet with "Ruling: PENDING". It was outside the #270 ruling, and the wave approved it itself. The bullet also said "declares or inherits" when the code raises only if the subclass also defines its own model_serializer.

## Root cause
The wave self-approved a break beyond the posted ruling instead of getting user ratification or downgrading it.

## Check
grep -n "Ruling: PENDING" CHANGELOG.md and confirm no match before release. Confirm each Breaking bullet cites an `issuecomment-` URL.

## Prevention
When a wave finds it needs a break beyond the ruling, either record a user ruling comment before the wave lands, or downgrade it (warning, not TypeError) and move it to Changed.
