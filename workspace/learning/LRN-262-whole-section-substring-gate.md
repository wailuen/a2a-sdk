---
id: LRN-262
title: Sign-off gate substring-matches whole section, never flips
category: testing
severity: high
source: redteam
date: 2026-10-09
---

## What happened
round_11_checkable_reference_recorded() returned False if "PROPOSED" or "PENDING" appeared anywhere in the Round 11 section. History and closing paragraphs contain those words, so the flag stayed False even after the documented sign-off edit. The release gate would then block every release.

## Root cause
The parser searched free text instead of the dedicated status line.

## Check
Verify that a test applies the documented sign-off edit to the real REVIEWS.md and asserts the flag is True. Verify the parser anchors on the status line (e.g. `^\*\*(SIGNED OFF|PROPOSED)\*\*`).

## Prevention
When planning any text-derived gate, parse only a dedicated status or reference line, and require a test that runs the success transition end to end, not only the failing state.
