---
id: LRN-245
title: Re-resolving a label to a new value appends a second index entry, deadlocking $ref
category: sdk
severity: high
source: redteam
date: 2026-09-03
---

## What happened
`loop.py`'s resolved-value index dedups only on byte-identical (label, value)
pairs. Resolving the same (kind, label) to a *different* value appends a
second entry instead of replacing the first, so `$ref:<kind>:<label>` then
hits the multi-match branch and the correct raw value hits the ambiguity
branch — both reject with "use `$ref:<kind>:<label>`", the form the caller
already used. No strict/allow_raw_override/passthrough-limit escape covers
the `$ref` path, so the model burns to max_turns.

## Root cause
Index growth treats every resolution as an independent entry keyed on
(label, value) rather than treating (kind, label) as the identity and the
value as mutable — a refreshed identifier has no way to supersede its prior
resolution.

## Check
Resolve label L to v1, then re-resolve L to v2; assert `$ref:<kind>:L`
substitutes v2 and that raw v2 passes with no ambiguity/multi-match error.
`grep -n "index_entry_key" agent_sdk/agent/loop.py` — dedup key must be
(kind, label), last-write-wins, not (kind, label, value).

## Prevention
When planning any append-only resolved-value/index structure keyed by a
caller-nameable label, require last-write-wins semantics on (kind, label)
before append-only dedup — and require the ambiguity error message to never
recommend a disambiguation form the caller already supplied.
