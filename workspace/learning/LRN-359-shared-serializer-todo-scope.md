---
id: LRN-359
title: Shared serializer edits must be declared in todo scope
category: ops
severity: high
source: redteam
date: 2026-10-15
---

## What happened
The w049 fix changed `runner.py` (build_artifact), `common/sse.py` and `routes/mcp.py`, plus three test files. None were listed in any todo Modifies: line. The scope scan never saw them, so the sse.py regression got past review.

## Root cause
A hardening of a shared serializer was treated as a model-level fix, not a transport change.

## Check
Verify every file in `git diff --name-only` appears in a todo Creates:/Modifies: line: `grep -n "Modifies:" workspace/todos/active/*.md`.

## Prevention
When a fix touches a shared serializer (sse_data, MCP writer, build_artifact), list that file and all its caller files in the todo Modifies: lines, and name the files in the CHANGELOG entry.
