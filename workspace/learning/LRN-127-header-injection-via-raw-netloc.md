---
id: LRN-127
title: CSP directive injection via raw redirect_uri netloc interpolation
category: security
severity: high
source: redteam
date: 2026-07-20
---

## What happened
`_redirect_security_headers` in `agent_sdk/routes/oauth.py:281` builds the CSP by
interpolating raw `f"{parsed.scheme}://{parsed.netloc}"` from a DCR-registered
redirect_uri. `_valid_redirect_uri` (lines 150-163) only blocks control chars and
length, so a netloc like `evil.com;frame-ancestors *;/cb` injects a duplicate
`frame-ancestors *` directive, which browsers honor over the intended `'none'`.

## Root cause
Validation guarded against control-char/length attacks but not against
CSP-significant characters (`;`, `'`, `"`, space) in the netloc, and the header
builder trusted the unsanitized parsed component instead of reconstructing the
origin from validated parts.

## Check
grep `agent_sdk/routes/oauth.py` for `parsed.netloc` used inside an f-string that
feeds a `Content-Security-Policy` (or any header) value; confirm none exist. Also
verify `_valid_redirect_uri` rejects any netloc/URL containing `;`, `'`, `"`, or
whitespace, with a regression test asserting
`https://evil.com;frame-ancestors *;/cb` is rejected.

## Prevention
When planning any feature that reflects a URL/origin into an HTTP header (CSP,
Location, CORS), require the origin be rebuilt from validated components
(`hostname` + numeric `port`), never interpolated from raw `netloc`/query/path;
and require redirect_uri validators to deny CSP/header-significant characters,
not just control chars.
