---
id: LRN-224
title: SI regression test hit one surface, not the Reuses-mandated set
category: testing
severity: high
source: redteam
date: 2026-08-15
---

## What happened
GH-135's SI-2 AC required a test proving a validator's secret-interpolating
error never reaches the model or wire, with `Reuses: C-010` mandating parity
across loop/MCP/admin/commitments. The landed test covers only loop.py, with
non-secret values and no MCP/admin case — the gap that let RT-001's log
leak ship.

## Root cause
The AC's `Reuses: C-NNN` surface list and literal attack-input requirement
were both assumed satisfied by one same-topic test on one surface, never
independently checked.

## Check
For an SI-tagged AC with `Reuses: C-NNN`, grep the named test file for one
test per surface in C-NNN's registry entry, each using a secret-looking
value: `grep -n "def test_" tests/test_gh135_tool_body_validation_error.py`
— confirm MCP and admin cases exist beside loop.py, asserting the token is
absent from wire output and caplog.

## Prevention
When an SI-tagged AC carries `Reuses: C-NNN`, the todo must enumerate every
surface in that registry entry and name a per-surface test using the AC's
literal attack input; gate phase-redteam on verifying all exist.
