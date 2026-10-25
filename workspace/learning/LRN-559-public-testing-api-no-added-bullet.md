---
id: LRN-559
title: New exported testing API lacks Added bullet and file paths
category: sdk
severity: high
source: redteam
date: 2026-10-25
---

## What happened
GH-264 added the public keyword `ChatDriver(card=...)` and function `fetch_agent_card`. Both were mentioned only inside a `### Changed` bullet. No `### Added` bullet existed, and `[Unreleased]` never named `agent_sdk/testing/chat.py` or `docs/testing.md`. LRN-433, LRN-202 and LRN-443 failed.

## Root cause
Prose in a group bullet was treated as enough; new public symbols and changed file paths were not tracked separately.

## Check
Verify `[Unreleased]` has a `### Added` bullet for each new name in `agent_sdk/testing/__all__` or its parameters, and grep -c "chat.py" and "testing.md" in `[Unreleased]` return at least 1 when those files changed.

## Prevention
When planning changes to an exported surface, require an `### Added` bullet per new keyword or function, and list every changed file path in the CHANGELOG entry.
