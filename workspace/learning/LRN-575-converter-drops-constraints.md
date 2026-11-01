---
id: LRN-575
title: Schema converter silently drops unsupported property constraints
category: sdk
severity: high
source: redteam
date: 2026-11-01
---

## What happened
`convert_schema` in the MCP elicitation module dropped integer/number `enum`, string `const`, `pattern`, `multipleOf` and `exclusiveMinimum/Maximum` instead of returning "not convertible". `validate_content` then accepted values the tool's own response_schema forbids (e.g. lvl=99, code='zz') and passed them to resume_handler.

## Root cause
`_convert_property` copies known keys per type but has no allow-list, so unknown keywords vanish without refusal.

## Check
Verify tests in tests/test_gh224_mcp_elicitation.py assert `convert_schema` returns None for Literal['yes'], Literal[1,2,3], Field(pattern=...), Field(multiple_of=...), and exclusive bounds. Grep `_convert_property` in agent_sdk/routes/mcp_elicitation.py for a per-kind allow-list.

## Prevention
When planning any schema down-converter, require a per-type keyword allow-list: any keyword outside it returns "not convertible". Require a negative test per dropped keyword class.
