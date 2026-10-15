---
id: LRN-371
title: Wire key removal and wire() type change filed outside Breaking
category: sdk
severity: high
source: redteam
date: 2026-10-15
---

## What happened
The [Unreleased] CHANGELOG put GH-177 (removed wire keys `web_url`, `last_modified`), GH-179(5) (`MarketBriefing.wire()` dict to str, AG-UI `data` object to string) and GH-179(3) (new ValidationErrors) under Fixed/Changed with no Migration line. The str return also fails the dict-only check in runner.py for domain subclasses with their own catalog_id.

## Root cause
Rulings called the changes "not breaking for model users", so the wire-level and construction-time breaks were not classed as Breaking.

## Check
In CHANGELOG.md [Unreleased], confirm each removed wire key, wire() return-type change and new construction-time rejection sits under "Breaking changes" with a **Migration:** line. Test: register a MarketBriefing subclass with a domain catalog_id and run it through runner.py.

## Prevention
When planning, classify any wire value type change, removed wire key or new construction-time rejection as Breaking with a Migration line, whatever the ruling says. Grep callers of an overridden `wire()` for type assumptions.
