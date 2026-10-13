---
id: LRN-312
title: Cell sanitizer used on identifiers corrupts copy-back ids
category: sdk
severity: high
source: redteam
date: 2026-10-13
---

## What happened
GH-156 `_safe_id` ran ids through `_sanitize_cell` (C-007), which rewrites `=`, `:` and `,` to fullwidth forms. Graph ids like `AAMk...AAA=` and URNs like `urn:li:org:1` came out wrong in the MCP text fallback, so a text-only client could not use them in a follow-up call. Tests used only hyphenated ids and passed.

## Root cause
A delimiter-neutralising cell sanitizer was reused for identifiers that must round-trip byte-exact.

## Check
Verify `safe_id_text` exists in `agent_sdk/common/redact.py` and `_safe_id` uses it. Run a test asserting `AAMkAGI2TAAA=` and `urn:li:organization:1` appear verbatim in `to_plain_text()` and MCP `content[0].text`.

## Prevention
When planning text rendering of ids a model will copy back, require an id-preserving sanitizer (strip controls, whitespace, `()[]<>|` only; keep `= + / : , . _ - ! ~ @`). Require tests with real upstream id alphabets (base64 padding, URN colons).
