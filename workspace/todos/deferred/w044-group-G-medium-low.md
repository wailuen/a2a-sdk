wave: w044
group: G
date: 2026-10-10
status: non-blocking (medium/low)

Non-blocking — these did not block w044's archive. Address opportunistically or fold into a future wave.

Findings were accumulated across every unit redteam round for group G and deduped by file+description. Redteam IDs restart each round, so each heading carries its round number (R1–R3). Several findings recur across rounds with different wording. They are kept separately because their descriptions differ, and the theme index below groups them. All are flagged sdkCandidate.

## Theme index

- ALLOW_ALL_ISSUER_USERS warning misstates the gate (fires when role/group/tenant pin is active) and/or is logged before later boot failures: R1 RT-002, R2 RT-003, R3 RT-002
- Docs contradict D13 (DESIGN.md §5.5 "Membership lives in Entra only", docs/security.md "managed in Entra", ADR-003 D7 boot-failure list): R1 RT-003, R2 RT-002, R3 RT-001
- Fail-closed rule lives only in the boot check, not in OidcConfig / OidcRelyingParty: R1 RT-004
- parse_idp_issuer called twice instead of reusing the boot-check result (C-026 note not followed): R1 RT-005
- Blank / whitespace REQUIRED_ROLE or REQUIRED_GROUP handling and missing edge-case tests: R1 RT-006, R2 RT-004

## Findings

### R1 RT-002 — medium — agent_sdk/app.py
_validate_idp_settings (app.py ~515-519) logs 'every account at the configured issuer is admitted' whenever the opt-out is set. That includes cases where the opt-out changes nothing: REQUIRED_ROLE or REQUIRED_GROUP is set (the claim check in oidc.py:348-358 still runs), or the issuer is a GUID-pinned Entra tenant. The warning then misstates the security gate. It is also logged before later checks that can still fail boot (ONE_TIME_CONSENT conflict, missing PyJWT), so a failed boot can still leave an 'admitted' warning in the logs.
- Fix: Log the WARNING only when the opt-out actually relaxes the gate (tenant_id is None and no role or group is set). When the opt-out is redundant, either log nothing or log a short note that it has no effect. Move the warning after every remaining raise path in _validate_idp_settings. Add a test: opt-out + REQUIRED_ROLE + Okta issuer produces no 'every account' warning.

### R1 RT-003 — medium — DESIGN.md
Three docs still describe the old gate and now contradict D13. DESIGN.md §5.5 IdP addendum (line 399) says 'Membership lives in Entra only' and does not mention the non-Entra fail-closed rule or AGENT_SDK_OAUTH_IDP_ALLOW_ALL_ISSUER_USERS. docs/security.md line 45 says 'Who may sign in is managed in Entra', which is wrong for non-Entra issuers, two bullets above the new rule. The 'Boot DOES fail for:' list in ADR-003 D7 leaves out the D13 refusal and the opt-out-without-oidc refusal.
- Fix: Add one sentence to the DESIGN.md §5.5 addendum (or the §6 GH-152 bullets) stating the D13 rule and the opt-out. In docs/security.md, change line 45 to say membership is managed at the IdP (Entra assignment, or role/group for other issuers). Add the D13 refusals to the ADR-003 D7 boot-failure list.

### R1 RT-004 — low — agent_sdk/auth/oidc.py
The fail-closed rule is enforced only in AgentApp._validate_idp_settings. OidcConfig and OidcRelyingParty have no defense of their own. An OidcConfig with tenant_id=None, required_role=None and required_group=None builds fine, and validate_id_token (oidc.py:336-358) then accepts any valid token from the issuer. Any future code path that builds the relying party outside build_app() would bring the GH-152 fail-open back without a warning.
- Fix: Add `allow_all_issuer_users: bool = False` to OidcConfig, pass it in from app.py:810-818, and raise ValueError in OidcRelyingParty.__init__ when tenant_id is None, no role or group is set, and the flag is False. The boot check and the relying party then hold the same rule.

### R1 RT-005 — low — agent_sdk/app.py
The todo's Reuses C-026 note says to keep and use the parse_idp_issuer result from _validate_idp_settings. Instead, build_app calls parse_idp_issuer(settings.oauth_idp_issuer) a second time at app.py:814 to set OidcConfig.tenant_id. Both calls use the same function, so they cannot drift today. But the gate decision and the tenant pinning are still computed separately, and the instruction was not followed.
- Fix: Have _validate_idp_settings return the tenant_id (or store it on self). Pass that value to OidcConfig(tenant_id=...) so the gate and the relying party share one result.

### R1 RT-006 — low — tests/test_gh152_idp_settings_boot.py
Two edge cases have no test. First, an empty REQUIRED_ROLE or REQUIRED_GROUP: `AGENT_SDK_OAUTH_IDP_REQUIRED_ROLE=` is a common .env pattern and gives "" instead of None. It is refused today only because of truthiness, and nothing pins that. Second, the opt-out combined with a role or group, or with an Entra issuer: nothing checks the warning behavior there (see R1 RT-002).
- Fix: Add parametrized cases: Okta issuer + AGENT_SDK_OAUTH_IDP_REQUIRED_ROLE='' must raise, and the same for REQUIRED_GROUP=''. Also add Okta + opt-out + role, asserting the boot result and the warning behavior chosen for R1 RT-002.

### R2 RT-002 — medium — docs/security.md
[SDK] The IdP section still says 'Who may sign in is managed in Entra (enterprise application "Assignment required"), not in the SDK.' (docs/security.md, around line 44). Three bullets later the new GH-152 bullet says the SDK refuses to boot unless a role, group or opt-out limits who may sign in. For non-Entra issuers the old sentence is now false, and the two bullets give operators conflicting guidance.
- Fix: Reword the old bullet, for example: 'On Entra, who may sign in is managed in Entra (Assignment required). For other issuers the SDK requires a role or group, or the explicit opt-out (see below).'

### R2 RT-003 — low — agent_sdk/app.py
[SDK] When AGENT_SDK_OAUTH_IDP_ALLOW_ALL_ISSUER_USERS=true is set together with REQUIRED_ROLE or REQUIRED_GROUP, app.py:515-519 still logs 'every account at the configured issuer is admitted'. That is false: oidc.py:348-358 still enforces the role or group. The warning also fires for a GUID-pinned Entra issuer, where 'issuer' really means 'tenant'. No test covers opt-out combined with a role or group. Operators reading boot logs get a wrong security statement.
- Fix: Log the 'every account' WARNING only when the opt-out actually takes effect: tenant_id is None and neither role nor group is set. When the opt-out is redundant, log a short note that it is ignored because a role, group or tenant pin is active. Add a test: opt-out plus a role produces no 'every account' warning, and the role is still enforced.

### R2 RT-004 — low — agent_sdk/app.py
[SDK] The gate at app.py:520-523 uses Python truthiness on oauth_idp_required_role / oauth_idp_required_group. A whitespace-only value such as AGENT_SDK_OAUTH_IDP_REQUIRED_ROLE=' ' passes the boot check. At runtime no role claim ever equals ' ', so every sign-in is denied with missing_role, and boot gives no error. This fails closed, so it is not a security hole, but the misconfiguration goes unreported, which is what the boot check exists to catch.
- Fix: Strip role and group in a config.py field_validator and turn blank values into None. Then a blank value hits the existing boot refusal with a clear message, and OidcConfig never receives a whitespace claim value.

### R3 RT-001 — medium — DESIGN.md
DESIGN.md section 5.5 'IdP sign-in addendum' (line 399) still says 'Membership lives in Entra only' and lists the boot refusals without the new D13 rule. It never says that a non-Entra issuer fails boot unless REQUIRED_ROLE, REQUIRED_GROUP or AGENT_SDK_OAUTH_IDP_ALLOW_ALL_ISSUER_USERS is set. docs/security.md, ADR-003 D13, the setup skill and CHANGELOG were updated, but the repo's main design spec now disagrees with the code.
- Fix: Add one sentence to the DESIGN.md section 5.5 addendum, next to the one-time-consent refusal. It should say that with a non-Entra issuer, boot refuses oidc unless a required role or group is set or AGENT_SDK_OAUTH_IDP_ALLOW_ALL_ISSUER_USERS=true. The opt-out logs one WARNING and is refused without oidc. Cite ADR-003 D13.

### R3 RT-002 — low — agent_sdk/app.py
In _validate_idp_settings (lines 514-519), the ALLOW_ALL_ISSUER_USERS warning is logged before the checks that can still fail boot: the ONE_TIME_CONSENT conflict at line 527 and the missing PyJWT import at line 532. A boot that is about to fail therefore first logs that every account at the issuer 'is admitted', which misleads anyone reading the logs.
- Fix: Move the opt-out logger.warning to the end of _validate_idp_settings, after the one-time-consent and jwt-import checks. Keep the fail-closed raise where it is. Add a test that combines ALLOW_ALL_ISSUER_USERS with ONE_TIME_CONSENT and asserts that no opt-out warning is logged.
