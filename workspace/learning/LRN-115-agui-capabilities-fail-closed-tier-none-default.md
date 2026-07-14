---
id: LRN-115
title: AG-UI _capabilities() fail-closed tier="none" default is intentional — do not "align" it to spec's tier="core"
category: protocol
severity: low
source: gh-review
date: 2026-07-13
---

## Observation

`_capabilities()` in `agent_sdk/routes/ag_ui.py` returns
`A2uiCapabilities.gated(False, None)` when the incoming AG-UI run body has no
`forwardedProps` or no `forwardedProps.a2uiClientCapabilities` key — i.e. when
the client made no explicit capability claim at all. `gated(False, ...)`
resolves to `A2uiCapabilities(tier="none")`; that literal now lives inside
`A2uiCapabilities.gated()` in `agent_sdk/a2ui/translator.py` (extracted there
as C-006 so both the A2A and AG-UI transports share one fail-closed
definition instead of each hardcoding it). This is a deliberate fail-closed
default: an AG-UI client that says nothing about A2UI support is treated as
*not* supporting it, so the server suppresses `A2UI_UPDATE` CUSTOM frames
rather than emitting them speculatively.

This reads as inconsistent with `A2uiCapabilities.from_metadata(None)`, whose
own default is `tier="core"` (fail-open), and with the A2UI spec's stated
default tier of `"core"` for clients that don't negotiate. GH-74 confirmed
this divergence is intentional, not a bug: `_capabilities()` and
`from_metadata()` answer different questions. `from_metadata()` defaults a
*parsed capability payload* that is already known to exist (e.g. a metadata
dict pulled from a stored task) — the caller has already established the
client is A2UI-aware. `_capabilities()` defaults the *absence of any claim in
a raw wire request* — the caller has established nothing about the client at
all. Fail-open in the first case is a reasonable default for an
already-scoped payload; fail-open in the second case would mean every
AG-UI-only client that has never heard of A2UI silently starts receiving
CUSTOM frames it didn't ask for.

## Root Cause

Not a code defect — a naming/proximity trap. `_capabilities()` and
`A2uiCapabilities.from_metadata()` live in the same function family (one
calls the other), share the same return type, and both have a "default when
input is missing" branch, inviting the assumption that the two defaults
should match. They intentionally don't: one is a negotiation fail-closed
gate at the network boundary, the other is a payload-parsing fail-open
convenience for already-trusted internal callers. This LRN exists because the
sibling decision (LRN-049, on the CUSTOM-event catalog gate in the same
route/translator family) already has a doc recording its rationale, and this
one didn't — a documentation gap, not a behavioral one.

## Prevention

1. Do NOT "fix" `_capabilities()` to default to `tier="core"` on a missing
   `a2uiClientCapabilities` key in order to align it with
   `from_metadata(None)` or with the A2UI spec's stated default tier. That
   change would silently start streaming `A2UI_UPDATE` CUSTOM frames to
   AG-UI clients that never opted in, which is a capability-negotiation
   violation (see LRN-046 in `agent_sdk/a2ui/translator.py`'s history), not a
   parity fix.
2. `_capabilities()`'s fail-closed default and `from_metadata()`'s fail-open
   default are answering different questions (raw-request absence-of-claim
   vs. parsing an already-scoped payload) and must not be forced to match.
3. If a future redteam or spec-conformance pass flags this asymmetry again,
   treat it as already-adjudicated (GH-74) and point to this LRN and
   `tests/test_gh74_ag_ui_capabilities_fail_open.py` rather than re-opening
   the decision.
4. Any change to `_capabilities()`'s default must keep
   `test_capabilities_absent_key_returns_none_tier` and
   `test_capabilities_absent_forwardedProps_returns_none_tier` green — those
   two tests exist specifically to pin the fail-closed default.
5. The fail-closed `tier="none"` literal itself lives in
   `A2uiCapabilities.gated()` (`agent_sdk/a2ui/translator.py`), not in
   `agent_sdk/routes/ag_ui.py` — that extraction (C-006) is intentional so
   the A2A and AG-UI transports cannot drift independently. Do not read the
   literal's absence from `ag_ui.py` as the fail-closed default having been
   removed; confirm it via the `gated(False, ...)` call site and via
   `translator.py` instead.
6. Whenever a later round in the same wave refactors code an earlier LRN
   documents (e.g. this C-006 extraction moving the literal out of
   `ag_ui.py`), re-verify that LRN's Observation/Prevention/Check against the
   final landed code before archiving it — do not archive a Check that greps
   for a literal the refactor already moved elsewhere.

## Check

```
grep -n 'def _capabilities\|gated(False' agent_sdk/routes/ag_ui.py
grep -n 'tier="none"' agent_sdk/a2ui/translator.py
```

Confirm `_capabilities()` in `agent_sdk/routes/ag_ui.py` still calls
`A2uiCapabilities.gated(False, None)` when `forwardedProps` is missing or
lacks an `a2uiClientCapabilities` key, and that the fail-closed
`tier="none"` literal it delegates to still lives in
`A2uiCapabilities.gated()` in `agent_sdk/a2ui/translator.py` (not rewritten
to fall back to `tier="core"` in either file). Executable proof lives in
`tests/test_gh74_ag_ui_capabilities_fail_open.py`:
`test_capabilities_absent_key_returns_none_tier` and
`test_capabilities_absent_forwardedProps_returns_none_tier` assert the
fail-closed tier directly, while
`test_no_a2ui_update_when_capabilities_absent` and
`test_no_a2ui_update_when_no_forwarded_props` assert the resulting behavior
end-to-end (zero `A2UI_UPDATE` CUSTOM frames over the AG-UI SSE stream) —
run `pytest -q tests/test_gh74_ag_ui_capabilities_fail_open.py` to verify all
eight cases pass.
