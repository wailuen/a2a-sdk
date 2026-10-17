---
id: LRN-415
title: JS block replaced by text edit left file unparseable
category: testing
severity: critical
source: redteam
date: 2026-10-17
---

## What happened
The GH-191 edit to `agent_sdk/console/static/chat.js` left part of the old stream-drop handler after the new `await processStream();`. The file failed `node --check` (`Unexpected token 'else'`, line ~658). console.js imports chat.js statically, so the whole admin console failed to load. All G1 tests still passed.

## Root cause
A block was replaced by text substitution and nothing parsed the result. Tests only matched strings in the JS source.

## Check
Copy each `agent_sdk/console/static/*.js` to a temp `.mjs` and run `node --check` on it; all must exit 0. Skip only when node is absent.

## Prevention
When planning any todo that edits console JS, add an AC: every `console/static/*.js` passes `node --check` before the todo is marked done.
