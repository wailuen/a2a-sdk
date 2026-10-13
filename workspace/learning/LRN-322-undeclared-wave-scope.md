---
id: LRN-322
title: Production files changed outside todo scope and CHANGELOG
category: ops
severity: high
source: redteam
date: 2026-10-13
---

## What happened
GH-156 added helper `safe_id_text` and `_ID_NEUTRALISE` to `agent_sdk/common/redact.py`, a file no todo listed. CHANGELOG omitted the helper and the `FundPerformance.pb_id` change from `_sanitize_cell` to `_safe_id` (`=`, `:`, `,`, `@` now pass verbatim). The review scope left out redact.py, its test and components/README.md.

## Root cause
Scope was taken from the todo's Creates/Modifies list. A "Reuses: add a sibling in X" note was treated as enough.

## Check
Run `git diff --name-only` for the wave. Confirm every `agent_sdk/**` file appears in a todo's Creates/Modifies line and is named in the CHANGELOG entry.

## Prevention
When planning, list every production file (including shared helpers like redact.py) in Creates/Modifies. A Reuses note is not a scope declaration. Require a CHANGELOG line for each new helper and each behaviour change.
