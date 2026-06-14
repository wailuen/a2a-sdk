---
id: LRN-004
title: CORS preflight (OPTIONS 204) must include Access-Control-Expose-Headers
category: protocol
severity: medium
source: redteam
date: 2026-06-14
---

## What happened

GH #8 — the CORS preflight response (OPTIONS → 204) included `Allow-Origin`, `Allow-Methods`, `Allow-Headers` but omitted `Access-Control-Expose-Headers`. Some browser user-agents refuse to expose non-listed headers, silently preventing them from reading the `WWW-Authenticate` 401 challenge, which breaks OAuth discovery start.

## Root cause

The preflight branch in cors.py was written separately from the non-preflight path and the `_EXPOSE_HEADERS` constant was not applied to it.

## Check

Send `OPTIONS` with `Access-Control-Request-Method: POST` to any protected route. Response must include `access-control-expose-headers: WWW-Authenticate, ...`.

## Prevention

When touching cors.py, verify that the preflight and non-preflight paths include the same `expose-headers` value. Add a TestClient test that checks the 204 preflight response headers explicitly.
