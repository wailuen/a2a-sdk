---
id: LRN-339
title: Untrusted slot keeps ':' and forges a sibling id line
category: security
severity: high
source: redteam
date: 2026-10-13
---

## What happened
GH-167 moved EntityList names and summaries to safe_line_text, which keeps ':'. A hostile name or summary such as 'Acme id: 99999-99' rendered next to the real `id:` line, so the model saw two or three ids for one entity.

## Root cause
A labelled `id:` line is itself a k:v pair. Any untrusted slot in the same list item that keeps ':' can forge it. The test only matched lines starting with four spaces then 'id:'.

## Check
Verify a test puts a hostile id value in name and summary and asserts that value appears nowhere in the rendered text. Only the one real `    id:` line may carry an id.

## Prevention
When planning text renderers, ensure untrusted slots sharing a list item with a labelled id neutralise ':' (safe_cell_text) or sit after the id line. Forgery tests must search for the hostile value, not match a line prefix.
