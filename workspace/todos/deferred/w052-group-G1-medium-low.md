wave: w052
group: G1
date: 2026-10-15

Non-blocking — these did not block w052's archive. Address opportunistically or fold into a future wave.

Deduped by file + description across every unit redteam round for group G1. Where several rounds raised the
same finding, the entries are merged into one, the strongest severity is kept, and the extra detail from each
round is folded in. The IDs below are renumbered for this note; they do not match any single round's IDs.
All findings are SDK-level (sdkCandidate: true). Context: GH-181 (format-neutral prompt section) and GH-182
(service API-key kind: admin-minted, accepted on require_identity routes even with DISABLE_API_KEYS).

## Findings

### RT-001
- severity: medium
- file: agent_sdk/auth/identity.py
- description: Raised in two rounds. `service: bool = False` was inserted between `admin` and `label` in the public frozen dataclass `agent_sdk.auth.Identity` (exported in agent_sdk/auth/__init__.py `__all__`). Positional construction such as `Identity("api_key", kid, False, "ci-label")` now sets `service="ci-label"`, a truthy value, which silently lets that identity pass `require_identity` under DISABLE_API_KEYS. The 5th positional arg also moves from `user` to `label`. The GH-152 precedent appended `user` at the end for exactly this reason. `ApiKeyInfo` (agent_sdk/auth/api_keys.py:43) has the same mid-insert, and its new `service` field is required with no default. CHANGELOG has no Added line for the new public fields or the new `service=` keyword on `ApiKeyStore.mint` (LRN-202).
- fix: Move `service` to the end of `Identity` (after `user`) and of `ApiKeyInfo` (after `last_used`), or make both `kw_only=True` with a CHANGELOG note. Give `ApiKeyInfo.service` a default of False. Add a test that `Identity("api_key", "x", False, "lbl").label == "lbl"`. Add CHANGELOG Added lines for Identity.service, ApiKeyInfo.service and ApiKeyStore.mint(service=...).

### RT-002
- severity: medium
- file: DESIGN.md
- description: Raised in four rounds. Spec drift. DESIGN.md:425-432 (GH-152 API-key switch paragraph and table) still says `AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS=true` "rejects non-admin `api_key` identities on every route guarded by `require_identity`" and that only admin keys stay accepted. Service keys (non-admin) now pass require_identity (agent_sdk/auth/middleware.py:140-145). §5.5/§6 (line ~419) list no key kinds and never describe the service kind, its refusal on require_admin, or that it has no task-binding admin bypass. The ADR a003 D3 text and table (workspace/adr/a003-oauth-idp-sign-in.md ~line 64) still say only admin keys bypass DISABLE_API_KEYS. Only docs/security.md and the /oauth/revoke line (DESIGN.md:393) were updated.
- fix: Update DESIGN.md §6 (lines ~419-432) and the a003 D3 text and table. Describe the `service` flag: rides on kind="api_key"; minted by an admin only, never via bootstrap; mutually exclusive with admin; accepted by require_identity even with DISABLE_API_KEYS; refused by require_admin, /admin/*, key management and /oauth/authorize consent; revokes only its own tokens on /oauth/revoke; no admin task-binding override (tasks/memory.py:185). Amend line 425 to say non-admin, non-service api_key identities are rejected. Cite the GH-182 ruling URL.
- codify: When a change widens an auth gate, grep DESIGN.md (and the ADRs) for every normative sentence about that gate (here "non-admin api_key") and update each one, not just the nearest.

### RT-003
- severity: medium
- file: agent_sdk/routes/oauth.py
- description: Docstrings written in this wave misstate who may revoke any OAuth token. The module docstring (line 29) says "admin api_key callers may revoke any token", and oauth_revoke (lines 1036-1037) says "admin api_key callers may revoke any token; oauth-kind, user and service callers self-revoke". The code (agent_sdk/auth/oauth_tokens.py:569 `_owned`) lets every non-service api_key revoke any token, including normal user keys, and even while DISABLE_API_KEYS=true (verified: a user key gets 401 on /v1/tasks but 200 plus a successful revoke of another client's token on /oauth/revoke). DESIGN.md:393 and oauth_tokens.py's docstring say "non-service API keys", so the three descriptions disagree.
- fix: Reword both oauth.py docstrings to match DESIGN.md:393: "non-service api_key callers may revoke any token; oauth-kind and service-key callers revoke only their own (silent no-op otherwise)". If the intent really was admin-only, that is a behaviour change needing a ruling, not a docstring edit.
- codify: A docstring that describes an authorization rule must be generated from or tested against the predicate it describes; reviewers should diff each docstring claim against the actual `_owned`-style predicate.

### RT-004
- severity: medium
- file: tests/test_gh182_service_key.py
- description: Raised in four rounds. The AC says the key kind survives restart "for every key store (local and shared/table store)". `test_kind_survives_reload_and_legacy_records_are_normal` only re-wraps the same live `ak._store` object in a new ApiKeyStore. That is not a restart: no EncryptedSqliteStore is closed and reopened from its file, and AzureTableCredentialStore is never exercised, even though tests/test_azure_credential_store.py already has the fixtures. The shared/table half of the AC has no test.
- fix: Parametrize over (a) an EncryptedSqliteStore at tmp_path that is minted into, closed, and reopened as a new instance on the same file and MASTER_KEY, and (b) AzureTableCredentialStore using the existing test double from tests/test_azure_credential_store.py (a real in-memory table double, not MagicMock, per harness/CLAUDE.md). On each, assert verify(svc).service is True after the reopen and that a legacy record without the field loads as service=False.

### RT-005
- severity: medium
- file: harness/skills/acceptance/SKILL.md
- description: Raised in two rounds. The new Rule (line ~609) "The admin key mints and revokes the service key and does nothing else" contradicts Phase 2B (`--ux`, line 444+), which opens the /admin test console and so needs the admin key; a service key is refused on /admin. That path makes protocol and tool calls with admin privilege, so the AC "use only the service key for protocol calls" is not true for `--ux` runs. The teardown note (line ~295) says the service key must stay valid "for Phase 2B", which never uses it. The "Server restart is safe" rule (line ~624) still mentions only the admin key. Same text in the template/.claude/skills and .claude/skills copies.
- fix: State the carve-out explicitly in the Rule and in Phase 2B: the admin key is also used to sign in to the /admin console for `--ux` (the console is an admin surface), and say why. Drop "Phase 2B" from the reason the service key stays valid, or explain what in 2B uses it. Mention the service key in the restart rule. Apply to the harness, template and .claude copies identically.

### RT-006
- severity: medium
- file: harness/skills/agent-verify/SKILL.md
- description: Neither /acceptance (Phase 0 mint) nor /agent-verify (Phase 1 step 4) checks that the mint response has `service: true`. These skills are seeded into agent repos that may pin an SDK older than this release. There KeyMintRequest ignores the unknown `service` field (pydantic default extra=ignore) and silently mints a normal user key. With DISABLE_API_KEYS=true every protocol call then gets 401 and the acceptance fix loop misreads it as agent failures; without it the run silently uses a plain user key.
- fix: After the mint curl, require `.service == true` in the JSON response; otherwise revoke the key just minted and stop with "agent-sdk >= 0.15.0 required for service keys". Mirror in harness/skills/acceptance/SKILL.md and in the template/.claude/skills and .claude/skills copies.

### RT-007
- severity: medium
- file: template/.claude/skills/acceptance/SKILL.md
- description: The template copies are edited but not committed in the template peer repo (`git -C template status` shows both SKILL.md files modified; LRN-071). The AC "harness and template copies identical" is not met literally either. Old drift remains: the scriptPath comment block and the "No secrets in output" rule differ between harness/skills/acceptance/SKILL.md and template/.claude/skills/acceptance/SKILL.md.
- fix: Commit and push the template changes to wailuen/a2a-agent-template before release. Sync the "No secrets in output" bullet so the template copy matches the harness copy (rewritten for the service key). Leave only the needed scriptPath difference.

### RT-008
- severity: medium
- file: harness/workflows/acceptance-api.js
- description: Raised in two rounds. harness/workflows/acceptance-api.js (comments and the "Service key:" prompt line; wording changed from admin key to service key) was modified by this group but is not in the GH-182 todo's Creates/Modifies list, and neither is its template/.claude/workflows/acceptance-api.js peer copy (LRN-085). The peer copy matches and was pushed in template commit a6e3b29, but undeclared edits escape wave scope checks. The .claude/skills/{acceptance,agent-verify}/SKILL.md local copies are also undeclared.
- fix: Add harness/workflows/acceptance-api.js, template/.claude/workflows/acceptance-api.js and the .claude/skills/{acceptance,agent-verify}/SKILL.md copies to the GH-182 todo's Modifies list. Record template commit a6e3b29 in the closing note.

### RT-009
- severity: medium
- file: agent_sdk/__init__.py
- description: The GH-181 thread has an owner comment ("Related, small") asking to export `safe_line_text` from the top-level `agent_sdk` package next to `safe_cell_text` (a2a-teamwork pins the internal import, RT-106). The todo dropped it, and agent_sdk/__init__.py:23 still exports only safe_block_text, safe_cell_text and safe_error_text. Releasing and closing GH-181 would silently lose the request.
- fix: Either add `safe_line_text` to agent_sdk/__init__.py imports and `__all__` with a CHANGELOG Added line and an import test, or open a follow-up issue linked from GH-181 before closing it.

### RT-010
- severity: low
- file: agent_sdk/routes/admin.py
- description: Raised in four rounds. `mint_key` checks `body.admin and body.service` (line 260) and refuses `service` on the bootstrap path before any authentication and before `unauth_rate_limit`. An unauthenticated caller sending {admin:true, service:true} gets 422 with a semantic detail instead of 401 with the PRM WWW-Authenticate challenge, and on the X-Bootstrap-Token path that request skips the per-IP unauthenticated rate limit. A bootstrap-header request with service:true is refused before the "bootstrap-path key mint attempted" audit log line, so that misuse leaves no audit trace. The same rule is also enforced a second time in `ApiKeyStore.mint` with a generic AgentError. Nothing leaks, but validation runs ahead of authentication.
- fix: Move the admin+service check after `await require_admin(request)` in the admin branch. In the bootstrap branch, refuse service only after `unauth_rate_limit` and after the audit log line. Optionally move the rule into a pydantic `model_validator` on KeyMintRequest, or rely on ApiKeyStore.mint's AgentError(VALIDATION) mapped to 422 after auth, so there is one source of truth.

### RT-011
- severity: low
- file: agent_sdk/routes/admin.py
- description: Raised in two rounds. Mint logging is uneven. Only service-key mints are logged (line ~288, at WARNING); admin-path mints of admin or normal keys are not logged at all, which falls short of the AC wording "logged like other mints". The existing bootstrap log at line ~271 still puts the raw caller label through %r with no length cap, the pattern the todo's Reuses note said not to copy.
- fix: Log every admin-path mint once at INFO with key_id, kind (admin/service/standard) and a safely rendered label (see RT-012). Switch the bootstrap log to the same safe label rendering.

### RT-012
- severity: low
- file: agent_sdk/routes/admin.py
- description: The service-mint log line (line ~289) renders the caller-supplied label with safe_line_text inside a joined line (`(label=%s)`). safe_line_text's own docstring says joined values must use safe_cell_text. Newlines are collapsed, but a label such as `x) admin key abcd minted (label=y` can fake log structure within the same line.
- fix: Render with safe_cell_text, or wrap the safe_line_text output in %r, so the label's boundaries cannot be forged. Update the C-034 reuse note if safe_cell_text is the right family member here.

### RT-013
- severity: low
- file: agent_sdk/auth/api_keys.py
- description: verify() and list_keys() trust the stored admin/service flags as they are. A record with both set (manual store edit or a future bug) yields Identity(admin=True, service=True) and a listing showing both, even though mint() makes them mutually exclusive.
- fix: In verify() and list_keys(), set `service = bool(record.get("service")) and not bool(record["admin"])` so admin always wins and the two flags can never both be true.

### RT-014
- severity: low
- file: tests/test_gh182_service_key.py
- description: Weak assertions. test_service_key_accepted_on_every_require_identity_route treats asyncio.TimeoutError as a pass and only checks `!= 401`, so a hung route or a 403 from another gate passes.
- fix: Check that the user key gets 401 and the service key gets the same non-auth status the admin key gets on each route. Count timeouts as a pass only when the admin key also streams.

### RT-015
- severity: low
- file: tests/test_gh182_service_key.py
- description: `_admin_routes()` lists only /admin/api routes that already depend on require_admin, so the "refused on every admin route" test is circular. A future /admin/api route added without require_admin is skipped rather than failing. Today every /admin/api route is covered (verified), so this is only a regression gap.
- fix: Enumerate every APIRoute whose path starts with /admin/api. Treat POST /admin/api/keys (which calls require_admin inline) as an explicit exception, and assert that both user and service keys get 403 on all the rest.

### RT-016
- severity: low
- file: tests/test_gh181_prompt_format_neutral.py
- description: Raised in four rounds. `test_market_briefing_prose_exception_unchanged` sits behind `if "MarketBriefing" in text:`, so it passes with no assertions if MarketBriefing is not registered. When it does run, it only checks the substring "[prose card", not the full unchanged annotation the AC pins, nor the "(prose exception) return MarketBriefing(...)" few-shot line. The FundPerformance pbId note is not pinned either. `_section()` also depends on content types being registered at import time.
- fix: Call `get_system_prompt_section(["MarketBriefing"])` (or register it inside the test) and assert unconditionally that MarketBriefing is present. Pin the exact full string " [prose card — a tool emits title, as_of and markdown prose; rendered as plain markdown, not a structured card]" from catalog.py and the "(prose exception) return MarketBriefing(...)" example line.

### RT-017
- severity: low
- file: harness/skills/acceptance/SKILL.md
- description: Phase 0 step 2 mints the service key with label `acceptance-<run-id>` before step 3 checks /health. The run ID is only fixed later, in Phase 2A step 2. A run that aborts between mint and teardown leaves service keys behind, and no step cleans them up.
- fix: Mint after the /health check, use a random suffix known at that point, and add a pre-flight step that revokes leftover `acceptance-*` service keys from earlier aborted runs. Mirror in the template and .claude copies.
