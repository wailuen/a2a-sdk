---
id: LRN-319
title: Fix silently narrows a maintainer ruling
category: protocol
severity: high
source: redteam
date: 2026-10-13
---

## What happened
GH-159 ruled that non-text user parts are rejected before a run (no silent drop). The AG-UI fix checks only the newest user message, so earlier user messages still drop parts in `_fold_history`. A test pinned the drop as correct and the CHANGELOG overstated the fix. The narrowing was never recorded.

## Root cause
A sound reason (avoid bricking threads) narrowed the ruling without escalation or a recorded clarification.

## Check
Read `tests/test_gh159_reject_non_text_parts.py`: no test may assert behavior weaker than the ruling unless REVIEWS.md or the GH issue records the clarification. Confirm CHANGELOG and docs/protocols.md wording matches actual scope.

## Prevention
When a fix must be narrower than a ruling, plan an escalation step and record the clarification (LRN-308 class) before merging; docs must state the real scope.
