---
id: LRN-145
title: Shared input_schema advertises loop-only $ref: affordance to MCP and agent-card surfaces
category: protocol
severity: high
source: redteam
date: 2026-09-02
---

## What happened
`ToolEntry.input_schema()` (registry.py:364) unconditionally appends a `$ref:<kind>` hint to `ReuseKind` field descriptions. That same schema is served on `routes/mcp.py` (`tools/list`) and `routes/agent_card.py` (`x-sdk.inputSchema`), but the substitution/validation gate for `$ref:` only exists in `loop.py`. An MCP client is told it may send `$ref:entity_id`, and the token then reaches the tool body verbatim as a literal string.

## Root cause
One shared `input_schema()` feeds three surfaces, but the model-facing affordance it describes is implemented on only one of them.

## Check
`grep -n '\$ref:' agent_sdk/routes/mcp.py agent_sdk/routes/agent_card.py` should show no hint text reaches those schemas. Add a regression test asserting MCP `tools/list` inputSchema for a `ReuseKind` tool contains no `$ref:` text; keep `tests/test_rt010_reuse_field_schema_hint.py` asserting the loop-facing schema does.

## Prevention
When planning a model-facing schema hint tied to a loop-only mechanism, require a surface-scoped schema projection (e.g. `include_reuse_hint` flag) rather than one shared builder — a schema served to MCP/agent-card must never promise a contract only `loop.py` honors.
