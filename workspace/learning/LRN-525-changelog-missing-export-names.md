---
id: LRN-525
title: New exports not named in CHANGELOG bullet
category: ops
severity: high
source: redteam
date: 2026-10-25
---

## What happened
GH-255 added exports to `agent_sdk/console/static/a2ui.js` (`MAX_TEXT`, `MAX_LONG_TEXT`, `MAX_PROSE`, `MAX_RAW`, `MAX_SECTIONS`, `MAX_CELLS`, plus `capRows`/`moreNote`/`clip`). The bullet named only three; the six constants appeared nowhere, failing LRN-503.

## Root cause
The bullet was written from the prose fix, not from a diff of `export` lines.

## Check
`git diff -U0 -- agent_sdk | grep '^+export'`; for each name, `grep -c '<name>' CHANGELOG.md` must be at least 1 within [Unreleased].

## Prevention
When planning, make the CHANGELOG todo list every new `export` (console JS included) by name and value, derived from the diff, and mark console-internal ones provisional.
