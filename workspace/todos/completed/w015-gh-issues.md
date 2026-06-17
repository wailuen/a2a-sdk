# w015 — GitHub issues #40, #41, #42, #43

Sourced from open issues on wailuen/a2a-sdk. Items are ordered by severity.
GH-43, GH-42, and GH-41 have no file overlap with each other or with GH-40.
Group A (parallel): GH-43, GH-42, GH-41. Group B (after A): GH-40.
Target: v0.5.12.

---

- [x] `GH-43` Gate serverInfo.title behind negotiated protocol version ‖ group:A
  - Creates: (modifies `agent_sdk/routes/mcp.py`)
  - Reads: `agent_sdk/routes/mcp.py`
  - Severity: critical
  - Root cause: `_handle_initialize()` emits `serverInfo.title` unconditionally regardless of negotiated protocol version. `title` was added in MCP 2025-11-25; emitting it under a negotiated `2025-06-18` session causes Claude.ai to reject the handshake with "Authorization with the MCP server failed". Additionally, `2025-11-25` is not in `SUPPORTED_PROTOCOL_VERSIONS`, so clients that request it can never negotiate to it.
  - AC: `serverInfo.title` is absent from the `initialize` response body when the negotiated version is `2025-06-18` or older; present when negotiated version is `2025-11-25`; `2025-11-25` added to `SUPPORTED_PROTOCOL_VERSIONS`; tests assert both cases.
  - GH: https://github.com/wailuen/a2a-sdk/issues/43

- [x] `GH-42` Include DocumentItem.type in DocumentList.to_plain_text() ‖ group:A
  - Creates: (modifies `agent_sdk/models/content_types.py`)
  - Reads: `agent_sdk/models/content_types.py`
  - Severity: medium
  - Root cause: `DocumentList.to_plain_text()` renders each document as `{name}[ (modified {when})]` but never reads `DocumentItem.type` (optional str). A document with `type='pdf'` silently drops the extension in every MCP text-only / AG-UI text-fallback path. Wire shape and frozen field contract are unaffected — this is a pure text-rendering gap.
  - AC: `DocumentList.to_plain_text()` outputs `"{name} ({type})"` when `DocumentItem.type` is set, e.g. `"Q4 Report (pdf)  2026-03-31"`; omits the parenthetical when `type is None`; test added asserting both cases.
  - GH: https://github.com/wailuen/a2a-sdk/issues/42

- [x] `GH-41` Document lifespan_extras as the canonical scheduling hook ‖ group:A
  - Creates: (modifies `agent_sdk/app.py`, `DESIGN.md` or `docs/scheduling.md`)
  - Reads: `agent_sdk/app.py`, `agent_sdk/contrib/commitments/executor.py`
  - Severity: medium
  - Root cause: `agent_sdk.scheduler` does not exist and `lifespan_extras` is undocumented for background tasks, causing domain authors to guess at a nonexistent import. `lifespan_extras` is already the ASGI-standard blessed pattern (used by `commitments_lifespan` and `webhooks_renewal_lifespan`). Decision: document `lifespan_extras`, do NOT ship a new `agent_sdk.scheduler` module.
  - AC: `Agent.__init__` docstring (app.py:79) documents `lifespan_extras` with a minimal `asyncio.create_task` example; a `## Scheduling` section added to DESIGN.md (or equivalent) referencing both contrib implementations as patterns; CHANGELOG entry; no new public API surface added.
  - GH: https://github.com/wailuen/a2a-sdk/issues/41

- [ ] `GH-40` Add LRN-023 commit-intent guard to wave-cycle.js archive phase ‖ group:B
  - Creates: (modifies `harness/workflows/wave-cycle.js`, `template/.claude/workflows/wave-cycle.js`)
  - Reads: `harness/workflows/wave-cycle.js`
  - Severity: high
  - Root cause: The archive phase (phase 7) gates on a green pytest suite but has no check verifying that Creates: files were actually committed. A wave can archive with deliverables only in the working tree, which a subsequent `git checkout` silently drops. No `git status`, `git log`, or ARCHIVE_INTENT_SCHEMA exists in the file.
  - AC: Immediately after the pytest gate passes and before the archive agent call, the workflow runs `git status --short`, cross-references unstaged/untracked paths against `wave.allCreates`, and blocks archive (sets `protocolBlocked=true`, logs offending paths) if any Creates: file is uncommitted; both `harness/` and `template/.claude/` copies updated in sync.
  - GH: https://github.com/wailuen/a2a-sdk/issues/40
