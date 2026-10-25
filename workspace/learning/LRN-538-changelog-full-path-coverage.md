---
id: LRN-538
title: Changelog must name every changed file by full path
category: ops
severity: high
source: redteam
date: 2026-10-25
---

## What happened
[Unreleased] omitted full repo paths for changed source files (agent_sdk/a2ui/catalog.py, agent_sdk/models/content_types.py, agent_sdk/common/admission.py) and gave only the bare name `gate.py` for the action gate. Seven changed test files were also not listed.

## Root cause
Bullets were written per issue from memory, not checked against `git diff --name-only`.

## Check
Verify that every path from `git diff --name-only -- agent_sdk tests` appears verbatim in the [Unreleased] block of CHANGELOG.md. A bare basename does not count (LRN-491/LRN-505).

## Prevention
When planning a release, generate the changed-file list from git diff and assign each file to a bullet's `Changed:` or `Tests:` list by full path. Include tests edited to absorb behavior changes.
