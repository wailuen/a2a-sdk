---
id: LRN-205
title: Two-condition exemption citation accepted without verifying either condition
category: ops
severity: high
source: redteam
date: 2026-08-19
---

## What happened
GH-144's CHANGELOG entry cited DESIGN.md §4.0's wire-shape exemption for a
stable-core error-code change (404/-32001 -> 501/-32004), asserting it
satisfies "both conditions." Neither holds: the changed file
(`agent_sdk/routes/a2a.py`) is not under `models/`, and the cited spec
table maps neither code to the affected method — REVIEWS.md's own signed
Round 10 audit already classified this exact finding as "not a hard-MUST
breach," contradicting the CHANGELOG's conformance claim.

## Root cause
The entry's own prose ("satisfies both conditions") was accepted as proof
instead of checking each condition against the landed diff's file path and
the quoted spec clause, and without cross-checking REVIEWS.md for a prior
audit verdict on the identical finding.

## Check
`grep -B2 -A6 "wire-shape conformance exemption" CHANGELOG.md` — for each
citation, confirm (a) the changed type/shape is defined under
`agent_sdk/models/` per the diff, and (b) a quoted external spec clause
mandates the new value. Then `grep -n "not a hard-MUST breach\|internal
cross-method inconsistency" REVIEWS.md` and confirm no contradiction with
the CHANGELOG's exemption claim.

## Prevention
When planning or reviewing a CHANGELOG entry invoking a multi-condition
exemption, require each condition verified independently against the
landed file path and quoted spec text — never the entry's own assertion —
and cross-check REVIEWS.md for any existing audit verdict on the same
finding before accepting the citation.
