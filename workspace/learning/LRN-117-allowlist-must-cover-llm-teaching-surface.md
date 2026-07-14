---
id: LRN-117
title: Allowlist must cover LLM system-prompt teaching surface
category: protocol
severity: high
source: protocol-audit
date: 2026-07-14
---

## What happened
`catalog.py::get_system_prompt_section()` (L154) ignores
`a2ui_allowed_components` (SC-D2), unlike its 3 siblings which filter via
`_filtered_types()`. `app.py:546` calls it with zero args, so the LLM is
taught schemas for disallowed components.

## Root cause
SC-D2 was wired into tool-emits validation and agent-card ads, but the
system-prompt consumer was missed.

## Check
`grep -n "def get_system_prompt_section" agent_sdk/a2ui/catalog.py` — confirm
it takes `allowed_components` and uses `_filtered_types()`; confirm `app.py`
passes `settings.a2ui_allowed_components` there.

## Prevention
When planning an allowlist feature, enumerate every call site reading the
registry — tool validation, card ads, AND system-prompt text — filter each;
"gated at emits layer" is insufficient since the LLM emits free-form JSON.
