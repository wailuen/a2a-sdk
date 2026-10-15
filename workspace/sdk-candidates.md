# SDK issue candidates — w052 (2026-10-15)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: RT-001: Service-key mint log line writes the caller-supplied label raw with %r (no length cap, control chars pass through) instead of going through safe_line_text from agent_sdk/common/redact.py as the todo's Reuses: C-034 note requires. Fix: log safe_line_text(body.label); add a test with \n, \x1b and a 5000-char label asserting capped, collapsed caplog output.
- Severity: high
- Component: security
- File: agent_sdk/routes/admin.py
- Rationale: SDK admin route logging hygiene (SI-2: no raw user input in logs); not agent-specific code.

## Candidate 2: RT-002: The SI-2 hostile no-leak test only covers the mint path. Nothing checks that the service-key plaintext stays out of caplog/response bodies on list, revoke, a 401 with DISABLE_API_KEYS, or a 403 on /admin/api/*. Nothing checks that refusal bodies and WWW-Authenticate headers for a service key match a user key's byte for byte. Fix: add one DEBUG-level caplog test covering all four paths.
- Severity: high
- Component: security
- File: tests/test_gh182_service_key.py
- Rationale: SDK's own test suite for core credential/auth handling; covers SDK secret-leak guarantees, not agent domain tests.

## Candidate 3: RT-003: revoke_by_value lets any kind=="api_key" caller revoke any user's OAuth access/refresh token family, and /oauth/revoke skips the DISABLE_API_KEYS check. A narrow CI service key can therefore sign out every person in the tenant. Fix: in _owned, require caller.kind=="api_key" and caller.admin for cross-owner revoke (silent no-op otherwise, RFC 7009); add a test that a service key cannot revoke another client's token.
- Severity: high
- Component: protocol/oauth
- File: agent_sdk/auth/oauth_tokens.py
- Rationale: SDK OAuth revocation route authorization (RFC 7009 /oauth/revoke) lives in agent_sdk/auth and agent_sdk/routes/oauth.py.

## Candidate 4: RT-004: SI-5 identity-decision surfaces lack pinning tests. (1) No test that OAuth consent approval (routes/oauth.py:912) refuses a service key as Bearer and as the api_key form field. (2) No test that a service key cannot read another identity's task (tasks/memory.py:185) and gets 404 / -32001 with no existence leak. A future 'admin or service' change would pass the suite.
- Severity: high
- Component: security
- File: tests/test_gh182_service_key.py
- Rationale: SDK identity-binding and consent guarantees in core routes/tasks; SDK test coverage, not agent tests.

## Candidate 5: RT-005: /acceptance should use only the service key for protocol calls. The A2A/AG-UI transport examples still say Authorization: Bearer <admin_key> (lines ~158, 166, 226, 232), and the Rules bullet (~605) still says the admin key goes to the chmod-600 temp file. harness/workflows/acceptance-api.js (lines 13, 98) still says 'admin API key'. The same stale text is in the template and .claude copies. Fix: replace with <service_key> everywhere, update acceptance-api.js and its template mirror, and apply to all three skill copies.
- Severity: high
- Component: harness/skill
- File: harness/skills/acceptance/SKILL.md
- Rationale: Harness skill and workflow text that all agent repos run; SDK-owned harness.

## Candidate 6: RT-006: The 'Teardown: revoke the service key' step sits right after the Phase 2A workflow call (~line 295), before the Phase 3 fix loop and Phase 2B/--ux reuse the key. A model that follows the steps in order revokes the key after round 0, so every later round gets 401s and chases made-up auth failures. Fix: move teardown to the true exit points (final report, Phase 3b escalation, abort), state that the key persists across rounds and restarts, and update the Server restart procedure. The template copy has the same bug.
- Severity: high
- Component: harness/skill
- File: harness/skills/acceptance/SKILL.md
- Rationale: Harness skill control-flow bug affecting every agent's acceptance run.

## Candidate 7: RT-001 (round 2): The revoke_by_value narrowing to caller.admin also changes public POST /oauth/revoke behavior for plain user API keys (was: revoke any token; now: silent no-op, still 200). This is undocumented: not in the CHANGELOG [Unreleased], the oauth.py docstrings at :29/:1036 still say api_key callers may revoke any token, DESIGN.md:393 is stale, oauth_tokens.py is missing from the todo's Modifies list, and no test covers user keys (with DISABLE_API_KEYS on and off).
- Severity: high
- Component: protocol/oauth
- File: agent_sdk/auth/oauth_tokens.py
- Rationale: SDK public OAuth route behavior change plus its docs, changelog and tests.

## Candidate 8: RT-002 (round 2): The template acceptance SKILL.md has drifted from the harness copy. The Rules bullet (~609) still says 'The admin key is read from ADR-000 but never printed', while the harness copy (harness/skills/acceptance/SKILL.md:614) describes the service key in a chmod-600 temp file. The LRN-208 identity check fails. The template SKILL.md edits are also uncommitted in the template peer repo, while acceptance-api.js was already committed (a6e3b29).
- Severity: high
- Component: harness/template
- File: template/.claude/skills/acceptance/SKILL.md
- Rationale: Template scaffold that seeds every downstream agent; SDK-owned.

## Candidate 9: RT-001 (round 3): The new Identity.service field was inserted mid-dataclass (after admin, before label/user) in an exported frozen dataclass. Positional construction such as Identity("api_key", sid, False, "my-label") now sets service to a truthy string, which lets the key bypass idp_disable_api_keys in require_identity. Fix: move service to the end or make it kw_only; add a CHANGELOG Added line for Identity.service; add a positional-construction regression test.
- Severity: high
- Component: security
- File: agent_sdk/auth/identity.py
- Rationale: Public SDK auth API (agent_sdk.auth.Identity); a field-order change escalates privilege. SDK internals and security.

## Candidate 10: RT-002 (round 3): Narrowing /oauth/revoke to admin-only api_key callers changes behavior for existing user keys. That is outside the GH-182 ruling (issuecomment-6193941983), which covers only service keys. It was shipped with no maintainer ruling, and the SI annotation's claim that 'only admin keys can do that today' is wrong. Fix: either narrow only service keys (if caller.kind=="api_key" and not caller.service), or record an explicit maintainer ruling URL before release and cite it in the CHANGELOG and DESIGN.md §5.5.
- Severity: high
- Component: protocol/oauth
- File: agent_sdk/auth/oauth_tokens.py
- Rationale: Breaking behavior change on an SDK public RFC 7009 route; needs a ruling at SDK level.

## Candidate 11: RT-003 (round 3): The template peer repo has uncommitted, unpushed edits to .claude/skills/acceptance/SKILL.md and .claude/skills/agent-verify/SKILL.md (origin/main still at a6e3b29). Agents seeded from the template still get the admin-key flow. Fix: commit with a GH-182 message, push to wailuen/a2a-agent-template, then confirm a clean status and the new origin/main head.
- Severity: high
- Component: harness/template
- File: template/.claude/skills/acceptance/SKILL.md
- Rationale: Template scaffold propagation is SDK release work; downstream agents depend on it.
