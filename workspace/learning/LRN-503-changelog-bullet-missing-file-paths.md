---
id: LRN-503
title: CHANGELOG bullet omits changed file paths and new exports
category: ops
severity: high
source: redteam
date: 2026-10-24
---

## What happened
The GH-244 bullet described console A2UI renderer caps but never named `agent_sdk/console/static/a2ui.js`, the only agent_sdk file changed. It also omitted the new export `MAX_COLUMNS` and the test files. The LRN-491 check found 0 hits for a2ui.js in [Unreleased].

## Root cause
The bullet was written from behaviour, not from the diff, and static JS was not treated as an agent_sdk file to cite.

## Check
For each changed `agent_sdk/` file in `git diff --name-only`, verify `grep -c '<full/repo/path>' CHANGELOG.md` inside [Unreleased] is at least 1, and that each new export name appears.

## Prevention
When planning any GH fix, add a task step: list `git diff --name-only -- agent_sdk` and cite every path (console static JS included) plus each new export and test file in that issue's own bullet.
