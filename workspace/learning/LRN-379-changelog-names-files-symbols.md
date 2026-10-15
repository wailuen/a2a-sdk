---
id: LRN-379
title: Wave CHANGELOG omits changed files and new public symbols
category: ops
severity: high
source: redteam
date: 2026-10-15
---

## What happened
The [Unreleased] entry never named `routes/a2a.py`, `routes/ag_ui.py`, `console/static/a2ui.js` or `models/content_types.py`. It had no Added section for `safe_label_text`, `TITLE_TEXT_MAX_LEN`, `LINE_TEXT_CUT_MARKER` and `BASIC_CATALOG_COMPONENTS`, unlike the 0.13.0 entry.

## Root cause
The CHANGELOG was written per issue rather than reconciled against the diff.

## Check
For each file in `git diff --name-only -- agent_sdk`, `grep -c "<basename>" CHANGELOG.md` is >= 1. For each new top-level public name, grep that it appears under `### Added`.

## Prevention
When planning a wave, add a final CHANGELOG-reconcile step: name every changed `agent_sdk/**` file and add an Added line per new public symbol, marked stable API or internal helper.
