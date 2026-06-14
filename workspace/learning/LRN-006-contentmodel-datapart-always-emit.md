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

Import `build_artifact` and a domain ContentModel subclass. Construct `A2uiCapabilities(tier="core", catalogs=["urn:a2ui-profile:standard:v1"])` with a domain type whose `catalog_id` differs from the standard catalog (so `caps.allows(ModelCls) == False`). Call `build_artifact(event, caps)` — result must have `len(artifact.parts) == 2` with the second part being a `DataPart` containing the raw model dump. Also verify the A2UI-enabled path: pass matching catalogs → second part is a `DataPart` with `metadata["mimeType"] == "application/a2ui+json"`.

## Prevention

When adding new ContentModel subclasses or touching `build_artifact()`, verify: (a) non-A2UI path produces 2 parts (TextPart + raw DataPart), (b) A2UI path produces 2 parts (TextPart + A2UI DataPart). Never 1-part or 3-part artifacts.
