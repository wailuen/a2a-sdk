# w056 — GitHub issue 200

Sourced from open issues on wailuen/a2a-sdk. GH-186 is deferred by ruling and NOT in this wave.
Target: 0.17.2 (main only; no back-port to release/0.15.x, per the ruling).

One item. It adds its own entry to `CHANGELOG.md` `[Unreleased]`.

---

- [ ] `GH-200` Absent MCP-Protocol-Version on post-init POST /mcp gets 400; spec says assume the negotiated version or 2025-03-26 ‖ group:G1
  - Creates: (modifies `agent_sdk/routes/mcp.py` (`mcp_post`, session record / `_session_alive`, `_negotiated_version` docstring, module docstring), `tests/test_mcp_gh77_absent_version_header.py`, `DESIGN.md` §5.5 (~line 377), `workspace/learning/LRN-118-protocol-doc-behavior-drift.md`, `CHANGELOG.md`)
  - Reads: `tests/test_http_protocol.py` (~lines 240-320), `workspace/learning/LRN-089-mcp-version-gate-missing-initialize-carveout.md`, MCP 2025-06-18 Transports → Protocol Version Header
  - Severity: high
  - Root cause: `mcp_post` (`agent_sdk/routes/mcp.py:817-825`) treats an ABSENT `MCP-Protocol-Version` on a non-initialize request the same as an unrecognized one and returns 400 "MCP-Protocol-Version header required". GH-77 chose this deliberately, but the spec only requires 400 for an invalid/unsupported value; for an absent header it says the server SHOULD use the version negotiated at initialize, else assume 2025-03-26. Microsoft Copilot Studio omits the header on `tools/list` after a successful initialize, so it cannot load tools.
  - Ruling: Checkable reference: https://github.com/wailuen/a2a-sdk/issues/200#issuecomment-6234026443 (this reverses the GH-77 absent-header 400 on Streamable HTTP; do not reinstate it)
  - AC: At initialize, the server records the negotiated `protocolVersion` (from the initialize result body) against the new `Mcp-Session-Id`. The session record keeps its owner binding and TTL/LRU behaviour unchanged; every reader of the session record is updated for any shape change.
  - AC: Non-initialize `POST /mcp` with NO `MCP-Protocol-Version` header and a live `Mcp-Session-Id` owned by the caller → request is dispatched normally (200 for `tools/list` / `ping`), and the response `MCP-Protocol-Version` header equals that session's negotiated version.
  - AC: Non-initialize `POST /mcp` with NO header and NO session id (caller has no live session) → dispatched; response header is `2025-03-26`.
  - AC: The existing session checks still run first and are unchanged: unknown/expired/foreign session id → 404; no session id while the caller owns a live session → 400 "Mcp-Session-Id required".
  - AC: Header PRESENT but unrecognized (e.g. `1999-01-01`) on a non-initialize request → still 400. The error text must not say "header required" (it was sent); use "unsupported MCP-Protocol-Version" to match the GET/DELETE paths.
  - AC: Header present and supported → behaviour unchanged (response header echoes it).
  - AC: initialize behaviour unchanged (absent or unknown header still proceeds to body-level negotiation).
  - AC: `tests/test_mcp_gh77_absent_version_header.py`: replace the two absent→400 tests with absent→200 tests covering the session-version echo and the no-session 2025-03-26 fallback; add the present-but-unrecognized→400 test; keep the initialize regression test. Add a test that a session negotiated at `2025-03-26` echoes `2025-03-26`, and one negotiated at `2025-06-18` echoes `2025-06-18`.
  - AC: Module docstring, `_HEADER_ABSENT` comment, `_negotiated_version` docstring, the `mcp_messages` comment ("Streamable path rejects both") and DESIGN.md §5.5 no longer claim Streamable HTTP 400s on an absent header; they state the new rule and cite GH-200.
  - AC: LRN-118's check line is updated so it no longer requires "Streamable HTTP (absent→400)"; it should require the docs to match the GH-200 rule.
  - AC: CHANGELOG `[Unreleased]` Fixed entry citing GH-200 and the ruling URL, noting it reverses the GH-77 absent-header 400.
  - GH: https://github.com/wailuen/a2a-sdk/issues/200
  - SI: SI-5  # Touches the MCP request admission path next to auth and session ownership. The session-owner check and 404/400 session rules must stay exactly as they are; only the absent-version-header branch changes. No client-supplied header value is ever echoed unless it is in SUPPORTED_PROTOCOL_VERSIONS.

---

Archived 2026-10-17 by hand (the wave left the file in active/ again).
