---
id: LRN-149
title: Cross-turn reuse index needs transport history fold with tool results
category: protocol
severity: high
source: redteam
date: 2026-09-02
---

## What happened
GH-148's reuse/mismatch gate rides `resolved_for_kind`, built by scanning prior
`toolResult` blocks in `messages`. On AG-UI, `_fold_history` rebuilds resent messages
from `type == "text"` parts only, and each run starts a fresh `TaskRecord` — so
`scan_resolved()` returns empty every run and the gate silently passes through, even
though docs and a design paragraph claimed A2A/AG-UI parity.

## Root cause
The mechanism assumes every transport's message-replay preserves tool-result blocks; no
one verified AG-UI's fold actually does before asserting parity.

## Check
`grep -n "type == \"text\"" agent_sdk/routes/ag_ui.py` around `_fold_history` — confirm
whether `toolResult`-bearing blocks are preserved. Run
`test_ag_ui_fold_drops_resolved_marker_across_runs` and confirm the gap is either closed
or explicitly documented as a known limitation (CHANGELOG + GH-148), not silently claimed
fixed.

## Prevention
When planning a cross-turn mechanism keyed on message-transcript replay, require the
plan to verify each supported transport's history-fold preserves the specific block
types the mechanism reads (not just text) before claiming transport parity — and if a
transport can't carry it, log/document the gap instead of shipping silent passthrough.
