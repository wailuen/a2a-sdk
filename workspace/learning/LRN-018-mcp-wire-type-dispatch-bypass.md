---
id: LRN-018
title: MCP route bypasses per-type wire dispatch, emitting raw field dict instead of markdown string
category: protocol
severity: high
source: redteam
date: 2026-06-15
---

## What happened
`_handle_tools_call` in `agent_sdk/routes/mcp.py` originally called `artifact.wire()` unconditionally for all `ContentModel` subclasses. For `MarketBriefing`, `wire()` returns the raw Pydantic field dump (title, as_of, prose, sections) as a dict, not the markdown string required by DESIGN §4.3. The translator (`agent_sdk/a2ui/translator.py:108`) already guarded `isinstance(artifact, MarketBriefing)` and called `to_markdown()` correctly, so the two code paths diverged silently. The initial fix added the same `isinstance(artifact, MarketBriefing)` guard to `mcp.py`, at which point `structuredContent` for `MarketBriefing` was a bare markdown **string** — matching the AG-UI/A2A shape exactly.

**GH-105 update (ratified):** MCP's 2025-06-18 spec requires `Tool.outputSchema` and `CallToolResult.structuredContent` to always be JSON objects, never bare strings or scalars. This reversed the bare-string shape *on the MCP surface only*: `structuredContent` for `MarketBriefing` is now `{"markdown": <str>}` (`agent_sdk/routes/mcp.py:425-432`), and `outputSchema` advertises the matching object schema `{"type": "object", "properties": {"markdown": {"type": "string"}}, "required": ["markdown"]}` (`agent_sdk/agent/registry.py:264-269`). The AG-UI/A2A wire contract in `translator.py:108` is untouched — it still emits the bare `to_markdown()` string there. The surviving invariant is the *dispatch guard itself*, not the specific value shape: no MCP emission site may call `artifact.wire()` (or advertise `emits.model_json_schema()`) for `MarketBriefing` without first checking `isinstance(artifact, MarketBriefing)` / `issubclass(emits, MarketBriefing)` — only the guarded value's shape changed, from bare string to `{"markdown": str}`.

## Root cause
The MCP route was written without awareness that `MarketBriefing` is the sole `ContentModel` type whose wire representation is not the plain field dict. No isinstance guard was present in `mcp.py` when the `MarketBriefing.to_markdown()` contract was established. (Historical — the guard has since landed; see Check.)

## Check
```bash
grep -n "artifact.wire()" agent_sdk/routes/mcp.py
# Must not appear unconditionally — must be guarded, e.g.:
#   {"markdown": artifact.to_markdown()} if isinstance(artifact, MarketBriefing) else artifact.wire()
```
Run: `.venv/bin/pytest -q tests/test_mcp_conformance_w9.py -k test_sc_c7_market_briefing_structured_content_is_object`
and assert `structuredContent` is a JSON **object** `{"markdown": <str>}` (GH-105 MCP
object-only requirement) — NOT a bare string, and NOT the raw field dict. On the
AG-UI/A2A path (`translator.py:108`, covered by `tests/test_a2ui_wire.py`), the value
stays a bare markdown string — do not conflate the two surfaces or treat one shape as
authoritative for the other.

## Prevention
Any new per-type wire-format rule in DESIGN §4 must be applied to ALL emission sites (routes/mcp.py, routes/a2a.py, translator.py, registry.py's `output_schema()`) atomically — but the *shape* of the rule may legitimately differ per surface when the surface's own spec demands it (e.g. GH-105's MCP object-only requirement). Add a cross-site grep assertion in the redteam checklist: every `artifact.wire()` call site (and every `outputSchema`/schema-advertisement site) must carry the `MarketBriefing` isinstance/issubclass guard, even when the guarded value's shape differs between surfaces. When a ratified wave changes what the guarded value looks like, update this Check clause and narrative in the same wave (see LRN-066) — a stale wire-shape assertion left behind will flag the new, correct code as a regression.
