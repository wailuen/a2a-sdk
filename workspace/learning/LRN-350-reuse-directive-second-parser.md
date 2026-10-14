---
id: LRN-350
title: Reuses directive ignored, second test parser written
category: testing
severity: high
source: redteam
date: 2026-10-14
---

## What happened
The todo said `Reuses: C-020` (extend the compact-schema parser in tests/test_a2ui_wire.py and import it). tests/test_gh170_profile_required_keys.py defined its own tokenizer/parser and imported nothing from it. Two files listed under Modifies were left untouched, so two parsers can now drift.

## Root cause
The implementer wrote a new, more capable helper instead of extending the registered one.

## Check
Grep `_parse_schema|_TOKEN` in tests/: it must be defined once (tests/_compact_schema.py) and imported by test_a2ui_wire.py and test_gh170_profile_required_keys.py. Confirm every file in the todo's Modifies shows in `git diff --stat`.

## Prevention
When a todo says `Reuses: C-NNN` for a helper, require the new test to import the extended helper, and name the shared module. No new parser in the new file. Redteam must diff Modifies against actual changes.
