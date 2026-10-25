---
id: LRN-541
title: Changelog names console static files by basename
category: ops
severity: high
source: redteam
date: 2026-10-25
---

## What happened
The GH-263 [Unreleased] bullet named `chat.js`, `retry.js`, `a2ui.js` by basename only. A grep for the full repo path over the block returned 0, failing the LRN-495 Check. New exports `abortableSleep` and `MAX_TOMBSTONES` were not tied to a path.

## Root cause
Console static files live under a nested dir, so authors shorten them to basenames in prose.

## Check
For each of chat.js, retry.js, a2ui.js: `grep -c 'agent_sdk/console/static/<file>' CHANGELOG.md` over the [Unreleased] block must be >= 1.

## Prevention
When planning a CHANGELOG entry touching console JS, require full paths `agent_sdk/console/static/<file>.js` and tie each new export to its path.
