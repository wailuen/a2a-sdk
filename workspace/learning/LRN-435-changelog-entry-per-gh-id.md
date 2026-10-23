---
id: LRN-435
title: CHANGELOG [Unreleased] missing entries for GH ids a group names in its AC
category: sdk
severity: high
source: redteam
date: 2026-10-22
---

## What happened
`[Unreleased]` listed only some GH ids of the group. GH-221, GH-218 and GH-204 had no entry, the GH-209 entry pointed at a missing GH-204 entry, and the new public constant `MCP_INTERRUPT_SUFFIX` and the `-32601` -> `-32602` wire change were undisclosed.

## Root cause
Done-checks verified one CHANGELOG line per wave, not one per GH id in the group.

## Check
For every GH id in the group run `grep -n 'GH-<n>' CHANGELOG.md` and confirm a hit inside `[Unreleased]`. Also `grep -n 'MCP_INTERRUPT_SUFFIX' CHANGELOG.md`.

## Prevention
When planning a group, add an AC per todo: "CHANGELOG [Unreleased] has a line naming GH-<n>", with the heading (Added/Changed/Fixed/Breaking), new public symbols, and updated docs. Breaking wire changes need a migration note (DESIGN.md exemption rule).
