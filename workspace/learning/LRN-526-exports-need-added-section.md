---
id: LRN-526
title: New exports mentioned only under Fixed, no Added section
category: ops
severity: high
source: redteam
date: 2026-10-25
---

## What happened
G1 added exports to `agent_sdk/console/static/a2ui.js` and a `signal` argument to `postSse` in `agent_sdk/console/static/api.js`. [Unreleased] had no `### Added` section; they appeared only inside GH-254/GH-255 `### Fixed` bullets, failing LRN-379.

## Root cause
New API surface was treated as part of a fix and not recorded as an addition.

## Check
Confirm `awk '/^## \[Unreleased\]/,/^## \[[0-9]/' CHANGELOG.md | grep -c '^### Added'` is at least 1 and each new export has its own line there, marked stable or internal.

## Prevention
When a group adds any export or argument, console JS included, plan a dedicated `### Added` line per item with file path and stable/console-internal (provisional) marker. A mention under Fixed does not count.
