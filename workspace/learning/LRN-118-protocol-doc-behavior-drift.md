---
id: LRN-118
title: DESIGN.md MCP version-header rule stale after transport split
category: protocol
severity: high
source: protocol-audit
date: 2026-07-14
---

## What happened
DESIGN.md §5.5 states one rule ("absent → assume 2025-03-26"). GH-77 split this by transport: Streamable HTTP (`mcp_post`) 400ed on absent header (non-init). GH-200 later reversed that: Streamable HTTP now dispatches on absent, using the session's negotiated version (else 2025-03-26); Legacy SSE (`mcp_messages`) assumes 2025-03-26. Commit bbfe353 fixed mcp.py's docstring, not DESIGN.md/REVIEWS.md.

## Root cause
The fix updated the nearest doc (docstring), leaving DESIGN.md out of scope, though it — not the docstring — is ground truth for contributors/agent-stack-check.

## Check
`grep -n "assume 2025-03-26" DESIGN.md` — must match the GH-200 rule: Streamable HTTP absent → session's negotiated version (else 2025-03-26), present-but-unrecognized → 400; no doc may claim Streamable HTTP 400s on absent. Cross-check `tests/test_mcp_gh77_absent_version_header.py`.

## Prevention
When a protocol change's behavior differs by transport, require DESIGN.md (and REVIEWS.md) updated in the SAME commit as the code/docstring fix.
