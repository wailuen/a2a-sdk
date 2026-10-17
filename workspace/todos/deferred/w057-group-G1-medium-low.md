wave: w057
group: G1
date: 2026-10-17

Non-blocking — these did not block w057's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for G1. Where several rounds raised the
same finding, the entries are merged into one, the strongest severity is kept, and the extra detail from
each round is folded in. IDs below are renumbered after the merge (round IDs collided: two rounds each
used RT-002..RT-005 for different findings). All findings are SDK-level (sdkCandidate: true).

## Findings

### RT-001
- severity: medium
- file: DESIGN.md
- description: The GH-201 bullet in DESIGN.md §5.5 (line 372) does not say what happens when more than 4 clients are active at once on one identity. The same section (line 375) says an org-wide OAuth client puts a whole org on one identity key, which is why the stream cap is sized in the low hundreds and can be raised by the operator. `_MAX_SESSIONS_PER_IDENTITY = 4` is hard-coded in agent_sdk/routes/mcp.py:152. So with 5 or more active Copilot Studio or Claude.ai users on one org-wide client, each `initialize` evicts a sibling's session. That sibling gets a 404, starts a new session, and evicts the next one. This is the GH-201 symptom again, now above 4 clients instead of above 1.
- fix: Do not change the value 4; the maintainer ruled it in issue 201, comment 6234642337. Add a sentence to the DESIGN.md §5.5 GH-201 bullet naming this limit: with more than 4 active clients on one identity, the least-recently-used client sees a 404 and must start a new session. Then raise to the maintainer, as a follow-up issue, whether this cap should become operator-raisable like `AGENT_SDK_MAX_MCP_STREAMS_PER_IDENTITY`.
- codify: When a per-identity cap is added, check it against every documented case where many users share one identity key (here, an org-wide OAuth client), and write the limit down next to the rule.
- sdkCandidate: true

### RT-002
- severity: medium
- file: workspace/components/README.md
- description: (Merged from two rounds.) The todo's `Reuses: C-028` note required updating the C-028 registry description to list agent_sdk/routes/mcp.py `_evict_identity_lru` as a second hand-written per-key quota, alongside IdpFlowStore._evict_for. The file was not changed: line 185 still lists mcp.py only for the 'shared table, one flooder evicts everyone' session popitem eviction. That is now partly out of date: mcp.py has a per-identity cap, while the global popitem still behaves that way (see RT-001). Without the update, the planned C-028 extraction will miss the new helper, which is an unregistered duplicate of the C-028 capability.
- fix: Edit the C-028 detail paragraph and table row (around line 185) to say that `agent_sdk/routes/mcp.py::_evict_identity_lru` (GH-201) is a second hand-written per-key LRU quota, keyed by `identity_key`, with a cap of 4, evicting only its own oldest entries, and that it should move onto C-028 when bounded_store.py is built.
- codify: A Reuses: note that tells the implementer to update the component registry is an acceptance criterion; check that workspace/components/README.md actually changed.
- sdkCandidate: true

### RT-003
- severity: medium
- file: tests/test_gh201_mcp_session_sharing.py
- description: (Merged from two rounds.) Test gaps on the new eviction rule. (1) The AC 'Global _MAX_SESSIONS LRU cap and SESSION_TTL_SECONDS idle TTL behave as before' has no test. No test in tests/ uses _prune_sessions or SESSION_TTL_SECONDS, or fills mcp_sessions to the global cap, so the per-identity cap is never tested against a full global map (see also RT-007). (2) No test re-initializes with the caller's own session id while the identity is already at the 4-session cap. In mcp.py:906-910 the order matters: the code removes the presented session first, then applies the LRU cap. If those two steps were swapped, a re-initialize at the cap would evict the presented session and one innocent sibling, and every current test would still pass. The existing re-initialize tests use only 2 sessions (test_reinitialize_evicts_only_presented_session here and in test_mcp_rtga_006_007_010.py:186); the at-cap re-initialize in test_other_identity_sessions_survive only checks the other identity's session.
- fix: Add tests that: (a) monkeypatch _MAX_SESSIONS low and check the documented global-cap behaviour; (b) monkeypatch time or SESSION_TTL_SECONDS and check that an idle session expires to 404; (c) create s1..s4, touch them so s1 is least recently used, re-initialize presenting s3, and assert s3 is gone while s1, s2, s4 and the new session are all live (4 sessions, s1 kept even though it is LRU).
- codify: When the order of two eviction steps decides who gets evicted, test the boundary where both steps could fire.
- sdkCandidate: true

### RT-004
- severity: medium
- file: harness/agents/mcp-advisor.md
- description: The portable MCP advisor and mcp-check checklists now say 'do NOT 400 on a missing id' (harness/agents/mcp-advisor.md:89-91, harness/skills/mcp-check/SKILL.md:77, and the .claude/ mirrors). These checklists audit ANY MCP server, not just this SDK. The MCP spec (harness/reference/mcp-protocol.md:269) says a server that REQUIRES a session id SHOULD answer a request without one with 400. Writing this SDK's GH-201 choice as a universal rule will make the advisor wrongly flag spec-conformant servers that require sessions.
- fix: Reword as conditional: 'missing id → 400 only if the server requires sessions; a server that accepts session-less requests (e.g. agent-sdk since GH-201) must not 400 and must not let initialize evict sibling sessions of a shared credential'. Apply the same wording in all four files (harness + .claude mirrors). Do not touch template/.
- sdkCandidate: true

### RT-005
- severity: medium
- file: agent_sdk/routes/mcp.py
- description: The todo's 'Reuses: C-028' note said to put the per-identity LRU eviction in a small helper next to _prune_sessions (e.g. _evict_identity_lru(sessions, owner, cap)) and 'Do not inline it in mcp_post', so the later C-028 extraction stays mechanical. An early round found it inlined in mcp_post (mcp.py:910-912). Status at write time: the helper now exists at mcp.py:268 and is called at mcp.py:910, so this looks resolved; the remaining part is a direct unit test of the helper.
- fix: Confirm _evict_identity_lru stays a standalone helper next to _prune_sessions, called from mcp_post in the order RT-003(2) depends on, and add a direct unit test for it.
- sdkCandidate: true

### RT-006
- severity: low
- file: agent_sdk/routes/mcp.py
- description: `_evict_identity_lru(sessions, owner, cap)` at lines 268-273 has no docstring. Despite its parameter name, it keeps `cap - 1` sessions, not `cap`: it frees one slot before the new session is inserted. The acceptance criterion and the ruling describe the opposite order: register first, then evict down to exactly 4. Either order gives the same result, but if a future caller (such as the planned C-028 extraction) calls the helper after insertion, the identity silently ends up with 3 sessions.
- fix: Add a docstring saying the helper must be called before inserting the owner's new session and leaves at most `cap - 1` of the owner's sessions, oldest first. Better still, call it after the insert at line 913 and keep exactly `cap`, so it matches the ruling's wording and IdpFlowStore._evict_for.
- sdkCandidate: true

### RT-007
- severity: low
- file: tests/test_gh201_mcp_session_sharing.py
- description: test_owner_at_cap_never_evicts_other_identity_at_global_cap never reaches the global cap. With `_MAX_SESSIONS=6`, the other identity holds 2 sessions and the caller is held to 4, so the total is at most 6. `_prune_sessions`'s `while len(sessions) > _MAX_SESSIONS` never runs, so the global LRU step, which can evict another identity's session and is unchanged by design, is never tested. The test name claims a global-cap guarantee the code does not give.
- fix: Rename the test to describe what it checks (the per-identity cap keeps the caller from crowding out another identity under a small global cap). Or set `_MAX_SESSIONS=5` and assert the documented, unchanged behaviour: the globally oldest entry is evicted when the table overflows.
- sdkCandidate: true

### RT-008
- severity: low
- file: DESIGN.md
- description: DESIGN.md §5.5 (line 372) drops the session-required 400 but does not say why this still meets the spec. The spec's 400 applies only to servers that require a session id. Without that sentence, a later reviewer reading mcp-protocol.md:269 may 're-fix' the 400 back in, which the ruling forbids.
- fix: Add one clause: 'sessions are optional on this server (spec: only servers that require a session id SHOULD 400 a missing one), so a session-less request is not an error'.
- sdkCandidate: true

### RT-009
- severity: low
- file: workspace/todos/deferred/w015-group-group:A-budget-exhausted.md
- description: Deferred item lines 44-45 describe the removed owner_has_session scan and the RTGA-010 evict-all loop as live code, and propose a reverse index for both. Those scans are gone. The new per-identity scan on initialize (mcp.py:910) is the one that remains.
- fix: Update the deferred note: owner_has_session and the RTGA-010 loop were removed by GH-201; the remaining O(n) scan is the per-identity cap on initialize. A reverse index would serve the new _evict_identity_lru helper.
- sdkCandidate: true
