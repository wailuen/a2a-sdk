---
id: LRN-167
title: Cost backstop default must scale with wave shape
category: ops
severity: high
source: redteam
date: 2026-08-15
---

## What happened
`AGENT_CALL_BUDGET` in `wave-cycle.js:456` (and `sdk-wave.js:432`)
defaults to 150 and throws when exceeded. The file's own comment
(451-453) and both wave SKILL.md copies say a routine 4-group wave
already costs ~4x20 unit + 32 phase + 24 codify/implement/archive
calls — above 150.

## Root cause
Backstop is a fixed constant unrelated to `groups.length`, though
group count is known when the budget is read.

## Check
Grep `Number(normalizedArgs.agentBudget) || 150` in both files;
confirm fallback scales with `groups.length`, not a literal. Confirm
`agentBudget: 0` is rejected, not silently defaulted.

## Prevention
A hard ceiling from a documented per-unit cost must scale with run
shape, not stay a constant the same change admits is below
common-case cost. Cross-check LRN-156 (override exists) — this
checks the default is sized right.
