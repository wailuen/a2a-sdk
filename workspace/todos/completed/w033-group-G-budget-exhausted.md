wave: w033
group: G
date: 2026-07-14
round_count: 5
status: budget-exhausted

## Findings

### RT-001
- severity: low
- file: REVIEWS.md
- status: FIXED (2026-07-14)
- description: GH-117 edited REVIEWS.md specifically to remove doc/behavior drift, but the deferred-findings table in the same file still carries stale mcp.py line anchors: line 282 cites `routes/mcp.py:68-70` for `_TITLE_MIN_VERSION` (now at line 86; SUPPORTED_PROTOCOL_VERSIONS moved to line 74) and line 283 cites `routes/mcp.py:301-302` for the tools/list tool-level `title` emission (now at lines 329-330). Same LRN-108/LRN-090 doc-anchor-drift class the task was fixing.
- fix: Replaced both line-number anchors in REVIEWS.md's deferred-findings table with symbol names — `_TITLE_MIN_VERSION` (module-level constant) and `_handle_tools_list()`'s `tool["title"] = entry.title` block — so the citations are drift-proof against future line shifts.
- sdkCandidate: false

### RT-002
- severity: low
- file: agent_sdk/routes/mcp.py
- status: FIXED (2026-07-14)
- description: Dead store in the legacy `mcp_messages` handler (lines 831-832): after the `version is None` 400-gate, `if version is _HEADER_ABSENT: version = SUPPORTED_PROTOCOL_VERSIONS[-1]` reassigns `version`, but `version` is never read again — `_dispatch()` is version-agnostic. This makes the docstring/DESIGN §5.5 claim that the legacy path 'assumes 2025-03-26' aspirational: the assumed version is computed and discarded with no runtime effect (observable behavior — absent header -> allowed, dispatch proceeds — is unchanged and correct). Pre-existing (not in the group-G diff) but present in a scope file GH-117's transport-split docs describe.
- fix: Dropped the inert `if version is _HEADER_ABSENT: version = SUPPORTED_PROTOCOL_VERSIONS[-1]` reassignment in `mcp_messages()` and added a comment noting `_dispatch()` is version-agnostic, so the 2025-03-26 "assumption" is intentionally an admission-check stance only, not a threaded runtime value. `version` remains used for the `is None` 400-gate. Verified with `python3 -m pytest tests/ -k mcp` (124 passed) and the full suite (1053 passed).
- sdkCandidate: false

## Instruction

Fix remaining findings, then re-run /wave w033.
