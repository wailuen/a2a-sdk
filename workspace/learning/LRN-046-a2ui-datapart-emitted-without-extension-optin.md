---
id: LRN-046
title: A2UI DataPart emitted unconditionally — requires X-A2A-Extensions opt-in gate
category: protocol
severity: critical
source: redteam
date: 2026-06-17
---

## What happened
The A2UI integration layer emitted `DataPart` payloads containing A2UI surface
data on every response, regardless of whether the client had declared support via
the `X-A2A-Extensions: a2ui` request header. Clients that do not understand A2UI
DataParts received opaque binary artifacts they could not interpret, and the
response was non-conformant because A2A requires extension data to be gated behind
capability negotiation.

## Root cause
The A2UI emit path was added as an unconditional post-processing step after the
main task response was assembled. The capability-negotiation check (presence of
`X-A2A-Extensions: a2ui` in the incoming request) existed in the routing layer
but was not threaded through to the emit function. The emit function had no access
to request context, so it could not perform the gate check.

## Check
```
grep -n 'DataPart\|a2ui\|X-A2A-Extensions' agent_sdk/a2ui/emit.py
# The emit function must check for opt-in before constructing or returning a
# DataPart. Acceptable patterns:
#   if not request_context.extensions.a2ui: return None
#   if 'a2ui' not in extensions: skip DataPart construction
# A DataPart construction path with no conditional guard is non-compliant.
```

## Prevention
When planning any extension-payload emit path (A2UI DataPart, AG-UI CUSTOM,
MCP resource blobs), gate the emit on explicit client opt-in. Pass request context
(headers or a parsed extensions set) into the emit function at design time — do
not add it as a retrofit. Add an integration test that sends a request without
X-A2A-Extensions and asserts the response contains no DataPart artifacts.
