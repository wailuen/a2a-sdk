---
id: LRN-472
title: New boot-time rejection shipped without Breaking entry
category: sdk
severity: high
source: redteam
date: 2026-10-23
---

## What happened
GH-205 made a registered tool named `load_skill` raise ValueError whenever skills_dir is set, even with mcp_skills=None (agent_sdk/app.py:665). Before, such an agent booted. CHANGELOG listed it under Changed with no Breaking entry or Migration line.

## Root cause
The rejection was treated as part of an opt-in feature, though it fires for existing agents.

## Check
grep CHANGELOG.md for the reserved name `load_skill` and confirm a `Breaking changes` bullet with a `**Migration:**` line and the ruling URL (LRN-321, LRN-371).

## Prevention
When planning any new construction-time check that can fail an existing agent's boot, require a Breaking entry with Migration, even if it ships with an opt-in feature.
