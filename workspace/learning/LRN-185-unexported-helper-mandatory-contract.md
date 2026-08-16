---
id: LRN-185
title: Mandatory third-party sanitiser contract points at an unexported private helper
category: security
severity: high
source: redteam
date: 2026-08-15
---

## What happened
GH-130's cell sanitiser (`_sanitize_cell`/`_sanitize_block`) stayed module-private,
unexported from `agent_sdk/__init__.py`. The contract is declared MANDATORY for
third-party cards in 3 places (docstring, docs/content-types.md, DESIGN.md §4.0) —
none resolve to a callable public symbol; DESIGN.md even cites the wrong helper
(`safe_error_text`, no separator neutralisation).

## Root cause
Mandatory-contract wording was added without verifying a public API satisfies it, so
authors are told to hand-build their own separator alphabet — the divergent-copy
failure C-007 existed to prevent (LRN-141).

## Check
`grep -n "^def _sanitize_cell" agent_sdk/models/content_types.py` +
`grep -n "safe_cell_text" agent_sdk/__init__.py` — sanitiser must be exported
publicly and DESIGN.md §4.0 must cite that symbol, not `safe_error_text`.

## Prevention
When a doc/spec declares a sanitisation contract MANDATORY for third-party code,
add a public-API-existence check to the same AC: confirm every cited helper is
exported and correctly named before closing the contract as "documented."
