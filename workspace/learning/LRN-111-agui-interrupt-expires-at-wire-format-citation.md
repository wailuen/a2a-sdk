---
id: LRN-111
title: AG-UI Interrupt.expiresAt wire format — ISO-8601 citation and verification method
category: protocol
severity: low
source: redteam (RT-002, w031/AGUI-1)
date: 2026-07-11
---

## What happened
`AGUI-1` (w031) required emitting `Interrupt.expiresAt` as a string instead of
an integer epoch-ms, per upstream `ag-ui-protocol`'s `Interrupt.expires_at:
Optional[str]`. The AC also required "confirm ISO-8601 vs stringified
epoch-ms convention against docs.ag-ui.com or the upstream SDK's own
serialization before choosing the format." The landed fix chose ISO-8601 UTC
(`%Y-%m-%dT%H:%M:%SZ`): the `InterruptEvent` branch computes
`wall_deadline = time.time() + event.expires_at` and calls the shared helper
`iso_utc()` (`agent_sdk/routes/ag_ui.py:352`), which owns the actual
`strftime("%Y-%m-%dT%H:%M:%SZ")` formatting (`agent_sdk/common/iso8601.py:25`).
The only evidence originally recorded was an unsourced code
comment — no citation any later reader could check. RT-002 flagged this as a
verification/drift gap: since both ISO-8601 and epoch-ms strings type-check
as `str` and no existing test round-trips through the real upstream Pydantic
model, a wrong format choice would be invisible to this repo's own suite.

## Root cause
No offline network access is available for `docs.ag-ui.com`, but the actual
`ag-ui-protocol` PyPI package is installed in sibling agent projects' venvs
(this repo consumes agent-sdk as a dependency across many downstream agent
repos on this machine). Direct inspection of the installed package was never
done during AGUI-1 implementation — only the type annotation was quoted from
memory/the wave todo's prose, not re-verified against the actual source.

## Verification performed (this pass)
Inspected the installed `ag-ui-protocol==0.1.19` wheel directly:

```
$ python3 -c "import ag_ui, ag_ui.core.types as t; print(t.__file__)"
.../site-packages/ag_ui/core/types.py

$ sed -n '259,271p' site-packages/ag_ui/core/types.py
class Interrupt(ConfiguredBaseModel):
    """
    A pause carried inside ``RunFinishedEvent.outcome`` when the outcome is
    ``RunFinishedInterruptOutcome``. The client resumes
    by addressing this interrupt in the resume array of the next RunAgentInput.
    """
    id: str
    reason: str
    message: Optional[str] = None
    tool_call_id: Optional[str] = None
    response_schema: Optional[Dict[str, Any]] = None
    expires_at: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
```

Confirmed: `expires_at` is `Optional[str]` (not `int`/`float`) in
`ag-ui-protocol==0.1.19`, `ag_ui/core/types.py`, class `Interrupt`. Package
metadata: `Name: ag-ui-protocol`, `Version: 0.1.19`,
`https://pypi.org/project/ag-ui-protocol/0.1.19/`.

**However**, the package does NOT further constrain the string's format —
there is no docstring, validator, or example anywhere in `ag_ui/core/`
(`types.py`, `events.py`, `capabilities.py`, `encoder/encoder.py`) that picks
ISO-8601 over any other string encoding for `expires_at` specifically. A
repo-wide grep across every agent project on this machine that depends on
`ag-ui-protocol` (`a2a-fpa`, `a2a-ilevel`, `investment_analyst`, `pitchbook`,
`m365`, `bunkerwire`) turned up no real-world producer of a populated
`Interrupt.expires_at` value to observe an established convention against.

## Conclusion
The AC's instruction to "confirm the format against upstream before
choosing" can only be partially satisfied: upstream confirms the wire type
is `str` (ruling out epoch-ms as an int/float), but does not mandate a
specific string encoding. ISO-8601 UTC (`YYYY-MM-DDTHH:MM:SSZ`) is retained
as this SDK's own choice — it is the most common convention for string
timestamps in JSON/REST APIs and is what a "reference-SDK consumer" written
against typical Python/JS date libraries would expect to parse by default.
This is a defensible interoperable default, not an upstream-verified one.

## Check
The ISO-8601 `strftime` idiom was extracted from `ag_ui.py` into the shared
`iso_utc()` helper during w031 — grep the helper for the format, and grep the
`InterruptEvent` branch for the helper call:
```
grep -n 'strftime("%Y-%m-%dT%H:%M:%SZ")' agent_sdk/common/iso8601.py
grep -n 'iso_utc(wall_deadline)' agent_sdk/routes/ag_ui.py
```
The first must match `iso_utc()`'s body (`agent_sdk/common/iso8601.py:25`) —
the ISO-8601 serialization this LRN documents. The second must match the
`InterruptEvent` branch (currently `agent_sdk/routes/ag_ui.py:352`) — the
call site that formats `expiresAt`. Also confirm the wire format is asserted,
not just produced:
```
grep -n "isinstance(intr\[.expiresAt.\], str)" tests/test_ag_ui.py
```
Must match inside `test_interrupt_outcome_and_resume` (currently
`tests/test_ag_ui.py:90`). If any grep returns nothing, the ISO-8601
choice this LRN records has drifted from the landed code/test and the
citation is stale — re-run the verification and update this file.

## Prevention
When an AC says "confirm X against upstream before choosing," and upstream's
own type only partially constrains X (e.g. `Optional[str]` without a format
spec), the landed artifact must record BOTH what was actually confirmed
(the type) and what was NOT confirmable (the exact string encoding) plus the
independent reasoning for the choice made — not phrase the comment as if the
full choice were upstream-verified. Prefer citing an installed package via
direct file inspection (`site-packages/.../types.py:LINE`) over prose-only
citations, and check whether any of this machine's other agent-sdk-consuming
repos have `ag-ui-protocol` installed before assuming no offline verification
is possible.

When a later wave extracts an idiom this LRN's Check clause greps for (as
w031 did, moving the `strftime` call from `ag_ui.py` into the shared
`iso_utc()` helper) into a shared helper, the Check clause must be re-pointed
at the helper's file/line in that same wave — split into one grep per file
if the idiom and its call site now live apart — or this LRN's own
drift-detector produces a false stale-citation alarm on the next redteam
pass.
