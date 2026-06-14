---
id: LRN-002
title: Pre-release redteam must run at full scope, not wave scope
category: ops
severity: high
source: manual
date: 2026-06-14
---

## What happened

The 0.4.0 pre-release redteam was scoped to the new Azure Storage code. GH issues #4–#8 are pre-existing bugs in protocol routes that were not touched by the Azure wave, so they passed through undetected.

## Root cause

Wave redteams are correctly scoped to changed code. But pre-release requires a full-scope pass to catch regressions and pre-existing issues on untouched surfaces.

## Check

Before any release commit, `/redteam` must be invoked with NO scope argument. A scope-restricted run (e.g., `/redteam w006`) is not sufficient for a release gate.

## Prevention

Add "Run `/redteam` at full scope (no argument)" as a mandatory pre-release gate step in the `/acceptance` skill. Scoped redteam is for wave-internal review only.
