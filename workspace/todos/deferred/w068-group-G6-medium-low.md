# w068 — deferred medium/low findings (unit:G6)

- Wave: w068
- Scope: unit:G6
- Date: 2026-10-25

Non-blocking — these did not block w068's archive. Address opportunistically or fold into a future wave.

Findings are deduped by file + description across all redteam rounds. Later-round duplicates are merged into the first entry.

## Medium

### D-1 — mismatch 400 echoes newest version, not the session's (agent_sdk/routes/mcp.py:1213-1217)
- Quote: `headers={_PROTOCOL_VERSION_HEADER: SUPPORTED_PROTOCOL_VERSIONS[0]},`
- Problem: The GH-273 session-mismatch 400 knows the owned session's `live_version` but echoes `SUPPORTED_PROTOCOL_VERSIONS[0]`. For a 2025-06-18 session sending 2025-11-25, the 400 echoes 2025-11-25 — the value it just rejected. The ruling says responses that know the session echo the session's version. `tests/test_gh273_mcp_session_version.py:47` pins the wrong value, and sends exactly the newest version so it cannot tell the behaviours apart.
- Fix: Use `headers={_PROTOCOL_VERSION_HEADER: live_version}` (owner-checked, not an SI-5 oracle). Change the assertion at test line 47 to `"2025-06-18"`. Add a test: initialize at 2025-03-26, send tools/list with header 2025-06-18, assert 400 with response header 2025-03-26. Update CHANGELOG GH-273 bullet and docs/protocols.md.
- Codify: A rejection decided from an owned session's negotiated version must echo that version, not the newest supported one.
- SDK candidate: yes

### D-2 — mismatch 400 refreshes last-seen (agent_sdk/routes/mcp.py:1206)
- Quote: `live_version = _session_alive(sessions, presented_session, owner)`
- Problem: The owner-checked lookup uses `touch=True` before the mismatch 400, so a rejected request refreshes last-seen and LRU position. A client stuck on a wrong header keeps its session alive forever. Contradicts the GH-273 design ("a rejected request cannot keep a session alive").
- Fix: Call with `touch=False`, do the 404 and mismatch-400 checks, then refresh (`sessions[id] = (time.time(), owner, live_version); sessions.move_to_end(id)` or a second `touch=True` call) only when the request passes. Add a test that a mismatch 400 leaves the stored timestamp unchanged.
- SDK candidate: yes

### D-3 — docs/protocols.md overclaims session-match rule for all verbs (docs/protocols.md:187-188)
- Quote: `After \`initialize\`, a present \`MCP-Protocol-Version\` on a request that carries` / `an owned \`Mcp-Session-Id\` must equal the version that session negotiated, else`
- Problem: Only `mcp_post` enforces it. `GET /mcp` with an owned session and a mismatched valid header still opens a 200 stream (mcp.py:~1311 only tests `is None`); `DELETE /mcp` still answers 204. CHANGELOG scopes it to POST only.
- Fix: Either enforce the same check in `mcp_get` (compare against `_session_alive`'s return, 400 after the 404, with test + CHANGELOG line), or narrow the doc to "a `POST /mcp` request" and add "GET and DELETE /mcp only reject unrecognized values." State the choice in DESIGN.md §5.5 too.
- Codify: When a rule is added to one verb of a multi-verb route, the user doc must name the verb, matching the design doc's scope.
- SDK candidate: yes

### D-4 — DESIGN.md §5.5 and mcp.py docstring miss GH-273 (DESIGN.md:383)
- Problem: DESIGN.md §5.5 (contributor ground truth per LRN-118) lists only "present-but-unrecognized -> 400" for Streamable HTTP; nothing about the GH-273 mismatch 400 or the early-exit session-version echo. The mcp.py module docstring (lines 65-75) has the same gap. Only docs/protocols.md was updated — the drift LRN-118's Prevention clause forbids. (A later round saw DESIGN.md:383 state "GET/DELETE /mcp do not apply the session-match rule"; verify current text before editing.)
- Fix: Add to §5.5 Streamable HTTP clause: a present, recognized header differing from the owned session's negotiated version -> 400 "unsupported MCP-Protocol-Version" (GH-273, ruling link), decided after the owner-checked 404; early exits echo the owned session's version, else the newest. Mirror one sentence in the mcp.py docstring. Declare DESIGN.md in the todo Modifies line and CHANGELOG Docs list.
- SDK candidate: yes

## Low

### D-5 — oversize session-id 400 echo disagrees with plan (agent_sdk/routes/mcp.py:1201-1202)
- Quote: `headers=base_headers,`
- Problem: Todo C-054/Reuses note says the >64-char session-id 400 "always echoes SUPPORTED_PROTOCOL_VERSIONS[0]". Code sends `base_headers`, echoing the client's own valid header (e.g. 2025-03-26).
- Fix: Use `{_PROTOCOL_VERSION_HEADER: SUPPORTED_PROTOCOL_VERSIONS[0]}` (as mcp_get/mcp_delete do) and add a test with header 2025-03-26 and a 65-char id; or correct the todo text.
- SDK candidate: yes

### D-6 — only the 415 early exit is tested (tests/test_gh273_mcp_session_version.py:68, :92)
- Quote: `async def test_early_exit_415_echoes_owned_session_version(`
- Problem: Five early exits (415, 413, parse error, invalid request, unknown-version 400) should echo the owned session's version; only 415 is tested. The no-refresh test checks only the timestamp, not that `move_to_end` was skipped.
- Fix: Parametrize over all five on an owned 2025-06-18 session: text/plain body (415), oversized body (413), `b'{'` (parse error), `b'[]'`/`json=[1]` (invalid request), header `2099-01-01` (unknown-version 400); each asserts 2025-06-18. Add other-owner cases asserting the newest. Assert `list(sessions)` order unchanged after the rejected request.
- SDK candidate: yes

### D-7 — no expired-session tests (tests/test_gh273_mcp_session_version.py:104)
- Quote: `async def test_unknown_session_with_any_header_is_404(client: httpx.AsyncClient) -> None:`
- Problem: AC lists expired sessions alongside unknown/other-owner as 404 for matching and mismatched headers, echoing newest on early exits. Nothing ages a session past `SESSION_TTL_SECONDS`; the `touch=False` expiry-removal path is untested.
- Fix: Set `sessions[sid] = (time.time() - SESSION_TTL_SECONDS - 1, owner, ver)`, send tools/list with 2025-06-18 and 2025-11-25, assert 404 "session not found". Add a 415 on the expired id asserting newest echoed and `sid` removed from `sessions`.
- SDK candidate: yes

### D-8 — CHANGELOG GH-273 bullet inaccurate/incomplete (CHANGELOG.md:10)
- Problem: "they no longer refresh the session's last-seen" describes a change that did not happen — before GH-273 the early exits never looked up the session. Bullet omits the `tests/test_mcp_gh77_absent_version_header.py` change and the `mcp_get` caller change.
- Fix: Reword to "the new lookup behind that echo does not refresh last-seen"; add the gh77 test file to Tests and `mcp_get` to changed callers.
- SDK candidate: yes

### D-9 — Mcp-Session-Id header read twice (agent_sdk/routes/mcp.py:1121, :1194)
- Quote: `early_id = request.headers.get(_SESSION_ID_HEADER)`
- Problem: Same header read into `early_id` and `presented_session`, each with its own 64-char check. Easy to drift.
- Fix: Read once at the top as `presented_session` and reuse for both lookups.
- SDK candidate: yes
