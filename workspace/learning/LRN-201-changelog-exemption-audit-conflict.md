---
id: LRN-201
title: CHANGELOG exemption claims need a spec citation, not prose
category: ops
severity: high
source: redteam
date: 2026-08-19
---

## What happened
GH-144's CHANGELOG entry claimed a wire break (terminal-task
message/stream error 404/-32001 -> 501/-32004) "satisfies" DESIGN.md §4.0's
exemption, citing no spec clause. REVIEWS.md:453's signed-off Round 10
audit already called the same finding an internal inconsistency,
"not a hard-MUST breach."

## Root cause
Exemption granted on the entry's own prose — no verified spec clause,
no cross-check against the existing audit verdict.

## Check
`grep -B2 -A6 "wire-shape conformance exemption" CHANGELOG.md` — confirm
each hit quotes a spec clause, then grep REVIEWS.md for the same finding;
flag any pair where the audit says "not a hard-MUST breach" while
CHANGELOG claims the exemption.

## Prevention
When an entry invokes DESIGN.md §4.0's exemption, require a direct
spec-clause quote plus a REVIEWS.md search reconciling any prior verdict.
