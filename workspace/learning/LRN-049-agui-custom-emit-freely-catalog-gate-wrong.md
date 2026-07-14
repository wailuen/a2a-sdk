---
id: LRN-049
title: AG-UI CUSTOM events wrongly gated on catalog membership — must emit freely
category: protocol
severity: medium
source: gh-review
date: 2026-06-18
---

## Observation

The A2UI_UPDATE emit path used `self.catalogs` membership as a gate before
emitting AG-UI CUSTOM events: only types registered in the server's catalog were
allowed through. This mirrors the correct A2A DataPart gate (where `X-A2A-Extensions`
opt-in is required) but is wrong for AG-UI CUSTOM. The AG-UI spec explicitly states
that consumers silently ignore unknown CUSTOM event types; suppressing them at the
server prevents discovery, breaks bootstrapping, and creates an undiscoverable
circular dependency (the catalog must be known to receive the events that would
reveal the catalog).

The A2UI_UPDATE gate should fire only when `tier == "none"` (the agent has declared
no A2UI support at all), not on catalog membership.

## Root Cause

The implementer conflated two distinct gating rules:

- **A2A DataPart gate** — requires explicit client opt-in via `X-A2A-Extensions: a2ui`
  header. Emitting without opt-in violates A2A capability negotiation (LRN-046).
- **AG-UI CUSTOM gate** — no server-side suppression permitted. The spec delegates
  filtering entirely to the consumer. Gating on `self.catalogs` is a false analogy
  with the DataPart rule.

## Prevention

When planning any AG-UI CUSTOM event emit path:

1. Do NOT gate on `self.catalogs` or any server-side type registry membership.
2. The only valid server-side suppression is `tier == "none"` (agent has opted out
   of A2UI entirely).
3. Catalog opt-in (`self.catalogs`) is the correct gate ONLY for A2A DataPart
   delivery where the client must have sent `X-A2A-Extensions: a2ui`.
4. Add a test that confirms a CUSTOM event for a type NOT in `self.catalogs` is
   still emitted when `tier != "none"`.

## Check

```
grep -n 'translate\|allows\|for_custom_emit\|tier' agent_sdk/a2ui/translator.py agent_sdk/routes/ag_ui.py
```

Confirm that the `A2UI_UPDATE` emit in `agent_sdk/routes/ag_ui.py` is gated only
on `tier == "none"` and NOT on `type in self.catalogs` or any catalog-membership
predicate. Since w032's C-006 extraction, `ag_ui.py` no longer calls
`caps.allows()` directly — it calls
`self.capabilities.for_custom_emit()` (`translator.py`) and passes the result
into `translate()`, which applies `allows()` internally. `for_custom_emit()`
must return `self` unchanged when `tier == "none"` (preserving the suppression)
and otherwise force `tier="core+extended"` (catalogs preserved), so `allows()`
downstream can only ever gate on `tier == "none"` for the AG-UI path — never on
catalog membership. The `allows()` method in `translator.py` must return
`False` only when `self.tier == "none"`, and must emit domain types freely
(consumers silently ignore unknown CUSTOM events per the AG-UI spec) — never
suppress based on catalog membership.
