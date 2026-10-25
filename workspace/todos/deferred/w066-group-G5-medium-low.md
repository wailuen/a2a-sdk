# w066 — Group G5 deferred medium/low findings

- Wave: w066
- Scope: unit:G5
- Date: 2026-10-25

Non-blocking — these did not block w066's archive. Address opportunistically or fold into a future wave.

## RT-001 (medium) — agent_sdk/contrib/action_gate/gate.py:127 [sdkCandidate]
> the route extracts ``TextPart`` text only, so a resume carrying only a

[SDK] parse_decision's A2A bullet was left stale while GH-252 rewrote the AG-UI bullet next to it. It still says a DataPart/FilePart-only A2A resume arrives as "" (UNCLEAR). Since GH-193, routes/a2a.py::_resume_value delivers one DataPart as {"status": None, "payload": data}, and a FilePart is rejected with -32005 before it reaches the gate. The bullet also labels the dict form 'AG-UI' only, but A2A now produces that same dict. This contradicts the docs/protocols.md text that G5 just corrected ('payload.decision from one DataPart (delivered as status: None)'), so the AC 'docs match shipped code' is only partly met.

- Fix: Rewrite the A2A bullet: a text resume is a plain str and is matched exactly; exactly one DataPart (and nothing else) arrives as {"status": None, "payload": <data>}, so payload.decision is read; a FilePart or mixed parts are rejected by the route (-32005 / -32602) and never reach the gate. Change the AG-UI bullet heading so it says the dict form is shared by both transports.
- Codify: When a wave edits one bullet of a per-transport docstring, re-check every sibling bullet against the current route code; older fixes (here GH-193) can leave the neighbours stale.

## RT-002 (medium) — tests/test_gh235_nested_json_and_resume.py:54 [sdkCandidate]
> @pytest.mark.parametrize("status", ["banana", 5, {"x": MARKER}, []])

[SDK] GH-252 now documents, in docs/protocols.md and in the action_gate docstrings, that a decision word in an AG-UI resume `status` (e.g. "approved") is rejected by the route with `invalid resume entry`. No route-level test sends status="approved" or "rejected". The bad-status test uses only "banana", 5, a dict and a list. If someone adds a decision word to _RESUME_STATUSES, the removed shorthand comes back and no test fails, while the docs still promise it is rejected.

- Fix: Add "approved" and "rejected" (and e.g. "APPROVED") to the `status` parametrize list of test_bad_status_is_run_error_before_lookup, so the documented rejection of the shorthand is pinned over build_app().
- Codify: Every contract a doc fix newly states must have a test that would fail if the code drifted back to the old behaviour.

## RT-003 (low) — tests/test_gh235_nested_json_and_resume.py:188 [sdkCandidate]
> def test_tool_json_serializer_failure_uses_fixed_fallback(monkeypatch):

[SDK] AC item 3 asks for the fallback test to assert `content == _RESULT_FALLBACK`. The CHANGELOG GH-252 bullet says 'non-serializable result content is the fixed fallback'. The new test only calls the private helper `_tool_json` directly. It never checks the TOOL_CALL_RESULT frame's `content`. The mapper's other fallback branch (BaseModel.model_dump raising, routes/ag_ui.py `content = _RESULT_FALLBACK`) is still untested. The earlier mapper-level test now asserts '{"x":null}' instead.

- Fix: Add a mapper-level test. Feed _RunMapper a ToolResultEvent whose result is a BaseModel with a model_dump that raises (and/or monkeypatch to_jsonable_python), take the TOOL_CALL_RESULT frame, and assert frame["content"] == _RESULT_FALLBACK.

## RT-004 (low) — agent_sdk/example/agent.py:92 [sdkCandidate]
> "properties": {"status": {"enum": ["approved", "denied"]}},

[SDK] The reference example's publish_note interrupt sends a responseSchema that asks for a `status` field with values approved/denied. Its handler also reads payload.get("status") as the decision. This teaches the pattern GH-252 removed from the docs: a decision word under `status`, read through the nested-status path that action_gate deliberately never reads. It also disagrees with docs/testing.md:178 ('publish_note approves when payload.decision is "approved"') and with the canonical `payload.decision` form in docs/protocols.md. This file is outside G5's listed scope, but it undermines the AC 'no doc or docstring teaches status="approved"'.

- Fix: Change the example's response_schema to {"properties": {"decision": {"enum": ["approved", "rejected"]}}, "required": ["decision"]} (or reuse action_gate.DEFAULT_CONFIRM_SCHEMA). Drop the payload.get("status") fallback in `confirmed`, or move the example onto confirmation_required/parse_decision. Add a CHANGELOG note, since the example's wire schema changes.

---
Filed 2026-10-25 by /sdk-autoloop cycle 2: verified still-present mediums (and lows sharing a fix) are in #261–#267. Other lows stay here, unfiled.
