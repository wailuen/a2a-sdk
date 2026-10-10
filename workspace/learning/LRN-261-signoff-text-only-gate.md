---
id: LRN-261
title: Ratification gate keyed to bare SIGNED OFF text
category: testing
severity: high
source: redteam
date: 2026-10-09
---

## What happened
REVIEWS.md Round 11 header said SIGNED OFF while its body said PENDING. The test flag was hard-coded True, and the docstring and CHANGELOG stated sign-off as fact. The gate test only looked for the text "SIGNED OFF", so it passed.

## Root cause
The gate was tied to a bare phrase, not to a checkable sign-off reference, and the flag was hard-coded.

## Check
Verify that `grep -n "ROUND_8_METADATA_ROW_REMOVAL_RATIFIED" tests/` shows a derived value (not a literal True), and that a test fails while Round 11 contains PENDING.

## Prevention
When planning a ratification gate, require the flag to derive from a checkable reference (comment URL or session ID), and require /sdk-release to block on PENDING entries. Docs and CHANGELOG must not run ahead of REVIEWS.md.
