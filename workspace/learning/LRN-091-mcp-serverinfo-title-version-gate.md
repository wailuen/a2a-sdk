---
id: LRN-091
title: MCP serverInfo.title version gate is conservatively correct — deliberate deviation from spec baseline
category: protocol
severity: critical
source: protocol-audit
date: 2026-06-19
---

## What happened
`mcp.py:73` sets `_TITLE_MIN_VERSION = "2025-11-25"`. The initialize handler
at lines 253–257 emits `serverInfo.title` only when the negotiated version
index is <= index of `"2025-11-25"` (index 0), which means title is omitted
under `2025-06-18` and `2025-03-26`. The spec (mcp-protocol.md §2) adds
`title` at `2025-06-18`, so the gate is one version higher than strictly
required. This is a PASS — GH-43 showed empirical rejection by Claude.ai at
the 2025-06-18 baseline, making the tighter gate the safer choice.

## Root cause
Omitting an optional field is spec-valid. The conservative gate is a
deliberate, documented deviation (code comment lines 69–73) driven by GH-43
live-session rejection, not an oversight.

## Check
```
grep -n "_TITLE_MIN_VERSION" agent_sdk/mcp.py
# Must show "2025-11-25". Any lower value requires GH-43 re-validation first.
```

## Prevention
When planning changes to `_TITLE_MIN_VERSION`, ensure GH-43 has been
re-tested live with a `2025-06-18`-negotiated session against Claude.ai before
lowering the gate. Do not lower speculatively. See also LRN-087 (same
finding, earlier source).
