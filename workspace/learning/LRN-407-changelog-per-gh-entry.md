---
id: LRN-407
title: CHANGELOG needs one entry per GH item and new public symbols
category: ops
severity: high
source: redteam
date: 2026-10-17
---

## What happened
GH-185 added public `agent_sdk.auth.current_identity` and touched seven agent_sdk files. The [Unreleased] block had no GH-185 entry, no `### Added` line for the symbol, and the GH-187 Fixed entry omitted tasks/memory.py and tasks/store.py.

## Root cause
A wave carrying two GH items updated the changelog for one and treated the other as covered.

## Check
Run `grep -c "GH-<n>" CHANGELOG.md` for every GH number in the wave and confirm >= 1. For each new name in `agent_sdk/*/__init__.py` `__all__`, grep CHANGELOG.md and confirm it sits under `### Added`. Every changed agent_sdk file must be named in some entry.

## Prevention
When planning a wave with several GH items, add a CHANGELOG task per GH number, listing new public symbols under Added and naming every changed source file, with the ruling URL. Make it an acceptance criterion before redteam.
