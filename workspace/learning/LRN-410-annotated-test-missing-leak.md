---
id: LRN-410
title: Annotated tests missing and leak checks run outside the app
category: testing
severity: high
source: redteam
date: 2026-10-17
---

## What happened
The GH-185 todo's SI-5 annotation required a test that a rejected request leaves no bound identity. None existed. Isolation checks (`assert current_identity() is None`) ran in the test's own context, which cannot see values bound in the app's tasks, so they passed even without unbinding. AG-UI resume and A2A message:stream resume were untested.

## Root cause
Annotations saying "add a test" were not treated as acceptance conditions, and ContextVar leak checks observed the wrong context.

## Check
For each SI annotation in the todo, grep tests/ for a named test and confirm it exists. Confirm a spy on `bind_identity` asserts zero calls on a 401 for each transport. Confirm sequential alice then bob calls assert the tool saw only bob.

## Prevention
When planning, turn every "add a test" annotation into a named test task per transport. Leak checks must record the value from inside the tool or adapter, not from the test's context.
