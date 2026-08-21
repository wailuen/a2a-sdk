---
id: LRN-199
title: Wire error/status code change ships with zero CHANGELOG entry
category: ops
severity: high
source: redteam
date: 2026-08-19
---

## What happened
GH-144 changed `/v1/message:stream`'s terminal-task response from 404
`-32001` to 501 `-32004` (stable-core, DESIGN.md §4.0), and GH-143 added a
429 to `GET /mcp` — but `CHANGELOG.md` had no `## [Unreleased]` section;
its head was the already-tagged `## [0.6.0]`. Neither wire change was
documented anywhere in the file.

## Root cause
Changelog authoring is habitual per-fix, not a checked gate: no
wave-closing step verifies that a diff changing a public route's emitted
error code/HTTP status has a matching typed CHANGELOG heading before the
fix is called done.

## Check
`grep -n '## \[Unreleased\]' CHANGELOG.md` after any commit past
`git tag --contains HEAD` — if absent while the diff changes a status/code
in `agent_sdk/routes/*.py` or `agent_sdk/models/errors.py`, it's
undocumented. Tell: the wave edits `harness/skills/**/*.md` or
`workspace/learning/*.md` to match the new code, but CHANGELOG.md doesn't.

## Prevention
When planning a change to any A2A/MCP error code or HTTP status on a
public route, add a CHANGELOG.md task to that unit's Modifies: list —
open/extend `## [Unreleased]`, classify per DESIGN.md §4.0's exemption
test, name the route + old/new code, and include a Migration callout.
