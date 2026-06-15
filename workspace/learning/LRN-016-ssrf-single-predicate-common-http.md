---
id: LRN-016
title: SSRF IP-block logic must live in agent_sdk/common/http.py — never duplicated
category: security
severity: high
source: GH-24 (2026-06-15)
---

# LRN-016 — SSRF guard: single `_is_non_public_ip` predicate in `common/http.py`

## Root cause

The RFC 1918 / loopback / link-local / reserved / multicast IP-block logic was
duplicated independently in two places:
- `agent_sdk/sources.py:_on_request` (async DNS re-check per request hop)
- `agent_sdk/credentials/fields.py:validate_credential_url` (sync check at save time)

Duplicate implementations create drift risk: a fix or extension to one copy
(e.g. adding a new blocked range) may not be applied to the other.

## Fix

Single shared predicate in `agent_sdk/common/http.py`:

```python
def _is_non_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )
```

Both `sources.py` and `credentials/fields.py` import and call this function.
`safe_get()` in the same module also uses it.

## Rule going forward

**`_is_non_public_ip` in `agent_sdk/common/http.py` is the single source of truth
for the SSRF IP deny-list.** Never inline equivalent logic elsewhere. Any change
to the blocked ranges (e.g. adding IPv6 ranges) must be made here only.

**`safe_get(url)` in `agent_sdk/common/http.py` is the approved escape hatch**
for tool code that must fetch a user-supplied URL outside a `SourceAdapter`.
SI-1 bans bare `httpx` in tools — use `safe_get` instead. It:
- Resolves the hostname via async DNS
- Blocks non-public addresses (including `169.254.169.254` IMDS)
- Disables redirect-following (open-redirect SSRF vector)

Never add a second URL-fetching helper. Extend `safe_get` if more options are needed.
