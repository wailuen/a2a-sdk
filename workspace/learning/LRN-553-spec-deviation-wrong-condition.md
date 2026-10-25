---
id: LRN-553
title: Documented spec deviation names the wrong condition
category: protocol
severity: high
source: redteam
date: 2026-10-25
---

## What happened
`docs/protocols.md` says a tool with no `emits` returns an empty void result, as the GH-266 deviation. That case has no outputSchema, so it breaks no rule. The real deviation is a tool that declares `emits` (so advertises outputSchema) and returns None: it gives `isError:false` and no `structuredContent`, against MCP 2025-06-18.

## Root cause
The doc named the nearby case, not the exact condition that breaks the spec's MUST.

## Check
In docs/protocols.md, the "Deviation (GH-266)" sentence must contain `emits`, `outputSchema` and `structuredContent`; a doc test should pin those words.

## Prevention
When planning a spec-deviation doc, require the sentence to state the exact condition breaking the MUST, cite the spec version, and add a test pinning the condition words, not only "Deviation".
