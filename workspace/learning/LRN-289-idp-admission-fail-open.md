---
id: LRN-289
title: IdP sign-in admits any user of a non-Entra issuer with no role/group
category: security
severity: high
source: protocol-audit
date: 2026-10-10
---

## What happened
`agent_sdk/auth/oidc.py` pins the tenant only for Entra issuers. For Okta, Google or Auth0, `tenant_id` is None. With `required_role` and `required_group` unset, `validate_id_token` accepts any valid ID token, and `_validate_idp_settings` in `app.py` only demands issuer and client_id.

## Root cause
The IdP admission gate defaults to open when no tenant pin, role or group is configured.

## Check
Verify a test that boots with a non-Entra issuer and no role/group and expects a startup error. `grep -n "ALLOW_ANY_USER\|oauth_idp_required" agent_sdk/app.py` must show the fail-closed check in `_validate_idp_settings`.

## Prevention
When planning any identity-provider or consent gate, require that startup refuses to boot unless a restriction (tenant GUID, role or group) is set, with an explicit opt-in flag and warning for open admission.
