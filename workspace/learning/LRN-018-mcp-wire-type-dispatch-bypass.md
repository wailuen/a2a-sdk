---
id: LRN-018
title: MCP route bypasses per-type wire dispatch, emitting raw field dict instead of markdown string
category: protocol
severity: high
source: redteam
date: 2026-06-15
---

## What happened
`_handle_tools_call` in `agent_sdk/routes/mcp.py` calls `artifact.wire()` unconditionally for all `ContentModel` subclasses. For `MarketBriefing`, `wire()` returns the raw Pydantic field dump (title, as_of, prose, sections) as a dict, not the markdown string required by DESIGN §4.3. The translator (`translator.py:90`) already guards `isinstance(artifact, MarketBriefing)` and calls `to_markdown()` correctly, so the two code paths diverge silently.

## Root cause
The MCP route was written without awareness that `MarketBriefing` is the sole `ContentModel` type whose wire representation is a string rather than a dict. No isinstance guard was added to mcp.py when the `MarketBriefing.to_markdown()` contract was established.

## Check
```
grep -n "artifact.wire()" agent_sdk/routes/mcp.py
# Must not appear alone — must be guarded: to_markdown() if isinstance(artifact, MarketBriefing) else artifact.wire()
```
Run: `pytest tests/ -k "market_briefing and mcp"` and assert `structuredContent` is a `str`, not a `dict`.

## Prevention
Any new per-type wire-format rule in DESIGN §4 must be applied to ALL emission sites (routes/mcp.py, routes/a2a.py, translator.py) atomically. Add a cross-site grep assertion in the redteam checklist: every `artifact.wire()` call site must carry the MarketBriefing isinstance guard.
