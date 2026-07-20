---
id: LRN-126
title: CSP form-action must be widened on the form-owning document, not the redirect
category: security
severity: high
source: redteam
date: 2026-07-20
---

## What happened
GH-122's fix widened `form-action` CSP to the redirect_uri origin on the 302/303
redirect responses in `oauth.py` (`_redirect_security_headers`), but the actual
`<form>` the user submits lives in `_consent_page`, which still serves bare
`form-action 'self'`. The "Approve does nothing" bug persists in Chromium/Electron.

## Root cause
Chromium/Electron enforces `form-action` for a form submission using the CSP of
the document that *owns the form*, not the CSP header on the resulting 30x hop —
a redirect response never commits as a rendered document, so its CSP (like its
X-Frame-Options) is inert (crbug.com/932518). Tests only asserted header
presence on the 30x response, so this was invisible to unit tests.

## Check
Verify that `_consent_page` / `oauth_authorize_page` / the 401 re-render path in
`oauth_authorize_approve` (agent_sdk/routes/oauth.py) emit `form-action` widened
to the validated redirect_uri origin, not just `'self'`. Grep:
`grep -n "form-action" agent_sdk/routes/oauth.py` — every code path that renders
the consent page HTML must include the widened directive, and a test must assert
the header on the GET/consent-page response, not only on 302/303 responses.

## Prevention
When planning a CSP/security-header fix for any redirect-driven flow (OAuth
consent, form POST-then-redirect), identify which response actually *renders
the document containing the form/action* and apply the directive there — verify
against the response type serving the interactive HTML, never assume the
redirect response's headers apply to the page that initiated it.
