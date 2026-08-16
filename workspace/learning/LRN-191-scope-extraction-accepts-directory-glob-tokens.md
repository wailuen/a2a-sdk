---
id: LRN-191
title: Wave scope extraction accepts directory/glob tokens
category: sdk
severity: high
source: redteam
date: 2026-08-15
---

## What happened
`extract_wave_scope()` accepts any backticked token on a Creates:/Modifies:
line, including dir/glob tokens from prose (e.g. `` `agent_sdk/` ``). The
archive gate matches scope by prefix, so one token "declares" every file
under that tree, disabling `offendingUndeclaredScope`. A pinned test
asserts `agent_sdk/` valid.

## Root cause
`_looks_like_path()` accepts any path-shaped token, not just real files
(extension, no trailing `/`, no `*`).

## Check
`grep -n "agent_sdk/\`" tests/test_wave_scope_extraction.py` — no dir/glob
should assert valid; a "(`x/` not a harness dir)" prose fixture must
exclude `x/` from `extract_wave_scope()`.

## Prevention
When planning scope/gate work, require `_looks_like_path()` (and JS
mirrors) reject tokens ending `/`, containing `*`, or lacking an
extension; offender rule must match paths exactly, never by prefix.
