---
id: LRN-134
title: A2UI-over-A2A DataPart "messages" wrapper key satisfies A2A v0.3.0 but contradicts A2UI v0.9.1's own literal binding — citation + known interop caveat
category: protocol
severity: low
source: redteam (RT-003)
date: 2026-07-25
---

## What happened
GH-128 (w038, landed same change) fixed a Critical finding: `agent_sdk/agent/runner.py`
was emitting A2UI DataParts with `data=<bare list[dict]>`, which the todo argued
violates the A2A base spec's `DataPart.data` typing. The fix wraps the message
array as `data={"messages": [...]}}`, matching this SDK's own AG-UI CUSTOM
`value.messages` convention, "matching the AG-UI CUSTOM value convention
exactly (GH-128)". The only justification recorded for the wrapper key name
was `~/.claude/agents/a2ui-advisor.md`, a knowledge file the SAME change
rewrote from "`data` MUST be a JSON array" to "the message array... lives
under `data.messages`" (lines 716-731, 864-866 at the time RT-003 fired).
RT-003 flagged this as circular: the code cites a knowledge file edited in
the same change to agree with the code, not an independent source.

## Root cause
No step in the w038 fix verified the `data.messages` shape against the
actual, version-pinned A2UI v0.9.1 extension specification text — only
against the A2A base spec (correctly) and against the SDK's own advisor
knowledge file (circularly, since it was edited in the same pass).

## Verification performed (this pass)
Fetched the exact, byte-verbatim source of both pinned specs via `gh api`
(not paraphrased tool summaries):

**A2A v0.3.0 (the tag this SDK conforms to — confirmed via
`agent-sdk`'s `a2a-check` skill target and DESIGN.md), `DataPart`:**
```
$ gh api "repos/a2aproject/A2A/contents/types/src/types.ts?ref=v0.3.0" --jq '.content' | base64 -d | sed -n '798,809p'
export interface DataPart extends PartBase {
  readonly kind: "data";
  data: {
    [key: string]: any;
  };
}
```
Confirmed: `DataPart.data` is a required JSON **object** (`{[key: string]:
any}` has no array member) at the exact tag this SDK targets. Source:
`github.com/a2aproject/A2A`, tag `v0.3.0`, `types/src/types.ts:802-809`.
This part of the original GH-128 justification is independently confirmed,
not circular.

**A2UI v0.9.1 (the exact pinned spec directory — not v0.9, not the
unversioned `main` docs), `a2ui_extension_specification.md`, "Data
encoding" section:**
```
$ gh api repos/google/A2UI/contents/specification/v0_9_1/docs/a2ui_extension_specification.md --jq '.content' | base64 -d | sed -n '172,196p'
Agents and clients encode A2UI messages as an A2A `DataPart`.
...
The `data` field of the `DataPart` contains a list of A2UI JSON messages
(e.g., `createSurface`, `updateComponents`, `action`). It MUST be an array
of messages.
...
Example DataPart:
{
  "data": [
    {"version": "v0.9.1", "createSurface": {...}},
    {"version": "v0.9.1", "updateComponents": {...}}
  ],
  "kind": "data",
  "metadata": {"mimeType": "application/a2ui+json"}
}
```
Confirmed: the canonical, version-pinned A2UI v0.9.1 extension spec's own
A2A binding says `data` MUST be a **bare array**, and its own example shows
`"data": [...]`, not `"data": {"messages": [...]}}`. Source:
`github.com/google/A2UI`, path `specification/v0_9_1/docs/
a2ui_extension_specification.md:172-196`.

## Conclusion
The two pinned specs directly conflict for this exact field: A2A v0.3.0
requires `DataPart.data` to be an object; A2UI v0.9.1's own A2A binding
requires it to be a bare array. No published spec — A2A or A2UI — defines
`data.messages` (an object with a `messages` key) as a normative shape.
The wrapper key is this SDK's own invented resolution, not a citable
canonical convention on either side: RT-003's suspicion that the key name
lacked a non-circular source is correct. The wrapper is retained (reverting
would reintroduce the GH-128 Critical A2A-base-spec violation, now
independently confirmed against the pinned tag above, not just the SDK's
own prior claim), but the choice is a deliberate SDK-specific tradeoff,
not a spec-conformant one: **a strictly spec-conformant A2UI v0.9.1 Path-A
renderer, built from a2ui.org alone with no knowledge of this SDK, will not
find its message array at `data` and will render nothing for every A2UI
artifact this SDK emits over A2A** — the same failure class `deleteSurfaceSemantics`
(GH-113) was invented to make discoverable for the split-delivery shape.
This SDK's own first-party consumers (`agent_sdk/console/static/chat.js`,
`agent_sdk/testing/chat.py`) were updated in the same change and unwrap
`data.messages` correctly; the residual risk is scoped to third-party,
non-SDK-aware A2UI Path-A clients. RT-001 (v0.5.44, same day): the
recommended follow-up landed — `agent_sdk/a2ui/catalog.py::a2ui_extension()`
now advertises a `dataEncoding: "data.messages"` non-normative agent-card
hint, mirroring `deleteSurfaceSemantics`, so a spec-conformant third-party
A2UI Path-A renderer has a wire-discoverable way to find the wrapper. The
wrapper itself remains a deliberate, non-canonical SDK convention on
neither spec's side — the hint makes the deviation discoverable, it does
not make it spec-conformant.

RT-002 (w038 group G): the "unaffected" claim above described only this SDK's own
producer→own-consumer round trip. A follow-up redteam pass found the
consumers had actually been narrowed to accept ONLY the `data.messages`
object shape and reject/skip a bare-array `data` — which is the shape
A2UI v0.9.1's own A2A binding actually mandates, per this LRN's own
citation trail. That meant this SDK's console (`chat.js`) and scripted
client (`testing/chat.py`) could no longer render an artifact from a
strictly spec-conformant third-party A2UI producer, an undocumented
consumer-side interop regression distinct from the accepted producer-side
one, and one this SDK's own `harness/agents/a2ui-advisor.md:721` guidance
already told downstream agents to avoid (`Array.isArray(raw) ? raw : …`).
Both consumers were widened to accept EITHER shape on read — a bare array
or an object with a `messages` array — with zero cost to the locked
producer decision above (this SDK's own emission is unchanged). See
DESIGN.md §5.4 for the updated citation and `tests/test_card_console.py::
test_handle_a2a_artifact_accepts_bare_array_datapart_live_behavior` /
`tests/test_chat_driver.py::test_rt002_extract_a2ui_accepts_bare_array`
for the regression pins.

## Check
```
grep -n 'data={"messages"' agent_sdk/agent/runner.py
grep -n 'dataEncoding' agent_sdk/a2ui/catalog.py
```
The first must match both the open- and close-array `DataPart`
constructions in `build_artifact()`. The second must match the
`a2ui_extension()` params dict (pinned by
`tests/test_rt001_a2ui_data_encoding_hint.py`).

## Prevention
When a fix cites "the base protocol requires X" to justify deviating from
an extension's OWN documented binding, verify the extension's binding text
too, at the extension's exact pinned version — not just the base protocol,
and not the SDK's own advisor/knowledge file (which may have been edited in
the same change to match the code, as it was here). A conflict between a
base spec and an extension's own binding is not resolved by silently
picking one side; it must be recorded with citations from both, and the
unresolved interop cost of the chosen side must be stated explicitly, not
implied by omission.
