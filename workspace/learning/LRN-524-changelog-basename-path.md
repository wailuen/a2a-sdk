---
id: LRN-524
title: CHANGELOG bullet names changed file by basename only
category: ops
severity: high
source: redteam
date: 2026-10-25
---

## What happened
The GH-254 bullet mentioned `postSse` in `api.js` by basename. `grep -c agent_sdk/console/static/api.js` over [Unreleased] returned 0, failing LRN-503/LRN-491 and the rule to name every changed `agent_sdk/` file by repo path.

## Root cause
Console static JS was treated as informal and cited by short name.

## Check
For each changed `agent_sdk/` file, run `grep -c 'agent_sdk/console/static/api.js' CHANGELOG.md` (full path) and require at least 1.

## Prevention
When planning CHANGELOG items, require every changed agent_sdk file, console static JS included, to be cited by its full repo path. Verify with grep on the full path, not the basename.
