---
id: LRN-101
title: Agent card description must never fall back to empty string
category: protocol
severity: low
source: implement
date: 2026-06-21
---

## What happened

In `agent_sdk/routes/agent_card.py`, the `description` field on the AgentCard was
populated via `agent_description or ""`. When `agent_description` is blank, this
emits `""` onto the wire. A2A v0.3.0 §3.1 requires `description` to be a
human-readable string; the type constraint is satisfied but the semantic intent
is violated.

## Root cause

Any fallback chain that terminates in `""` for a REQUIRED A2A string field is
spec-marginal: the JSON type passes schema validation while the semantic contract
("human-readable") is broken. The fix resolves the fallback to
`_desc_stripped or settings.display_name`, ensuring the field is always
non-empty.

## Check

Grep `agent_sdk/routes/agent_card.py` for `or ""` and confirm no match on the
line that assigns the `description` field of AgentCard; also verify that the
description assignment reads `_desc_stripped or settings.display_name`.

## Prevention

When planning any route or factory that constructs an AgentCard (or any A2A wire
object with a REQUIRED string field), ensure the fallback chain cannot produce
`""`. Use `field or fallback_sentinel` — where `fallback_sentinel` is a
guaranteed non-empty value such as `settings.display_name`.
