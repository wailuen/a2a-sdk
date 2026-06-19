---
id: LRN-094
title: Agent card advertises tools absent from MCP tools/list
category: protocol
severity: high
source: protocol-audit
date: 2026-06-15
---

## What happened
`build_agent_card()` populates the card's skills list via `registry.all()`, which includes both tier-1 and tier-2 tools. The MCP `tools/list` handler uses `registry.tier1()`, and `_handle_tools_call` rejects tier-2 tool calls with a `-32601` method-not-found error. An MCP client that discovers the agent via the card and attempts to call a tier-2 skill receives a confusing 404-equivalent error with no prior indication that the tool is unavailable on the MCP surface.

## Root cause
The card build path and the MCP dispatch path use different registry filters (`all()` vs `tier1()`), and the `x-sdk.tier` annotation is SDK-internal — generic MCP clients will not read it as a surface restriction signal.

## Check
```
grep -n "registry\.all()" src/agent_sdk/agent_card.py
grep -n "registry\.tier1()" src/agent_sdk/mcp.py
```
Confirm that `build_agent_card` does NOT call `registry.all()` (or if it does, every tier-2 tool in the result carries a machine-readable `surfaces` restriction). Also verify: `pytest -k "card_skills_match_mcp_tools"` passes.

## Prevention
When planning any feature that adds a new tool tier or surface filter, ensure the agent-card build path is updated in the same unit of work to match the MCP dispatch filter. A test asserting that every unrestricted card skill has a matching entry in MCP `tools/list` must be added or remain green.
