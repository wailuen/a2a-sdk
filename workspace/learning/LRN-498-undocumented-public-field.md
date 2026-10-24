---
id: LRN-498
title: New public field or keyword on exported class not in CHANGELOG
category: sdk
severity: high
source: redteam
date: 2026-10-24
---

## What happened
GH-240 added field `negotiate_standard` and keyword `keep_declared_catalogs` to `A2uiCapabilities` (exported by `agent_sdk.a2ui.__all__`). Neither was listed under `### Added`, nor named in DESIGN.md or docs. The field also changes `__eq__`/`repr`.

## Root cause
Changelog bullets described behaviour, not the new public symbols; the field was not made private or excluded from compare/repr.

## Check
Verify that `grep -n "negotiate_standard" CHANGELOG.md` matches under `### Added` with `agent_sdk/a2ui/translator.py`. For every new dataclass field or keyword on an exported class in the diff, grep its name in CHANGELOG.md.

## Prevention
When planning a change that adds a field or keyword to an exported class, require a CHANGELOG `### Added` line naming the symbol and file (LRN-293, LRN-423), or make the field private with `field(compare=False, repr=False)`.
