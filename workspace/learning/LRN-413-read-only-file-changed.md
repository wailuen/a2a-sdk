---
id: LRN-413
title: File listed under Reads was modified, missing from scope and changelog
category: ops
severity: high
source: redteam
date: 2026-10-17
---

## What happened
GH-185 changed `agent_sdk/agent/runner.py` (bind_identity rebind in `wait_resume`), but the todo listed it only under Reads. The G1 review scope and CHANGELOG entry omitted it, and four tests changed for GH-187 were also undeclared.

## Root cause
Scope was fixed at planning time; files first read, then edited during implementation were never promoted to Creates/Modifies.

## Check
Run `git diff --name-only -- agent_sdk tests` and confirm every path appears in a todo's Creates/Modifies line and is named in that issue's `[Unreleased]` CHANGELOG entry.

## Prevention
When planning, treat any Reads file that may need a hook or rebind as Modifies up front. At wave close, diff changed files against todo Creates/Modifies and CHANGELOG, and add any missing.
