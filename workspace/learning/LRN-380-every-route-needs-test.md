---
id: LRN-380
title: SI AC naming "every route" needs a test per route
category: testing
severity: high
source: redteam
date: 2026-10-15
---

## What happened
GH-179 item 9 required the strict-serialize helper on every non-stream A2A route plus a test. Only tasks/get and message:send (task path) were tested. tasks/list, tasks/cancel, the resume branch and the sync_reply bare-Message branch had no non-finite test.

## Root cause
Tests were written for the routes the headline AC named, not for each route the SI-tagged "every route" note covered.

## Check
In tests/test_gh179_conformance_drift.py, verify a test per route (tasks/list, tasks/cancel, resume, sync_reply) that injects NaN and asserts HTTP 502, body == {error:{code:-32006,message:'invalid agent response'}}, and no nan/inf text in body or caplog.

## Prevention
When planning an AC that says "every route/writer/branch", enumerate the routes in the todo and require one test per entry (LRN-128/LRN-364).
