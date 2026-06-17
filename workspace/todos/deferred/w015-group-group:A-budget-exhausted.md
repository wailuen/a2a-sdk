wave: w015
group: group:A
date: 2026-06-15
round_count: 5
status: budget-exhausted

## Findings

### RT-JSON-POINTER-001
- severity: medium
- file: /Users/wailuen/Development/a2a-sdk/agent_sdk/a2ui/translator.py
- description: apply_data_model_update's escape guard checks the raw pointer string for '/..' but does not decode RFC 6901 percent-escape sequences (~1 → /) before the check. A pointer like '/foo~1../bar' passes the guard, then after token decoding navigates to key 'foo/..' in the model dict, silently creating a spurious key instead of the intended target. This is a data-integrity bug: the correct field is not written, a garbage key is created. Not exploitable for filesystem traversal or credential access (the model dict is an in-memory display-data structure), but violates the documented safety contract of the guard. The function is importable by SDK consumers (agent_sdk.a2ui.translator.apply_data_model_update) and any caller who passes developer- or user-derived pointer strings is affected.
- fix: Decode ~1 and ~0 sequences in the pointer BEFORE running the escape check, or alternatively check for the decoded '..' token after splitting. Example: after splitting into tokens, reject any token equal to '..' (post-decode). The current guard at line 177 should be supplemented with a post-split check: `if any(t == '..' for t in [tok.replace('~1', '/').replace('~0', '~') for tok in pointer[1:].split('/')])` then raise.
- codify: apply_data_model_update JSON Pointer escape guard must check POST-decoded tokens for '..', not the raw pointer string — raw check misses ~1-encoded traversal attempts.

### RT-SAFE-GET-SI2-001
- severity: medium
- file: /Users/wailuen/Development/a2a-sdk/agent_sdk/common/http.py
- description: safe_get() interpolates the caller-supplied hostname into AgentError messages: "safe_get: cannot resolve host '{host}'" and "safe_get: '{host}' resolves to a non-public address". The function is documented as the approved escape hatch for tool code that must fetch a user-supplied URL (bypassing the SourceAdapter pattern). When a tool passes a user-derived URL to safe_get and the AgentError propagates through _handle_tools_call (mcp.py line 352-356), exc.public()['message'] contains the hostname and is returned to the MCP caller in the isError text block. This is a latent SI-2 violation: user-derived input (the hostname) echoes in error output. SI-2 requires exception text never to interpolate user inputs.
- fix: Remove the hostname from AgentError messages in safe_get. Use generic messages: "safe_get: host resolution failed" and "safe_get: host resolves to a non-public address". The hostname is already logged separately if needed for diagnostics (add a logger.debug call for internal tracking, never exposing it to the wire).
- codify: safe_get AgentError messages must not interpolate the caller-supplied hostname — SI-2: exception text must never echo user inputs. Use generic messages only.

### RT-DESIGN-STALE-001
- severity: medium
- file: /Users/wailuen/Development/a2a-sdk/DESIGN.md
- description: DESIGN.md §6 states the bootstrap token is "printed to stdout" but the implementation (agent_sdk/auth/api_keys.py line 147-154) writes to stderr (file=sys.stderr). This contradicts LRN-010 and creates a documentation hazard: operators reading the DESIGN may look in the wrong stream for the token and conclude the bootstrap is broken. The code behavior (stderr) is correct; the DESIGN is stale.
- fix: Update DESIGN.md §6 bootstrap paragraph: replace 'printed to stdout' with 'printed to stderr' to match the code and LRN-010.

### RT-MCP-LEGACY-CT-001
- severity: medium
- file: /Users/wailuen/Development/a2a-sdk/agent_sdk/routes/mcp.py
- description: POST /mcp (Streamable HTTP) enforces Content-Type: application/json and returns HTTP 415 for non-JSON content types (lines 430-439). The legacy counterpart POST /mcp/messages does not perform this enforcement at all — any Content-Type passes through. This asymmetry means the legacy SSE transport accepts structurally invalid requests silently. The JSON body parse (line 680) will fail for non-JSON bodies and return a parse error over the SSE channel, but the 415 rejection is never raised, violating MCP spec §3.2.1 which applies to all POST endpoints.
- fix: Add the same Content-Type guard to mcp_messages (POST /mcp/messages) immediately after the session and version checks, before body read. Apply the same 'if ct and ct != application/json: return 400/415' pattern used in mcp_post.

### RT-TEST-COV-001
- severity: low
- file: /Users/wailuen/Development/a2a-sdk/tests/test_mcp_security_rt001_005.py
- description: The test suite has no test for the Content-Type: application/json enforcement on POST /mcp specifically. The 415 enforcement is tested only for the A2A surface (POST /v1/message:send in test_protocol_fixes_w9_group_a.py). The mcp_post 415 guard was added per MCP 2025-06-18 §3.2.1 but lacks a corresponding regression test that would catch accidental removal or breakage of the guard for the /mcp route.
- fix: Add a test in test_mcp_security_rt001_005.py or test_mcp_conformance_w10.py: POST /mcp with Content-Type: text/xml should return HTTP 415. Also add a companion test for POST /mcp with no Content-Type (should proceed, per the 'if ct' bypass).

### RT-SESSION-SCAN-001
- severity: low
- file: /Users/wailuen/Development/a2a-sdk/agent_sdk/routes/mcp.py
- description: Two O(n) linear scans over the sessions dict occur per authenticated POST /mcp request. First at line 491 (owner_has_session = any(rec[1] == owner for rec in sessions.values())) for the missing-session-id gate, and second at line 518 (for orphan_sid in [s for s, rec in list(sessions.items()) if rec[1] == owner]) for RTGA-010 orphan eviction on every initialize. Both scans are bounded by _MAX_SESSIONS=1000 so the worst-case work is O(1000) per request — acceptable but inefficient. A targeted flood of POST /mcp requests with valid auth (no session) from many distinct identities amplifies these scans without bound up to the session cap.
- fix: Maintain a reverse index dict {owner_key: set[session_id]} alongside the main sessions OrderedDict. Update it on session create/evict/expire. Both the 'owner_has_session' check and the RTGA-010 orphan loop become O(1) lookups against this index, eliminating the scan entirely. The reverse index must be kept consistent with all eviction paths (_prune_sessions, LRU popitem, mcp_delete).

## Instruction

Fix remaining findings, then re-run /wave w015.
