# w057 — GitHub issue 201

Sourced from open issues on wailuen/a2a-sdk. GH-186 is deferred by ruling and NOT in this wave.
Target: 0.17.3 (main only, per the ruling).

One item. It adds its own entry to `CHANGELOG.md` `[Unreleased]`.

---

- [ ] `GH-201` Re-initialize evicts every session of the same identity, so clients sharing a credential knock each other out ‖ group:G1
  - Creates: (modifies `agent_sdk/routes/mcp.py` (`mcp_post` initialize branch ~line 900, session-less 400 branch ~lines 860-870, `_sessions`/`_prune_sessions` helpers, module docstring), `tests/test_mcp_rtga_006_007_010.py`, `tests/test_mcp_conformance_w10.py`, `tests/test_mcp_gh77_absent_version_header.py`, new `tests/test_gh201_mcp_session_sharing.py`, `DESIGN.md` §5.5 MCP section, `CHANGELOG.md`)
  - Reads: `agent_sdk/auth/identity.py` (`principal_key`), `REVIEWS.md`, `harness/agents/mcp-advisor.md`, `workspace/learning/LRN-426-ruling-reversal-doc-sweep.md`, `workspace/learning/LRN-427-doc-test-locks-old-rule.md`
  - Severity: medium
  - Root cause: a successful `initialize` on `POST /mcp` deletes ALL sessions owned by the identity key (RTGA-010). The key is `Identity.principal_key`, which has no user part for a shared API key or org-wide OAuth client, so two clients on one credential evict each other (next call → 404). Separately, a non-initialize request with no `Mcp-Session-Id` gets 400 "Mcp-Session-Id required" whenever any session for that identity is alive.
  - Ruling: Checkable reference: https://github.com/wailuen/a2a-sdk/issues/201#issuecomment-6234642337 (this reverses RTGA-010's evict-all and the owner_has_session 400; do not reinstate either)
  - AC: Add a module constant `_MAX_SESSIONS_PER_IDENTITY = 4`.
  - AC: A successful `initialize` evicts only the session it replaces: the presented `Mcp-Session-Id`, if it is live AND owned by the caller. A presented id owned by another identity is never evicted (owner check unchanged).
  - AC: After registering the new session, if the identity holds more than 4 live sessions, evict that identity's least-recently-used sessions until it holds exactly 4. Other identities' sessions are never touched by this step.
  - AC: Global `_MAX_SESSIONS` LRU cap and `SESSION_TTL_SECONDS` idle TTL behave as before.
  - AC: The `owner_has_session → 400 "Mcp-Session-Id required"` branch is removed. A non-initialize request with no `Mcp-Session-Id` is dispatched normally whatever other sessions exist for the identity; its absent-version-header handling stays as GH-200 (no session → `2025-03-26`).
  - AC: Unchanged and still tested: unknown/expired session id → 404; session id owned by another identity → 404; present-but-unsupported `MCP-Protocol-Version` → 400; GH-200 session-version echo.
  - AC: Tests (new `tests/test_gh201_mcp_session_sharing.py`): two clients on the same API key each initialize, then both call `tools/list` with their own session id → both 200; a 5th initialize on the same identity evicts only the least-recently-used of that identity's sessions (the other 3 stay live, a just-used older session is kept over an idle newer one); re-initialize presenting session S evicts S only; a different identity's sessions survive all of the above; a session-less `tools/list` while the identity has live sessions → 200.
  - AC: Replace `test_reinitialize_evicts_previous_session`, `test_m1_absent_session_id_after_init_returns_400`, and the "Mcp-Session-Id required" assertion in `tests/test_mcp_gh77_absent_version_header.py` with tests for the new rule. Per LRN-427, a doc-guard or regression test must not keep asserting the reversed rule.
  - AC: Per LRN-426, sweep every doc, comment, advisor checklist (`harness/agents/mcp-advisor.md`, `.claude/agents/mcp-advisor.md`, `harness/skills/mcp-check/SKILL.md`, `.claude/skills/mcp-check/SKILL.md`), `DESIGN.md` and `REVIEWS.md` for the evict-all and session-required-400 rules, and update them to the GH-201 rule. Do NOT edit `template/`.
  - AC: CHANGELOG `[Unreleased]` Fixed entry citing GH-201 and the ruling URL, noting it reverses RTGA-010's evict-all and the session-required 400.
  - GH: https://github.com/wailuen/a2a-sdk/issues/201
  - SI: SI-5  # Touches MCP session ownership next to auth. The owner binding must stay exact: no step may evict, read or touch a session owned by a different identity, and a presented session id from another identity must still 404 without revealing it exists.
  - Reuses: C-028  # The new per-identity cap (evict an identity's own least-recently-used sessions down to 4, never another identity's) is the per-key quota that C-028 (planned, extends C-024) describes. Its registry entry already names agent_sdk/routes/mcp.py session popitem eviction as one of the places with this problem. agent_sdk/common/bounded_store.py does not exist, so do not build it in this wave. Instead, follow the semantics of the reference IdpFlowStore._evict_for (agent_sdk/auth/oidc.py:447). Put the logic in one small helper next to _prune_sessions, for example _evict_identity_lru(sessions, owner, cap). Do not inline it in mcp_post. Then update the C-028 description to list mcp.py as a second hand-rolled per-key quota. This keeps the later C-028 extraction mechanical.
  - Reuses: C-024  # Count and evict by the existing owner key. That is `owner = _identity_key(identity)` in mcp.py, which is the same function as common.admission.identity_key and wraps principal_key. Do not call identity.principal_key directly as the Reads: line suggests. The per-identity count has to compare the same string the session tuple stores at rec[1]. Otherwise the cap and the owner check can drift apart. Also note: the registry says C-024 is BoundedTtlSingleUseStore (planned), but the mcp.py:218 comment calls common.admission.StreamSlot 'C-024'. Do not copy that mislabel into the new comments.

---

Archived 2026-10-17 by hand (the wave left the file in active/ again). After the wave, the per-identity cap was changed by hand from a fixed 4 to the AGENT_SDK_MAX_MCP_SESSIONS_PER_IDENTITY setting (default 200), per https://github.com/wailuen/a2a-sdk/issues/201#issuecomment-6235185280
