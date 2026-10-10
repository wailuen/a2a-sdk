---
id: LRN-268
title: Plan-time component ID goes stale in Reuses
category: ops
severity: high
source: redteam
date: 2026-10-09
---

## What happened
GH-152-D declared `Reuses: C-022`, but C-022 is advisor_skill_mirror_parity in the registry. The real new component (OidcRelyingParty + IdpFlowStore in agent_sdk/auth/oidc.py) called itself C-023, and no C-023 row existed, so the Dimension 8 check hit the wrong symbol.

## Root cause
The ID was guessed at plan time and never rewritten when the component was registered.

## Check
Every `Reuses: C-NNN` in the wave todos must have a row in workspace/components/README.md whose file matches the symbol imported; grep the registry for each new component docstring ID.

## Prevention
When planning, never hard-code a future C-NNN; at registration take the next free ID from the registry and rewrite all todo `Reuses:` lines (and drop stale annotations) before archive.
