---
id: LRN-241
title: Hand-listed text fallback silently drops wire fields added later
category: sdk
severity: high
source: redteam
date: 2026-09-03
---

## What happened
`FundPerformance.to_plain_text()` claims to "keep pace with every field the wire can
carry" but its `bits` list hand-enumerates fields and omits six of them (`calledDownPct`,
`dryPowder`, `dryPowderPct`, `distributed`, `remainingValue`,
`distributedPlusRemaining`). A card populated with only those fields renders the literal
`'fund performance (no data)'` for every text-only client, even though `wire()` carries
all the data and the A2UI console already renders four of the six.

## Root cause
The text fallback was written as a manual field list at creation time instead of being
derived from the model's field set, so it silently falls behind whenever `wire()` gains a
field.

## Check
`grep -n "to_plain_text" agent_sdk/models/content_types.py` and diff the field names
referenced in `bits` against `FundPerformance.model_fields`. Add a test constructing a
card with only the six currently-missing fields set and assert the result is not
`'fund performance (no data)'`.

## Prevention
When planning a `to_plain_text()`/text-fallback for any content type, require it to
iterate `self.model_fields` (or an equivalent single source of truth shared with
`wire()`) rather than a hand-written field list, so a field added later cannot silently
vanish from the text-only path.
