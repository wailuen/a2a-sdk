# w047 — GitHub issues 160–169

Sourced from open issues on wailuen/a2a-sdk. Rulings 2026-10-13:
Checkable reference: https://github.com/wailuen/a2a-sdk/issues/161#issuecomment-6137224867
Checkable reference: https://github.com/wailuen/a2a-sdk/issues/162#issuecomment-6137225080
Checkable reference: https://github.com/wailuen/a2a-sdk/issues/164#issuecomment-6137225283
Checkable reference: https://github.com/wailuen/a2a-sdk/issues/167#issuecomment-6137225466
Checkable reference: https://github.com/wailuen/a2a-sdk/issues/168#issuecomment-6137225747
GH-160, 163, 165, 166, 169 need no ruling (plain fixes).
Groups run in order G1 → G2 → G3 because of shared files (config.py, app.py, workflow scripts, docs/deployment.md).
Template mirrors: `template/` is its own repo (wailuen/a2a-agent-template). Items that change a mirrored file commit and push it there (LRN-071) and never `git add template/` here.
Target: next release (version chosen at /sdk-release).

---

- [ ] `GH-160` Settings validation errors print raw settings input (incl. MASTER_KEY) ‖ group:G1
  - Creates: (modifies `agent_sdk/config.py`, `tests/test_config.py`, `DESIGN.md`, `CHANGELOG.md`)
  - Reads: `agent_sdk/config.py` (model_config ~82-84, validators ~303-333), `DESIGN.md` (~434), `workspace/learning/LRN-214*`
  - Severity: high
  - Root cause: BaseAgentSettings lacks `hide_input_in_errors=True`; model_validator errors include the whole raw settings dict as `input_value=`, so the tail of MASTER_KEY (or any secret) reaches logs. DESIGN.md:434 already promises otherwise.
  - AC: `hide_input_in_errors=True` on BaseAgentSettings.model_config; a subclass overriding model_config still inherits it.
  - AC: Test: marker MASTER_KEY + DEV_MODE=false + no PUBLIC_URL → `str(ValidationError)` contains no part of the marker (head or tail) and no `input_value`, but still names PUBLIC_URL. Subclass test. CHANGELOG `[Unreleased]` Security entry.
  - SI: SI-2.
  - GH: https://github.com/wailuen/a2a-sdk/issues/160

- [ ] `GH-161` Entra tenant issuer must also require a role, group or explicit opt-out ‖ group:G1
  - Creates: (modifies `agent_sdk/app.py`, `tests/test_gh152_idp_settings_boot.py`, `tests/test_gh152_idp_authorize_flow.py`, `workspace/adr/a003-oauth-idp-sign-in.md`, `docs/security.md`, `harness/skills/setup/SKILL.md`, `template/.claude/skills/setup/SKILL.md` (template repo commit+push), `CHANGELOG.md`)
  - Reads: `agent_sdk/app.py` `_validate_idp_settings` (~527-543), `agent_sdk/auth/oidc.py` (~340-358), `workspace/todos/completed/w044-gh-152-non-entra-fail-closed.md`
  - Severity: high
  - Root cause: boot fail-closed rule applies only when the issuer is not a GUID-pinned Entra tenant; an Entra tenant with no role/group admits every member and guest unless the tenant admin turned on "Assignment required", which the SDK cannot see.
  - AC: With `oauth_idp=oidc`, boot fails (clear message naming settings, no values) for every issuer unless REQUIRED_ROLE, REQUIRED_GROUP or ALLOW_ALL_ISSUER_USERS=true is set (ruling supersedes the w044 Entra exemption). The opt-out keeps its single boot WARNING. Personal-account tenant GUID refusal is unchanged.
  - AC: Tests: Entra GUID issuer + nothing → boot fails; + role → boots; + group → boots; + opt-out → boots with one WARNING; non-Entra cases unchanged; `oauth_idp=none` unchanged.
  - AC: New ADR a003 D-entry citing the 161 ruling URL and stating it supersedes the w044 Entra exemption; docs/security.md and every copy of the setup skill (identical) updated; CHANGELOG `[Unreleased]` under Breaking changes with a **Migration** line (set a role/group, or the opt-out).
  - GH: https://github.com/wailuen/a2a-sdk/issues/161
  - Reuses: C-026  # Keep parse_idp_issuer (agent_sdk/config.py) as the only issuer parser. The new rule (role/group/opt-out required for every issuer) drops the `tenant_id is None` branch in app.py::_validate_idp_settings. The personal-account GUID refusal must stay inside parse_idp_issuer, not move into a second Entra check in app.py.
  - SI: SI-5  # Changes the boot gate that decides who can sign in and approve consent (app.py::_validate_idp_settings), but has no SI: field. Fail closed: every oidc issuer must have a role, group or explicit opt-out. Tests must show no path boots without one.
  - SI: SI-2  # The new boot error must name settings only (AGENT_SDK_OAUTH_IDP_REQUIRED_ROLE/GROUP/ALLOW_ALL_ISSUER_USERS). It must never interpolate the issuer URL, tenant GUID, role or group value. Assert this in the test.

- [ ] `GH-164` wave Parse drops declared Creates:/Modifies: paths ‖ group:G1
  - Creates: (modifies `.claude/workflows/sdk-wave.js`, `harness/workflows/wave-cycle.js`, `.claude/workflows/wave-cycle.js`, `template/.claude/workflows/wave-cycle.js` (template repo commit+push), `harness/wave_scope.py`, `tests/test_wave_scope_extraction.py`, `CHANGELOG.md`)
  - Reads: `harness/workflows/wave-cycle.js` (Parse ~716-817), `.claude/workflows/sdk-wave.js` (~660-672, ~743), `harness/wave_scope.py`
  - Severity: high
  - Root cause: (A) allScope comes only from an AI parse with no deterministic check, so it can drop paths such as `src/config.py`; (B) the file rule rejects lockfiles and dotfiles such as `uv.lock`, `.env.example`.
  - AC: Parse adds a deterministic regex scan of Creates:/Modifies: lines (via the agent call the workflow already uses for file reads), unions it with the AI result, fails Parse if the scan finds paths the AI missed or the union is empty, and logs the final allScope.
  - AC: File rule widened in the prompt text and `harness/wave_scope.py::_looks_like_path` to accept known lockfiles and dotfiles (`uv.lock`, `.env.example`, `package-lock.json`, `.gitignore`, …) while still rejecting directories, globs and a bare extension (keeps RT-001 / LRN-259 intent).
  - AC: Tests in `tests/test_wave_scope_extraction.py` for `(modifies `uv.lock`, `.env.example`, `src/config.py`)` plus the still-rejected cases. sdk-wave.js gets the same Parse change. harness/, .claude/ and template/ wave-cycle.js are byte-identical (template pushed).
  - AC: Do NOT run the modified workflow scripts as part of this wave beyond static/unit checks.
  - GH: https://github.com/wailuen/a2a-sdk/issues/164

- [ ] `GH-167` Text fallback replaces ASCII ( ) , with look-alikes in standalone slots ‖ group:G1
  - Creates: (modifies `agent_sdk/common/redact.py`, `agent_sdk/models/content_types.py`, `tests/test_content_types.py`, `tests/test_gh156_mcp_text_ids.py`, `DESIGN.md` §4.0, `docs/content-types.md`, `CHANGELOG.md`)
  - Reads: `agent_sdk/common/redact.py` (~112-202), `agent_sdk/models/content_types.py` (`_sanitize_cell` ~109-120, renderers), CHANGELOG RT-002/RT-005/GH-130 entries
  - Severity: medium
  - Root cause: every to_plain_text slot goes through safe_cell_text, which swaps ( ) [ ] < > = , : for look-alikes even where the value sits alone on its own line and cannot forge structure.
  - AC: New standalone-slot helper (line-break and control-char collapse, length cap, no separator swap). Used for slots that sit alone on a line with nothing joined after them (titles, names on their own line, summaries, as-of headers). Joined slots keep safe_cell_text. `safe_cell_text` behavior is unchanged.
  - AC: Ids move to their own labelled line where they were joined to a name (e.g. EntityList `  id: 59199-40`), so names keep ASCII; GH-156 tests (ids reach text, MCP text) updated to match and still pass.
  - AC: Tests: `Toshiba (Tokyo)` and `Smith, John` survive unchanged in title, name and summary slots; existing separator/structure-forgery tests distinguish standalone from joined slots and still prove a hostile value cannot forge a row, column or `(id)`/`k=v` pair.
  - AC: ContentModel contract docstring, DESIGN.md §4.0, docs/content-types.md, CHANGELOG `[Unreleased]` (cite GH-130/RT-005 trade-off).
  - GH: https://github.com/wailuen/a2a-sdk/issues/167
  - Reuses: C-007  # The planned standalone-slot helper (collapse line breaks and control chars, cap length, no separator swap) is exactly what agent_sdk/common/redact.py::safe_error_text(value, max_len=N) already does. Build the new helper as a thin wrapper over safe_error_text. Do not add a third control-char map next to _CONTROL_CHAR_MAP/_CONTROL_CHARS.
  - Reuses: C-030  # The ids moved onto their own labelled line (e.g. EntityList '  id: 59199-40') must still render through safe_id_text (via content_types._safe_id). Neither the new standalone helper nor safe_cell_text should handle them. Otherwise the GH-156 byte-exact id guarantee breaks.

- [ ] `GH-169` A2UI system-prompt section tells the model to hand-write component JSON ‖ group:G1
  - Creates: (modifies `agent_sdk/a2ui/catalog.py`, `tests/test_a2ui_wire.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/a2ui/catalog.py` (`get_system_prompt_section` ~257-289), `agent_sdk/app.py` (~684-688), `agent_sdk/agent/loop.py` (~1614)
  - Severity: medium
  - Root cause: the section says "wrap it as an A2UI Standard Profile component" and shows JSON examples, but cards only come from tools with `emits=`; model-written card JSON reaches users as raw text and is replayed as history, so the model copies the pattern and invents values.
  - AC: The section says tools deliver these cards to the user automatically; the model must not write component JSON in its reply and should describe results in prose using only values tools returned. MarketBriefing note and the examples heading reworded as reference shapes of tool output. FundPerformance "never invent" caveat kept. `allowed_components` filtering and compact schemas unchanged.
  - AC: Regression test: no "wrap it as" wording; an explicit "do not write component JSON" line present; existing wire tests updated, not skipped. CHANGELOG `[Unreleased]` entry.
  - GH: https://github.com/wailuen/a2a-sdk/issues/169
  - Reuses: C-020  # Rewording the examples heading and MarketBriefing note in catalog.py must keep _FEW_SHOT_EXAMPLES/_COMPACT_SCHEMAS in step with the registered ContentModel fields. Reuse the existing parity helpers in tests/test_a2ui_wire.py (_declared_wire_keys, _compact_schema_top_level_keys) in the regression test rather than writing new string checks.
  - Modifies: `agent_sdk/routes/mcp.py`, `tests/test_rt001_mcp_dispatch_no_value_log.py`  # RT-001: _dispatch catch-all logged exc via logger.exception (LRN-214); now class + frame_locations only

- [ ] `GH-162` Document and warn: OAuth/IdP sign-in requires one replica ‖ group:G2
  - Creates: (modifies `docs/deployment.md`, `agent_sdk/config.py`, `agent_sdk/app.py`, new `tests/test_gh162_single_replica_warning.py`, `DESIGN.md`, `CHANGELOG.md`, new `workspace/todos/deferred/gh162-shared-oauth-state.md`)
  - Reads: `agent_sdk/auth/oidc.py` (`IdpFlowStore` ~398), `agent_sdk/auth/oauth_tokens.py` (~140-144, ~454-463), `agent_sdk/routes/mcp.py` (~234), `docs/deployment.md` (~5-10, ~217-231), `agent_sdk/config.py` (~305-309)
  - Severity: high
  - Root cause: IdP flows, consent tickets, auth codes, access tokens and MCP sessions are per-process; docs recommend `minReplicas: 2`, contradicting DESIGN.md's one-process rule, so sign-in breaks across replicas.
  - AC: docs/deployment.md: OAuth/IdP sign-in requires exactly one replica; the Replicas section no longer recommends 2 when sign-in is on; Known-limitations lists IdP flows, auth codes, access tokens, MCP sessions and cross-replica revoke lag.
  - AC: config.py comment claiming multi-replica support corrected. Boot logs one WARNING naming the single-replica requirement when a shared (Azure Table) store backend is configured with OAuth or IdP sign-in on; no warning when sign-in is off or on the local SQLite store. Tests for each case.
  - AC: Deferred note records shared sign-in storage (IdP flows, codes, access tokens, MCP sessions with atomic single-use deletes) as future work citing the 162 ruling. CHANGELOG `[Unreleased]` entry.
  - GH: https://github.com/wailuen/a2a-sdk/issues/162
  - Reuses: C-024  # The deferred note for shared sign-in storage (IdP flows, codes, access tokens, MCP sessions with atomic single-use deletes) should name the planned C-024 BoundedTtlSingleUseStore (and its C-028 per-source quota option) as the abstraction to back with a shared store. It should not describe a new, separate store design.
  - SI: SI-2  # Touches config.py's credential-store backend settings with no SI: field. The new single-replica WARNING fires when the Azure Table backend is configured. It must not interpolate azure_storage_connection_string (a SecretStr), the account name or table names. Test that the warning text contains no part of a marker connection string.

- [ ] `GH-163` Admin route to revoke a user's tokens by identity ‖ group:G2
  - Creates: (modifies `agent_sdk/auth/oauth_tokens.py`, `agent_sdk/routes/admin.py`, `agent_sdk/console/static/console.js`, new `tests/test_gh163_revoke_user.py`, `DESIGN.md`, `workspace/adr/a003-oauth-idp-sign-in.md`, `CHANGELOG.md`)
  - Reads: `agent_sdk/auth/oauth_tokens.py` (~101, ~379-380, ~454-523), `agent_sdk/auth/oidc.py` (~344), `agent_sdk/routes/admin.py` (~254-308)
  - Severity: high
  - Root cause: tokens can be revoked only by token value, client id or family id, none of which an operator holds; removing a user in Entra takes up to SESSION_HOURS to bite.
  - AC: `OAuthTokenStore.list_identities()` returns per-user summaries (user, client id(s), family count, earliest created, latest expiry) with no token values or hashes. `revoke_user(user)` revokes every refresh family for that user and drops their access tokens in this process; returns the count.
  - AC: `GET /admin/api/oauth/identities` and `DELETE /admin/api/oauth/identities/{user}` (URL-encoded `tid:oid`), admin-only; idempotent 200 with revoked count; log the revocation without token material.
  - AC: Console "Signed-in users" panel lists identities with a Revoke action.
  - AC: Tests: only the target user's families are revoked; refresh after revoke → invalid_grant; non-admin and OAuth callers get 401/403; listing never contains token values or hashes. Docs note the per-process access-token caveat (GH-162). CHANGELOG `[Unreleased]` entry.
  - SI: SI-2.
  - GH: https://github.com/wailuen/a2a-sdk/issues/163
  - Reuses: C-007  # The DELETE /admin/api/oauth/identities/{user} path value is caller-supplied. Pass it through sanitize_text/safe_error_text before it reaches the revocation log line or any error detail. Never log or echo it raw.
  - SI: SI-5  # Adds two admin data routes, but SI: lists only SI-2. Both GET and DELETE /admin/api/oauth/identities must use dependencies=[Depends(require_admin)], like every other /admin/api route in agent_sdk/routes/admin.py. An OAuth or IdP user identity must be refused, not just an anonymous caller (the AC test covers this, but the plan does not list SI-5).

- [ ] `GH-165` Archive backfills PRD Implementation: markers but never Test: markers ‖ group:G2
  - Creates: (modifies `harness/workflows/wave-cycle.js`, `.claude/workflows/wave-cycle.js`, `template/.claude/workflows/wave-cycle.js` (template repo commit+push), `.claude/workflows/sdk-wave.js`, `CHANGELOG.md`)
  - Reads: `harness/workflows/wave-cycle.js` (~12, ~2642-2644), `.claude/workflows/sdk-wave.js` (~2312), `harness/skills/analyze/SKILL.md` (~68)
  - Severity: medium
  - Root cause: Archive step 3 replaces `Implementation: [pending]` only; `Test: [pending]` written by /analyze is never filled.
  - AC: Archive step 3 also fills `Test: [pending]` with `tests/<file>.py::<test_name>` for tests that exist and passed in this wave (from tests/ paths in allScope and test names cited in the wave file); otherwise leaves `[pending]`. Phase detail text updated. Same change in sdk-wave.js. All three wave-cycle.js copies byte-identical (template pushed).
  - AC: Do NOT run the modified workflow scripts as part of this wave beyond static checks.
  - GH: https://github.com/wailuen/a2a-sdk/issues/165

- [ ] `GH-166` IdP authorization code written to the uvicorn access log ‖ group:G3
  - Creates: (modifies `agent_sdk/observability/logging.py`, `agent_sdk/app.py`, `tests/test_gh152_idp_no_secret_leak.py`, `workspace/todos/deferred/w042-phase-medium-low.md`, `docs/deployment.md`, `docs/security.md`, `DESIGN.md`, `CHANGELOG.md`)
  - Reads: `agent_sdk/auth/oidc.py` (~233), `agent_sdk/routes/oauth.py` (~792), `workspace/todos/deferred/w042-phase-medium-low.md` (RT-009)
  - Severity: high
  - Root cause: `response_mode=query` puts `code` and `state` in the callback URL, and nothing strips query strings from `uvicorn.access` records.
  - AC: A logging filter on `uvicorn.access`, installed idempotently from build_app and always on, removes the query string from any path under `/oauth/` (handles uvicorn's args tuple); other paths keep their query.
  - AC: Test: after build_app, a uvicorn.access-shaped record for `GET /oauth/idp/callback?code=X&state=Y` formats without X or Y; a non-/oauth path keeps its query.
  - AC: docs/deployment.md and docs/security.md say the SDK strips /oauth query strings from uvicorn's access log only; proxies and ingress logs are not covered (mention `--no-access-log`). w042 RT-009 deferred entries cross-referenced as resolved. CHANGELOG `[Unreleased]` Security entry.
  - SI: SI-2.
  - GH: https://github.com/wailuen/a2a-sdk/issues/166

- [ ] `GH-168` AG-UI history messages hard-truncated at 4000 chars ‖ group:G3
  - Creates: (modifies `agent_sdk/routes/ag_ui.py`, `agent_sdk/config.py`, `tests/test_ag_ui.py` or new `tests/test_gh168_agui_truncation.py`, `uv.lock` (resynced, version 0.8.0 to 0.11.0 plus tzdata), `tests/test_ag_ui_group_b.py`, `tests/test_gh148_reuse_kind_substitution.py`, `tests/test_gh159_reject_non_text_parts.py`, `DESIGN.md` §5.3, `docs/protocols.md`, `docs/deployment.md`, `CHANGELOG.md`)
  - Reads: `agent_sdk/routes/ag_ui.py` (`MAX_MESSAGE_CHARS` ~71, `_fold_history` ~79-132)
  - Severity: medium
  - Root cause: every replayed message is cut to its first 4000 chars with no marker, so ids at the end are lost and the model invents them.
  - AC: New setting `AGENT_SDK_AGUI_MAX_MESSAGE_CHARS` (default 32000, validated minimum e.g. 1000) replaces the fixed constant.
  - AC: When a message exceeds it, keep the start and the end with an explicit `[... N chars omitted ...]` marker in the middle (marker counted within the limit); control-char stripping still happens before the cut; warning still logged.
  - AC: Tests: over-limit assistant message keeps its tail ids and the marker; setting overrides default; invalid setting fails boot; under-limit messages unchanged. DESIGN.md §5.3 (~339), docs/deployment.md, CHANGELOG `[Unreleased]`.
  - GH: https://github.com/wailuen/a2a-sdk/issues/168
  - SI: SI-2  # Changes transport code (agent_sdk/routes/ag_ui.py _fold_history) and adds a new setting, with no SI: field. The truncation warning must keep logging only lengths, never message content. The marker must hold only the omitted-char count. An invalid AGENT_SDK_AGUI_MAX_MESSAGE_CHARS must fail boot without echoing the value (relies on GH-160 hide_input_in_errors).

---

Archived 2026-10-13 by hand: the wave hit its phase redteam budget (8 rounds). Highs RT-001/RT-002 fixed by hand; RT-007 (GH-162 warning scope) ratified at https://github.com/wailuen/a2a-sdk/issues/162#issuecomment-6142451447. Pre-existing A2UI high filed as GH-170. Remaining mediums/lows in workspace/todos/deferred/w047-*.md. Shipped in v0.12.0.
