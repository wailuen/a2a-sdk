---
id: LRN-194
title: Identity-scoped error-code split lacks foreign-identity test
category: security
severity: high
source: redteam
date: 2026-08-19
---

## What happened
GH-144's missing-vs-terminal split in `message_stream` (a2a.py:333-342) must
stay downstream of the identity-scoped `store.get(task_id, identity)` at
:332, so a foreign identity's terminal task returns -32001/404, never
-32004/501. No test sends `message:stream` with another identity's terminal
taskId — `test_identity_binding_404_not_leak` covers GET /v1/tasks/{id}
only, a same-topic substitute of the class LRN-128 targets.

## Root cause
A new error-code branch on an identity-scoped lookup was treated as covered
by an adjacent, differently-scoped test instead of a test for the exact
branch.

## Check
`grep -n "def test_" tests/test_w017_gh51_multiturn.py`: a test completes a
task as identity A, POSTs `message:stream` with that taskId as identity B,
asserts `(404, -32001)` and NOT `(501, -32004)`.

## Prevention
When planning an error-code branch on an identity-scoped lookup, require a
todo naming the exact foreign-identity test proving lookup-before-branch
ordering — a same-topic test on another endpoint does not satisfy it.
