---
id: LRN-087
title: MCP serverInfo.title conservatively gated at 2025-11-25, not 2025-06-18 where spec adds it
category: protocol
severity: low
source: redteam
date: 2026-06-19
---

## What happened
`mcp.py:73` sets `_TITLE_MIN_VERSION = "2025-11-25"`. The initialize handler
emits `serverInfo.title` only when the negotiated protocol version index is <=
the index of `"2025-11-25"`. This means title is omitted under `2025-06-18`
and `2025-03-26`, even though the spec (mcp-protocol.md §2) added the field at
`2025-06-18`. GH-43 showed empirical rejection by Claude.ai at that version,
so the tighter gate was kept deliberately.

## Root cause
Omitting an optional field is spec-valid (mcp-protocol.md §2 "omitting an
optional field is spec-valid"), so the conservative gate is a deliberate
deviation, not a bug. The code comment at lines 69-73 documents this.

## Check
```
grep -n "_TITLE_MIN_VERSION" agent_sdk/mcp.py
# Must show "2025-11-25"; any lower value requires GH-43 re-validation first.
```

## Prevention
When planning changes to `_TITLE_MIN_VERSION`, ensure GH-43 has been
re-tested live with a `2025-06-18`-negotiated Claude.ai session before lowering
the gate to `"2025-06-18"`. Do not lower speculatively.
