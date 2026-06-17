---
id: LRN-043
title: MCP tier-1 tools missing openWorldHint annotation causes client over-restriction
category: protocol
severity: high
source: redteam
date: 2026-06-17
---

## What happened
Tier-1 tools (high-privilege, open-ended tools such as web-search and code-exec)
were registered without the MCP `openWorldHint: true` annotation. MCP clients
that respect annotations use this hint to decide whether to present additional
safety confirmation UI. Without it, clients silently apply closed-world (narrow,
safe-list) assumptions, potentially blocking legitimate open-ended calls or
mis-classifying tool risk.

## Root cause
The MCP spec added `openWorldHint` as an optional annotation after the initial
tool registration pattern was established in the SDK. Existing `@tool` decorators
were not retroactively audited for new annotation fields, so the gap persisted
across SDK versions.

## Check
```
grep -rn 'openWorldHint' agent_sdk/ | grep -v test
# Every tool decorated with @tool that performs open-ended external actions
# (web fetch, code execution, shell commands) must have openWorldHint=True.
# Cross-reference: list all @tool-decorated functions and confirm each either
# has openWorldHint=True or is scoped to a closed list of known safe targets.
```

## Prevention
When planning new tool registrations or auditing existing ones, ensure that any
tool whose action set is unbounded (fetches arbitrary URLs, executes user-supplied
code, reads arbitrary file paths) is annotated with openWorldHint=True. Add a
lint rule or test that enumerates registered MCP tools and asserts openWorldHint
presence for tools matching an open-ended action pattern.
