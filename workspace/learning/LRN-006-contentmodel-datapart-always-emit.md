---
id: LRN-006
title: ContentModel artifacts must always emit DataPart on A2A, not only when A2UI extension activated
category: protocol
severity: high
source: redteam
date: 2026-06-14
---

## What happened

GH #6 — `build_artifact()` in runner.py only appended a `DataPart` when `a2ui_messages is not None`, i.e., when the client had activated the A2UI extension via `X-A2A-Extensions`. Plain A2A clients (no extension) received only a `TextPart`. A2A spec §D3 requires structured artifacts to carry a `DataPart`; without it, machine-readable extraction is impossible and the A2UI extension is inoperable on the A2A transport.

## Root cause

The ContentModel branch fell through to TextPart-only when A2UI capability was absent, instead of always emitting a raw DataPart as the non-ContentModel BaseModel branch did.

## Check

Call `build_artifact()` with a ContentModel payload and `capabilities.a2ui_enabled = False`. Result must have `len(parts) == 2` including a `DataPart`.

## Prevention

When adding new ContentModel subclasses or touching `build_artifact()`, verify: (a) non-A2UI path produces 2 parts (TextPart + raw DataPart), (b) A2UI path produces 2 parts (TextPart + A2UI DataPart). Never 1-part or 3-part artifacts.
