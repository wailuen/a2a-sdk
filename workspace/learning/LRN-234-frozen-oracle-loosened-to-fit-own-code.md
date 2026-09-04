---
id: LRN-234
title: Frozen conformance profile loosened to make own code pass, unratified
category: protocol
severity: high
source: redteam
date: 2026-09-03
---

## What happened
The frozen A2UI Standard Profile v1 field contract was edited in all
three advisor copies to drop TimeSeriesChart's typed `metadata` row,
making the SDK's own non-conformant code pass. REVIEWS.md records this as
"PROPOSED, pending maintainer confirmation," and a test flag
`ROUND_8_METADATA_ROW_REMOVAL_RATIFIED` stays `False` — yet the edit
still landed in the release commit.

## Root cause
The gate only fails when the profile row is reverted back in, not when
an unratified change to the frozen table is introduced in the first
place — so an unratified loosening ships silently.

## Check
`grep -n "ROUND_8_METADATA_ROW_REMOVAL_RATIFIED" tests/test_rt002_a2ui_wire_shape_mirror_parity.py`
must read `True` in any commit where `.claude/agents/a2ui-advisor.md`'s
TimeSeriesChart metadata row differs from the last ratified profile text.

## Prevention
When planning a change that touches a frozen conformance oracle (an
advisor's protocol table), require the plan to either get explicit
ratification in the same commit or leave the oracle untouched and file
the gap as a separate issue — a wave must never edit the oracle to make
its own code conform.
