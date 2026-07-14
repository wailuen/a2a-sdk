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
grep -n 'x-a2a-extensions\|A2UI_EXTENSION_URI\|a2uiClientCapabilities' agent_sdk/routes/a2a.py
# The _capabilities() function must gate A2UI on the X-A2A-Extensions opt-in
# header. Required patterns:
#   request.headers.get("x-a2a-extensions", ...)
#   opted_in = A2UI_EXTENSION_URI in [...]        # computed from the header above
#   (message.metadata or {}).get("a2uiClientCapabilities")
#   return A2uiCapabilities.gated(opted_in, raw)  # C-006
# Since w032's C-006 extraction, the fail-closed `tier="none"` literal no
# longer lives inline in a2a.py — it lives in A2uiCapabilities.gated()
# (agent_sdk/a2ui/translator.py), and _capabilities() computes `opted_in` then
# delegates via gated(opted_in, raw). Absence of the three grep patterns above
# means the opt-in gate has been removed — fail-open. (Confirm the fail-closed
# default itself with: grep -n 'tier="none"' agent_sdk/a2ui/translator.py)
```

## Prevention
When planning any extension-payload emit path (A2UI DataPart, AG-UI CUSTOM,
MCP resource blobs), gate the emit on explicit client opt-in. Pass request context
(headers or a parsed extensions set) into the emit function at design time — do
not add it as a retrofit. Add an integration test that sends a request without
X-A2A-Extensions and asserts the response contains no DataPart artifacts.
