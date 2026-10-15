---
id: LRN-361
title: Mid-wave ingress hardening missing from todo Modifies and CHANGELOG
category: ops
severity: high
source: redteam
date: 2026-10-15
---

## What happened
GH-173 added a new module (common/json_strict.py) and edited routes/a2a.py, routes/oauth.py and ag_ui.py mid-wave. None were on the todo's Modifies line, and the CHANGELOG omitted them and the new helper. The scope audit failed. Reverse drift too: a listed test file was untouched.

## Root cause
Files added during fix rounds were not back-propagated to the todo and CHANGELOG.

## Check
For each path in `git status --porcelain`, grep workspace/todos/active/*.md for it on a Creates:/Modifies: line; confirm CHANGELOG names new public helpers (`grep loads_strict CHANGELOG.md`). Confirm every listed file has a diff.

## Prevention
When planning, require that any fix round adding or touching files updates the todo Modifies/Creates line and CHANGELOG (including an Added line for new helpers) in the same round; drop listed files left untouched.
