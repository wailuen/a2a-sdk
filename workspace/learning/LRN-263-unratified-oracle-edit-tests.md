---
id: LRN-263
title: Tests enforce frozen-contract edit while ratification flag False
category: testing
severity: high
source: redteam
date: 2026-10-09
---

## What happened
The three a2ui-advisor copies and DESIGN.md declared Profile v1.1 ratified, yet REVIEWS.md Round 11, CHANGELOG and the content_types.py docstring said PROPOSED. The ratified flag derived False, but _assert_metadata_row_state ran unconditionally and enforced the removal. This repeats Round 10 / LRN-234.

## Root cause
Tests asserting the edited state were not conditioned on the ratification flag, so the flag gated nothing.

## Check
Verify that `_assert_metadata_row_state` branches on ROUND_8_METADATA_ROW_REMOVAL_RATIFIED and fails when the row is removed while the flag is False.

## Prevention
When planning a frozen-contract edit, make its enforcing tests conditional on the ratification flag, and get user confirmation via AskUserQuestion before the edit lands.
