# w044 — GH-152: non-Entra issuers fail closed

From the w043 MCP protocol audit (HIGH). Maintainer ruling 2026-10-10.
Checkable reference: https://github.com/wailuen/a2a-sdk/issues/152#issuecomment-6094590732
Single item. Target: 0.9.0.

---

- [x] `GH-152-F` IdP sign-in admits every account at a non-Entra issuer when no role or group is set ‖ group:G
  - Creates: (modifies `agent_sdk/app.py`, `agent_sdk/config.py`, `agent_sdk/auth/oidc.py` if needed, `tests/test_gh152_idp_settings_boot.py`, `docs/security.md`, `harness/skills/setup/SKILL.md`, `template/.claude/skills/setup/SKILL.md` (lands via commit+push to wailuen/a2a-agent-template per LRN-071; runtime copy is what /acceptance / the harness skill actually executes — implementer runs `git -C template/ commit && git -C template/ push` as an explicit final step), `workspace/adr/a003-oauth-idp-sign-in.md`, `CHANGELOG.md`)
  - Reads: `agent_sdk/app.py` (`_validate_idp_settings`, ~498-526), `agent_sdk/auth/oidc.py` (~293-358, tenant pinning and `validate_id_token`), the ruling comment above
  - Severity: high
  - Root cause: `oidc.py` pins the tenant only when `AGENT_SDK_OAUTH_IDP_ISSUER` is an Entra URL; for any other issuer `tenant_id` is None. If `required_role` and `required_group` are also unset, `validate_id_token` accepts any valid ID token from that issuer, and `_validate_idp_settings` requires only issuer + client_id. So any account at that IdP can approve consent and mint a token for the agent's tools — a fail-open default on the gate that replaces admin-key consent.
  - AC: With `oauth_idp=oidc`, boot fails with a clear message (no secret values) unless the issuer is an Entra tenant pinned by GUID, OR `oauth_idp_required_role` / `oauth_idp_required_group` is set, OR the new explicit opt-out `AGENT_SDK_OAUTH_IDP_ALLOW_ALL_ISSUER_USERS=true` is set. Name the setting `oauth_idp_allow_all_issuer_users` in config (default false). The opt-out is only valid with `oauth_idp=oidc` (boot refuses it otherwise) and logs one WARNING at boot stating that every account at the issuer is admitted.
  - AC: Entra-tenant setups and setups with a role/group behave exactly as before (no new boot failure); `oauth_idp=none` unchanged.
  - AC: Tests: non-Entra issuer + no role/group + no opt-out → boot fails; + role → boots; + group → boots; + opt-out → boots with exactly one WARNING; opt-out without oidc → boot fails; Entra GUID issuer with nothing extra → boots.
  - AC: docs/security.md (Optional IdP sign-in), the setup skill (all copies identical) and ADR-003 (new D-entry citing the ruling URL) document the rule and the opt-out. CHANGELOG `[Unreleased]` entry.
  - SI: SI-2 — boot messages name settings only, never values of secrets.
  - GH: https://github.com/wailuen/a2a-sdk/issues/152
  - Reuses: C-026  # Decide "Entra tenant pinned by GUID" from the return value of `parse_idp_issuer` (`agent_sdk/config.py:38`): non-None means a GUID-pinned Entra tenant. `_validate_idp_settings` (`agent_sdk/app.py`) already calls it but discards the result — keep and use that result. Do NOT write a second host/GUID check in app.py or oidc.py; a second copy could drift from the one oidc.py uses to set `cfg.tenant_id` and reintroduce the fail-open.
  - Peer-repo: `template/.claude/skills/setup/SKILL.md`  # Not a workflows .js file, but the same peer-repo rule (LRN-085/RT-014) applies. `template/` is its own git repo (origin wailuen/a2a-agent-template). Per LRN-071 the edit only reaches downstream agents via `git -C template/ commit && git -C template/ push`. Never `git add template/` in a2a-sdk. (`.claude/skills/setup/SKILL.md` does not exist in a2a-sdk; the "if present" entry was removed from Creates.)
  - AC: Final step — `git -C template/ commit` and `git -C template/ push` the setup-skill edit to wailuen/a2a-agent-template; verify `git -C template/ status` is clean and `git -C template/ log origin/main -1` shows the commit. `template/` is not staged in the a2a-sdk commit.

---

**Archived 2026-10-10 (by /gh-review).** sdk-wave run wf_82d7f2c7-2f0: unit redteam clean by round 3
(also refuses the Microsoft personal-account tenant GUID 9188040d-6c67-4c5b-b112-36a304b66dad);
template setup-skill mirror pushed as wailuen/a2a-agent-template 3e20e01; pre-archive gate 2841
passed, 0 failed; protocol audits found no critical/high. Archive was held only by the uncommitted-tree
guard — commits happen in /sdk-release.
