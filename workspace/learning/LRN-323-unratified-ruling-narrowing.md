---
id: LRN-323
title: Wave narrows maintainer ruling without checkable approval
category: protocol
severity: high
source: redteam
date: 2026-10-13
---

## What happened
GH-159 ruling said non-text user parts are rejected with no silent drop. The AG-UI code rejects only user messages after the last assistant message; earlier ones are dropped by `_fold_history`. REVIEWS.md Round 13 logged this as "pending ratification". Its "cannot brick a thread" claim is false: a kept rejected message fails every later run.

## Root cause
The wave narrowed a maintainer AC itself, and never tested the case where the client keeps the rejected input.

## Check
Grep REVIEWS.md Round 13 for a maintainer comment URL. Run `_validate([user(text+binary), user("hi again")])` and confirm the behaviour matches the ruling. Grep docs/protocols.md for "brick".

## Prevention
When planning, treat any wave-written narrowing of a maintainer AC as a proposal. Escalate it and record the comment URL before release. Test safety claims against clients that keep rejected input.
