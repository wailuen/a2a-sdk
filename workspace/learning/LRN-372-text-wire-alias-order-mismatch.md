---
id: LRN-372
title: Text fallback alias order differs from wire serializer
category: sdk
severity: high
source: redteam
date: 2026-10-15
---

## What happened
`DocumentItem._wire_contract_keys` lets `modified` win over `last_modified`, but `DocumentList._body_text` used `d.last_modified or d.modified`. With both set, the TextPart and DataPart of one reply showed different dates (A2A artifact, MCP content vs structuredContent).

## Root cause
Alias folding was added to the serializer only; the hand-written text renderer kept its own precedence.

## Check
Test in tests/test_gh177_document_contract_keys.py: `DocumentItem(modified='M', last_modified='L')` in a DocumentList; assert the date in `to_plain_text()` equals `wire()['modified']`. grep `last_modified or` in agent_sdk/models/content_types.py and confirm no reversed order.

## Prevention
When planning a serializer that folds alias fields into contract keys, require the text fallback to use the same precedence (share one helper) and add a test setting both aliases that compares text to wire.
