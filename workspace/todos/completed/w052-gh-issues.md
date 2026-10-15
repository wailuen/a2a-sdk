# w052 — GitHub issues 181–182

Sourced from open issues on wailuen/a2a-sdk. The two items are independent.
Run in parallel (group:G1). Runs on top of v0.14.1 (920a820).
Target: 0.15.0 (new public key kind).

---

- [ ] `GH-182` /acceptance and /agent-verify need a narrow test credential when user API keys are disabled ‖ group:G1
  - Creates: (modifies `agent_sdk/auth/identity.py`, `agent_sdk/auth/middleware.py`, `agent_sdk/auth/oauth_tokens.py` (`revoke_by_value`), `agent_sdk/routes/oauth.py` (docstrings), `DESIGN.md`, the API key store under `agent_sdk/auth/` that implements `api_keys.mint`, `agent_sdk/routes/admin.py` (`KeyMintRequest`, `mint_key`, `list_keys`), admin console key UI under `agent_sdk/console/static/` if it mints keys, `harness/skills/acceptance/SKILL.md`, `harness/skills/agent-verify/SKILL.md`, `template/.claude/skills/acceptance/SKILL.md`, `template/.claude/skills/agent-verify/SKILL.md`, new `tests/test_gh182_service_key.py`, `docs/` auth page if one covers key kinds, `CHANGELOG.md`)
  - Reads: `agent_sdk/config.py` (`oauth_idp_disable_api_keys`), `agent_sdk/app.py` (~line 515, 624)
  - Severity: medium
  - Root cause: `require_identity` (middleware.py ~line 140) refuses every non-admin API key when `idp_disable_api_keys` is on, so the admin key is the only non-browser credential. Automated runs then hold a key that also opens `/admin` (credentials, key minting, revocation).
  - Ruling: Checkable reference: https://github.com/wailuen/a2a-sdk/issues/182#issuecomment-6193941983
  - AC: An admin can mint a service key through `POST /admin/api/keys` (`service: true`). `service` and `admin` both true is refused with 4xx. The bootstrap-token mint always yields an admin key and cannot yield a service key.
  - AC: A service key is accepted on A2A, AG-UI and MCP protocol routes with `AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS=true`, while a normal user key is still refused there.
  - AC: A service key is refused (same status as a normal user key) on every `require_admin` surface: key mint/list/revoke, credentials, and every `/admin/api/*` route. Test each route class.
  - AC: The stored key record keeps its kind across restart for every key store (local and shared/table store); existing keys without the field load as normal keys (no migration needed).
  - AC: `GET /admin/api/keys` shows the kind; revoking a service key works and it stops working at once.
  - AC: No secret appears in logs or errors (SI-2); minting a service key is logged like other mints, without the plaintext.
  - AC: `/acceptance` and `/agent-verify` (harness and template copies identical) mint a service key with the admin key, use only the service key for protocol calls, and revoke it at teardown.
  - AC: CHANGELOG `[Unreleased]` lists the new kind under Added with the ruling URL.
  - GH: https://github.com/wailuen/a2a-sdk/issues/182
  - Reuses: C-034  # The new service-key mint log line should render the caller-supplied label through C-034 safe_line_text (C-007 family, agent_sdk/common/redact.py) rather than raw %r. The existing bootstrap log at agent_sdk/routes/admin.py:264 interpolates body.label with %r, so do not copy that pattern. The label is user input and the SI-2 AC requires mint logging with no secret or raw input.
  - SI: SI-5  # The todo changes require_identity/require_admin (agent_sdk/auth/middleware.py:140,160) and has no SI: field. Three other places decide on identity.admin or kind=='api_key' and are missing from Reads/AC. (1) agent_sdk/routes/oauth.py:912 OAuth consent approval: a service key must stay refused there. (2) agent_sdk/tasks/memory.py:185: the admin bypass of task identity binding must not extend to service keys, so a service key must not read other identities' tasks. (3) agent_sdk/auth/oauth_tokens.py:569 revoke_by_value: any api_key caller can revoke any user's OAuth token. With DISABLE_API_KEYS=true, only admin keys can do that today, so a service key would gain cross-user revoke. Add an AC and a test per surface (LRN-224). Also keep Identity.kind == 'api_key' for service keys, using a flag rather than a new kind string. middleware.py:151 and oauth.py:912 branch on kind != 'api_key', so a new kind silently changes behavior.
  - SI: SI-2  # The SI-2 AC must name a hostile no-leak test in tests/test_gh182_service_key.py. It should assert that the plaintext key never appears in caplog for the mint, list, revoke and refused-request paths, and that the refusal body does not reveal the key kind. LRN-292/340/369: SI-2 annotations have repeatedly landed without the named test.

- [ ] `GH-181` A2UI system-prompt section forces "prose" with no way to adapt it ‖ group:G1
  - Creates: (modifies `agent_sdk/a2ui/catalog.py`, new `tests/test_gh181_prompt_format_neutral.py`, `docs/content-types.md` if it quotes the sentence, `CHANGELOG.md`)
  - Reads: `tests/` that pin the prompt text (grep "in prose")
  - Severity: medium
  - Root cause: `get_system_prompt_section()` (catalog.py ~line 263) appends "Describe tool results in prose, using only values the tools returned." after the persona, overriding persona format rules (e.g. markdown tables).
  - Ruling: Checkable reference: https://github.com/wailuen/a2a-sdk/issues/181#issuecomment-6193941256
  - AC: The section no longer tells the model which format to use ("prose" gone from that sentence); it says to summarise tool results for the user in the format the agent's instructions ask for.
  - AC: The safety rules stay word-for-word in meaning: cards are delivered automatically, never write component JSON, use only values the tools returned. A test pins each.
  - AC: The MarketBriefing "prose exception" lines (the card's own `prose` field) are unchanged.
  - AC: No new setting or override hook.
  - GH: https://github.com/wailuen/a2a-sdk/issues/181

---

Archived 2026-10-15 by hand. The pre-archive gate failed on one docs test (tests/test_rt007_component_registry_anchors.py: the new registry entry cited oauth.py:912 and memory.py:185). Fixed by hand by naming the functions instead. Full suite then green. The /oauth/revoke change was narrowed in round 3 to service keys only (admin and user keys unchanged), matching the ruling.
