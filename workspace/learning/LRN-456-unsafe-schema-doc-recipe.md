---
id: LRN-456
title: Documented tool-schema pattern not checked against model providers
category: protocol
severity: high
source: redteam
date: 2026-10-23
---

## What happened
docs/tools.md recommended a top-level `anyOf` in a tool's input schema ("ID A or ID B"). That schema reaches the model unchanged (Bedrock, OpenAI) and MCP clients via tools/list. Anthropic's API rejects top-level oneOf/allOf/anyOf with a 400.

## Root cause
The recipe was written on the premise that it "passes through" without checking provider limits.

## Check
Verify that `grep -n "anyOf\|oneOf\|allOf" docs/tools.md` shows no top-level combinator recipe for input schemas, and that no test pins one in a tier-1 inputSchema (e.g. tests/test_gh221_tools_list_titles.py).

## Prevention
When planning docs or tests for a JSON Schema pattern on tool inputs, ensure it is checked against every targeted model provider and MCP client; prefer optional fields plus an in-tool or model_validator check.
