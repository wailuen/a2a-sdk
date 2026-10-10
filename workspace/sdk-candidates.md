# SDK issue candidates — w044 (2026-10-10)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: The GH-152 change to the setup skill in the template peer repo is not committed or pushed. It adds the fail-closed rule for non-Entra issuers and the ALLOW_ALL_ISSUER_USERS opt-out docs. `git -C template status --short` shows the file as modified, and origin/main is still at c6a690b. New agents seeded from wailuen/a2a-agent-template will not get the rule or the docs. The LRN-071 Check fails.
- Severity: high
- Component: harness/template
- File: template/.claude/skills/setup/SKILL.md
- Rationale: This is the template scaffold that every downstream agent is created from. That makes it SDK-level work, not agent code. The gap is a missing commit and push in the template repo, plus a redteam rule that should check template/ todos for a clean status and a pushed commit.

## Candidate 2: parse_idp_issuer (config.py:38-70) accepts 9188040d-6c67-4c5b-b112-36a304b66dad as a pinned Entra tenant. That is the Microsoft personal-account (consumers) tenant ID. With no role, group or opt-out set, _validate_idp_settings (app.py:514-530) boots without a warning. oidc.py:336-343 then admits any token whose tid matches, so any personal Microsoft account can sign in and get a token for the agent's tools. This is the same fail-open gap GH-152 closes. The function already refuses the 'consumers' name but not the tenant ID it stands for.
- Severity: high
- Component: security
- File: agent_sdk/config.py
- Rationale: The bug is in the SDK's own sign-in issuer check (agent_sdk/config.py, used by app.py and auth/oidc.py), not in any agent's code. It is a login bypass in the OAuth/OIDC path. Fix: refuse this tenant ID in parse_idp_issuer with the same error as the common/organizations/consumers names. Add it to the test_boot_refuses_multi_tenant_issuer_aliases parameter list. Note the exclusion in docs/security.md and ADR-003 D13.
