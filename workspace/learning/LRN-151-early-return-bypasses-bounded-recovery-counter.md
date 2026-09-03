---
id: LRN-151
title: Early return above a bounded-recovery counter exempts that rejection path from the guarantee
category: sdk
severity: high
source: redteam
date: 2026-09-02
---

## What happened
`resolve_reuse_fields` (agent_sdk/agent/reuse.py:676) returns the "value is ambiguous"
error when multiple resolutions of a kind are on record, but the `reject_counts`
increment/threshold/forced-passthrough logic lives only in the later single-resolution
mismatch branch (691-704). With 2+ resolutions on record, a strict field rejects a
genuinely-new raw value forever — six consecutive calls all returned the ambiguity
error, `reject_counts` stayed `{}`. This contradicts the docstring's "unconditional"
bounded-recovery claim, and the suggested `$ref:<kind>:<label>` recovery path is itself
rejected by RT-A-007 for any label not already on record, so the model loops with no
in-band escape until max_turns.

## Root cause
The bounded-recovery counter was wired into only one of the function's rejection
`return` statements instead of every rejection exit, so a docstring-advertised
unconditional guarantee silently excludes the most common multi-entity path.

## Check
grep for `reject_counts` in `agent_sdk/agent/reuse.py` and confirm the increment/
threshold block runs before or wraps EVERY early `return` that rejects a raw value
(ambiguity branch included, not just the single-resolution mismatch branch). Add/keep
a regression test asserting bounded recovery fires with 2+ resolutions of a kind on
record, mirroring the existing single-resolution test.

## Prevention
When a function advertises an unconditional liveness/bounded-retry guarantee across
multiple rejection reasons, planner must require the counter/threshold check be
hoisted above (or invoked by) every rejecting `return` in that function — never
verify only the branch exercised by the original test case.
