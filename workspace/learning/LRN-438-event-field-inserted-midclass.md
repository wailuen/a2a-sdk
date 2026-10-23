---
id: LRN-438
title: New LoopEvent dataclass field inserted before existing fields
category: sdk
severity: high
source: redteam
date: 2026-10-22
---

## What happened
GH-220 added `DoneEvent.code` before `summary` and `ToolResultEvent.code`, in `agent_sdk/agent/events.py`. A positional call such as `DoneEvent(False, "err", "notice")` silently put the summary into `code`. CHANGELOG named only the AG-UI wire fields, not the new event fields.

## Root cause
A public dataclass was treated as internal; field order is part of the public surface.

## Check
In `agent_sdk/agent/events.py`, confirm every newly added field in a LoopEvent class comes after all prior fields (or is keyword-only), and `grep -n 'DoneEvent.code' CHANGELOG.md` hits.

## Prevention
When planning a field addition to a LoopEvent dataclass, require it to be appended last (or `kw_only`), a positional-call regression test, and a CHANGELOG line naming the event symbol.
