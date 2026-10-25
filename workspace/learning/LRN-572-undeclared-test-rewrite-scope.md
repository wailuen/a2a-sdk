---
id: LRN-572
title: Test listed under Reads rewritten without declaring scope
category: testing
severity: high
source: redteam
date: 2026-10-25
---

## What happened
The G6 todo listed tests/test_mcp_gh77_absent_version_header.py under Reads as "must stay green unchanged", yet the work rewrote test_present_supported_version_header_echoed (init 2025-06-18 to 2025-03-26). The file was in no Creates/Modifies line and not in the GH-273 CHANGELOG Tests list.

## Root cause
A breaking ruling inverted behaviour that an existing test pinned, but the planner treated that test as read-only.

## Check
For each test file in `git diff --name-only -- tests`, grep the active todo for it on a Creates/Modifies line and grep CHANGELOG.md for it.

## Prevention
When a breaking ruling changes behaviour pinned by an existing test, move that test from Reads to Modifies at planning time and name it in the CHANGELOG Tests list with a one-line note.
