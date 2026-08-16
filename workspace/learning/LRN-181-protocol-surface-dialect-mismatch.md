---
id: LRN-181
title: Runner protocol-surface arrays hardcoded to one repo's dialect
category: sdk
severity: high
source: redteam
date: 2026-08-15
---

## What happened
wave-cycle.js's protocol-surface arrays are `src/`-prefixed, but a2a-sdk's
source lives under `agent_sdk/`. SKILL.md Mode B pointed a resumed wave at
wave-cycle.js instead of sdk-wave.js, so `runProtocol` evaluated false
everywhere — Protocol Audit silently skipped, MCP wire-shape breaks shipped
unaudited, no log line naming the mismatch.

## Root cause
Runner selection was documented by cross-reference, not by name; no defense
existed against a layout the prefixes can't match.

## Check
`grep -n "wave-cycle.js" .claude/skills/wave/SKILL.md` — Mode B names the
runner explicitly. `grep -n wrongRunnerForRepoLayout .claude/workflows/wave-cycle.js`
shows the Parse-phase guard.

## Prevention
When path-prefix arrays assume one repo's source-root convention, every doc
entry point must name the runner, plus a fail-closed layout check.
