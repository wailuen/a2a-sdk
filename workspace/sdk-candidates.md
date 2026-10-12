# SDK issue candidates — w045 (2026-10-11)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: GH-155 token-budget exit: the 'at most final_summary_max_tokens beyond the budget' allowance is enforced on summary OUTPUT only; the full-transcript input re-send is not counted, so a capped run can overshoot token_budget by a whole extra context call. The accounting change (total spend -> output-only) was made by the wave without a recorded maintainer ratification on GH-155, and docs/deployment.md, DESIGN.md:469 and CHANGELOG describe it inconsistently. Merges RT-001 duplicates (input-not-counted / unratified-AC-change variants).
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/loop.py
- Rationale: SDK loop cost guard (DESIGN.md section 8). Current working tree _summary_max_tokens (loop.py:432) is output-only and its docstring claims a maintainer ruling; needs a GH-155 comment URL ratifying it or a revert to the AC as written. Earlier rounds flipped between input-charging (which made the feature dead) and output-only, so this is a genuine spec decision for the maintainer, not a code fix the wave can sign off.

## Candidate 2: GH-155 budget-exit summary was unreachable with default LoopPolicies when the transcript re-send was charged against the 1024-token allowance (always yielded the fixed notice); tests only passed with hand-tuned final_summary_max_tokens/max_output_tokens, and final_summary_max_tokens had no settings/env field despite docs telling operators to raise it. Merges the 'never fires by default' RT-001 duplicates.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/loop.py
- Rationale: SDK loop behaviour and BaseAgentSettings wiring. Current tree appears to have addressed it (output-only cap; config.py:230 and app.py:623 now wire final_summary_max_tokens), but a default-policy end-to-end test proving a budget-exit summary fires should be confirmed. Resolution is coupled to the ratification question in the previous candidate.

## Candidate 3: Max-turns exit (loop.py ~1769-1790) makes the new GH-155 summary call without re-checking the token budget or the task deadline; a run already past budget or deadline makes one more unbounded full-transcript call and reports 'max turns exceeded' instead of 'task deadline exceeded'.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/loop.py
- Rationale: Adding a model call to an exit path that previously made none bypasses SDK spend/time guards; affects every agent using run_loop.

## Candidate 4: _final_summary used a bare 'except Exception:' with no log, silently swallowing summary-call failures, including TypeError from third-party ModelClient implementations that do not accept the new required 'tool_choice' keyword. CHANGELOG does not tell custom ModelClient authors they must add the parameter.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/loop.py
- Rationale: ModelClient is a public SDK extension seam. Current tree binds the exception (loop.py:470); verify it logs type + frame_locations without str(exc) and that the CHANGELOG custom-client note was added.

## Candidate 5: OpenAI/Azure summary call (tool_choice='none') cap handling went through several broken iterations: (a) a small max_completion_tokens on gpt-5 reasoning models is consumed by reasoning and returns empty output, contradicting the module's own docstring; (b) a fix forced reasoning_effort='minimal' even when the operator set none, breaking gpt-4o/o-series/compatible endpoints with HTTP 400; (c) a later fix added +25,000 headroom, exceeding gpt-4o's 16,384 limit and uncapping visible output, with max_completion_tokens/reasoning_effort not wired from settings. Every failure is masked by the summary fallback to the fixed notice.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/openai_client.py
- Rationale: Built-in SDK model client. Current tree (openai_client.py:126-139) reverts to min(max_tokens, configured cap) with no invented reasoning_effort and logs an empty-text warning, so (b) and (c) look fixed; (a) remains a known trade-off on reasoning models that should be documented in DESIGN section 8 and covered by a finish_reason='length' test.

## Candidate 6: GH-155 changed public surface outside the todo scope without CHANGELOG entries: new DoneEvent.summary field (events.py), app.py final_summary wiring, and FakeModelClient.calls gaining a 'tool_choice' key (testing/fake_model.py).
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/events.py
- Rationale: DoneEvent is a public loop event type read by custom translators; scope/changelog drift on SDK public API (LRN-202).

## Candidate 7: GH-154 adds public field TaskRecord.date_line (TaskRecord is in agent_sdk.tasks.__all__) without listing store.py in the todo scope, without a CHANGELOG Added line, and without a DESIGN.md section 5 note on whether durable TaskStore subclasses must persist it.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/tasks/store.py
- Rationale: Public SDK task-store surface; durable store implementers need to know whether a resumed task keeps its original date (LRN-202).

## Candidate 8: _final_summary adds two new bridge_trailing_user call sites (final_summary=False path and notice fallback) but LRN-144's Check, which pins the allowed callers, was not amended, turning it into a permanently failing audit (LRN-249).
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/loop.py
- Rationale: SDK transcript-integrity invariant and its learning record; harness audits rely on the pinned call-site list.

## Candidate 9: New default-on timezone validator calls ZoneInfo('UTC') on every BaseAgentSettings build even when AGENT_SDK_INJECT_CURRENT_DATE=false; without the tzdata package, hosts with no system zone files (Windows, Alpine, distroless) fail to boot with an error that wrongly blames the operator's zone name.
- Severity: high
- Component: sdk/build
- File: agent_sdk/config.py
- Rationale: SDK packaging/boot. Current pyproject.toml now lists tzdata>=2024.1, so the main fix landed; confirm a UTC fast path or skip-when-disabled and a reset_tzpath([]) boot test.

## Candidate 10: SI-2 no-leak coverage for hostile timezone values is missing or vacuous: the original tests never used a control-char/newline marker or inspected logs; the later test_hostile_zone_never_leaks asserts absence on root caplog after build_app() sets agent_sdk.propagate=False, so when run in isolation caplog captures nothing and the negative assertion passes trivially.
- Severity: high
- Component: security
- File: tests/test_gh154_current_date.py
- Rationale: SDK security invariant SI-2 (untrusted input must not reach logs/prompt). Fix: use sdk_caplog or a positive control, and cover both A2A message.metadata.timezone and AG-UI forwardedProps.timezone (LRN-106/LRN-128).

## Candidate 11: _message_text (a2a.py:363-364) keeps only TextPart text; a Message with only FilePart/DataPart parts (e.g. an A2UI userAction DataPart) is accepted and the model is fed a placeholder ' ', silently dropping the parts instead of processing them or returning -32005 ContentTypeNotSupported (HTTP 415).
- Severity: high
- Component: protocol/a2a
- File: agent_sdk/routes/a2a.py
- Rationale: A2A v0.3.0 protocol route conformance in the SDK; affects every agent and the A2UI-over-A2A action path.

## Candidate 12: TOOL_CALL_START frames (ag_ui.py:238 and :273) always include parentMessageId, emitting "parentMessageId":null on tool-first turns and resume runs; the AG-UI reference encoder uses exclude_none, so strict schema-validating clients can reject the event or abort the stream.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/routes/ag_ui.py
- Rationale: AG-UI wire-format conformance in the SDK protocol route; the in-code comment calling it deliberate contradicts the published schema.
