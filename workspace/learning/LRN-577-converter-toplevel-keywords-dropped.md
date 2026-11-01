---
id: LRN-577
title: Schema converter ignores unknown top-level keywords
category: sdk
severity: high
source: redteam
date: 2026-11-01
---

## What happened
`convert_schema` checked only `$ref`/`$defs`/`additionalProperties` at the top level and silently dropped anyOf, oneOf, allOf, if/then/else, minProperties, dependentRequired and not. `validate_content(converted, {})` returned True, so resume_handler got content the response_schema forbids.

## Root cause
Top-level handling is a deny-list of a few known keys rather than an allow-list, so every other keyword is discarded.

## Check
Verify tests assert `convert_schema` returns None for top-level anyOf, allOf, minProperties and dependentRequired. Grep the `$ref` / `$defs` check in agent_sdk/routes/mcp_elicitation.py and confirm a top-level key allow-list (type, properties, required, additionalProperties, title, description).

## Prevention
When planning schema converters, require allow-listing keys at every level including the root. Any unknown key returns "not convertible", with one test per keyword.
