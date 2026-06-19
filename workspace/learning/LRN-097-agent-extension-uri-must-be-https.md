---
id: LRN-097
title: "AgentExtension URIs must use https:// scheme — URN-scheme URIs are silently dropped"
category: protocol
severity: high
source: implement
date: 2026-06-20
---

## What happened

An AgentExtension was declared with a URN-scheme URI (e.g., `urn:example:extension:foo`). The extension registered successfully on the server side, but consumer implementations silently dropped it from their allowlist — the extension was never activated for incoming tasks.

## Root cause

A2A v0.3.0 places no scheme constraint on `AgentExtension.uri` — the field is typed as `string`. However, real-world consumer allowlist heuristics (e.g. Claude.ai and several open-source A2A clients) filter for `https://` scheme and silently skip non-http URIs. The spec does not require this behaviour, but the consumer ecosystem has converged on it. Note: `urn:agui:run:v1` is a deliberate spec-mandated exception (GH-85 deferral) — do not "fix" it to https://.

## Check

```bash
# Grep agent_sdk/ for any AgentExtension URI using urn: scheme (flag these)
grep -rn 'uri=.urn:' agent_sdk/ --include="*.py"
# Expected: zero matches for SDK-owned extensions (urn:agui:run:v1 is a spec-mandated exception)

# Confirm the served card carries https:// URIs for SDK-owned extensions
curl -s <agent-url>/.well-known/agent.json | jq '.capabilities.extensions[].uri'
```

## Prevention

Use `https://` scheme for all SDK-owned `AgentExtension` URIs. Do NOT change `urn:agui:run:v1` — that is a normative URI defined by the AG-UI spec. When in doubt, confirm with `a2a-advisor` whether a given URI is spec-mandated or SDK-invented.
```python
# Correct for SDK-owned extensions
extension_uri = "https://agent-sdk.dev/extensions/my-feature/v1"

# Risky for SDK-owned extensions (silently dropped by most consumers)
extension_uri = "urn:example:extension:my-feature:v1"
```
