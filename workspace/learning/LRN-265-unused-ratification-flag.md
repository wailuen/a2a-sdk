---
id: LRN-265
title: Ratification flag computed but never branched on by tests
category: testing
severity: high
source: redteam
date: 2026-10-09
---

## What happened
`ROUND_8_METADATA_ROW_REMOVAL_RATIFIED` is computed from REVIEWS.md (False today), but no test reads it. `_assert_metadata_row_state` always demands the ratified state and its messages say "RATIFIED", so the gate enforces policy that is not ratified.

## Root cause
The flag was added as a gate but assertions were never made conditional on it, so it is decoration.

## Check
grep -n "ROUND_8_METADATA_ROW_REMOVAL_RATIFIED" tests/test_rt002_a2ui_wire_shape_mirror_parity.py tests/test_round8_metadata_ratification_gate.py and confirm it appears inside an `if`/assert in `_assert_metadata_row_state` and `test_all_three_a2ui_advisor_copies_carry_the_ratified_metadata_note`.

## Prevention
When planning a ratification or feature-flag gate, require that every test enforcing the gated state branches on the flag (False: pre-ratification state or "pending ratification" failure; True: ratified state), or drop the flag.
