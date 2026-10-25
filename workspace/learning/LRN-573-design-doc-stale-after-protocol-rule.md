---
id: LRN-573
title: DESIGN.md left stale after protocol rule change
category: protocol
severity: high
source: redteam
date: 2026-10-25
---

## What happened
GH-273 added a rule: a valid MCP-Protocol-Version differing from the session's version gets 400, and early exits echo the owned session's version. DESIGN.md section 5.5, the main description of per-transport version checks, still said only a present-but-unrecognized version gets 400.

## Root cause
The G6 todo's Creates list omitted DESIGN.md, so the design doc was never updated with the code.

## Check
grep -n "session's negotiated version\|GH-273" DESIGN.md must match inside section 5.5 whenever agent_sdk/routes/mcp.py changes version-header handling.

## Prevention
When planning any change to MCP version-header handling, list DESIGN.md (section 5.5 transport-split paragraph) in the todo's Creates/Modifies line and state whether GET/DELETE /mcp apply the rule.
