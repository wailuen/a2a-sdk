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

Consumer allowlist implementations filter AgentExtension URIs for the `https://` scheme. A URN-scheme URI does not match this filter and is silently discarded. No error is returned; the extension simply does not appear in the negotiated extension set.

## Check

Inspect the negotiated extensions in the task lifecycle or agent card response. If an extension you declared is absent:
```bash
# Check the agent card extensions field
curl -s <agent-url>/.well-known/agent.json | jq '.capabilities.extensions'
```
If the URI scheme is not `https://`, the consumer will drop it.

## Prevention

Always use `https://` scheme URIs for AgentExtension declarations:
```python
# Correct
extension_uri = "https://example.com/extensions/my-feature/v1"

# Will be silently dropped by consumers
extension_uri = "urn:example:extension:my-feature:v1"
```
Treat URN-scheme extension identifiers as not supported in interoperable A2A deployments until the consumer ecosystem broadens its allowlist.
