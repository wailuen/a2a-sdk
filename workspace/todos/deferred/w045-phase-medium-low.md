wave: w045
scope: phase
date: 2026-10-11
status: non-blocking (medium/low)

Non-blocking — these did not block w045's archive. Address opportunistically or fold into a future wave.

Findings were accumulated across every phase redteam round and deduped by file+description. Redteam IDs restart each round, so each heading carries its round label (R1..R8, in the order the rounds ran). Many findings recur across rounds with different wording. They are kept separately because their descriptions differ; the theme index below groups them. All are flagged sdkCandidate.

## Status check at write time (2026-10-12, quick grep only — re-verify before acting)

- Already landed in the tree: `tzdata>=2024.1` is in pyproject.toml; `agent_sdk/common/tz.py` has `load_zone` (UTC fast path via `datetime.timezone.utc`) and a shared `valid_timezone`. The tzdata/UTC-boot theme and the duplicated-validator theme are therefore likely resolved; confirm and close.
- Still open at write time: `_final_summary` does not check `stop_reason` in agent_sdk/agent/loop.py; DESIGN.md §8 has no `tool_choice`; CHANGELOG [Unreleased] has no `⚠️ Behavior changes` block.

## Theme index

1. `_final_summary` ignores `stop_reason`: max-tokens cut-off text shown as the summary; tiny caps (e.g. 4 tokens) allowed; no minimum useful cap: R1 RT-003, R4 RT-004, R5 RT-006, R6 RT-002, R7 RT-005
2. Bedrock `tool_choice='none'` keeps toolConfig; dropped toolUse leaves lead-in text ("Let me look that up") delivered as the summary: R4 RT-011, R5 RT-006, R6 RT-003, R7 RT-005, R8 RT-002
3. OpenAI/Azure summary cap (≤1024 `max_completion_tokens`) eaten by reasoning on gpt-5-class models, so summary comes back empty; module docstring now stale: R3 RT-002, R4 RT-002, R5 RT-005, R8 RT-003
4. Custom `ModelClient` without `tool_choice` raises TypeError, swallowed by broad except, summaries silently become the notice; no boot/signature check: R2 RT-005, R4 RT-009, R7 RT-008, R8 RT-001
5. DESIGN.md §8 ModelClient snippet lacks `tool_choice`: R3 RT-006, R4 RT-009, R5 RT-003, R6 RT-007, R7 RT-008, R8 RT-005
6. CHANGELOG [Unreleased] files default-on behavior changes (date line in prompt, extra billed cap-exit call, FAILED status.message text, deadline-vs-max-turns error string, ModelClient signature) under `### Added` instead of `### ⚠️ Behavior changes` with Migration lines: R1 RT-006, R3 RT-003, R4 RT-009, R5 RT-004, R6 RT-008, R7 RT-008, R8 RT-001
7. Max-turns exit deadline pre-check runs even with `final_summary=False`, changing the error to 'task deadline exceeded': R2 RT-006, R4 RT-003, R7 RT-007
8. Summary-call cost estimate leaves out last turn's tool results; `estimated_input_tokens`/`last_call_tokens` unused/dead; LoopPolicies comment contradicts helper: R2 RT-003, R4 RT-012
9. Default 'UTC' needs zoneinfo at boot; no `tzdata` dependency (likely fixed — see status check): R1 RT-004, R3 RT-004, R4 RT-006, R5 RT-002, R6 RT-004
10. Date line computed before `run_task_worker`'s `try:`; a raise leaves the task non-terminal and streams open: R3 RT-007, R4 RT-005, R5 RT-009, R6 RT-010, R7 RT-006, R8 RT-011
11. Resume test (`test_resumed_task_reuses_original_date`) never interrupts/resumes and can pass with zero assertions; `record.date_line` reuse branch never exercised: R1 RT-007, R2 RT-004, R3 RT-005, R4 RT-007, R5 RT-008, R6 RT-005, R7 RT-004, R8 RT-007
12. Token-budget exit has no end-to-end A2A/AG-UI tests (only max-turns does); `/v1/message:stream` untested for summary and timezone override: R1 RT-008, R3 RT-005, R4 RT-008, R5 RT-007, R5 RT-008, R6 RT-006, R7 RT-009, R8 RT-009
13. No `build_app()` test that `AGENT_SDK_FINAL_SUMMARY` / `AGENT_SDK_FINAL_SUMMARY_MAX_TOKENS` reach `app.state.loop_policies` (LRN-077): R1 RT-005, R4 RT-008, R5 RT-007, R8 RT-006
14. docs/deployment.md puts GH-155 settings under the GH-154 heading; `AGENT_SDK_FINAL_SUMMARY_MAX_TOKENS` has no bullet; unsettable knobs named: R1 RT-011, R2 RT-008, R3 RT-008, R4 RT-015, R5 RT-011, R6 RT-011, R7 RT-011, R8 RT-012
15. GH-154 helpers inserted between the RT-A-002 comment and `_TASK_FAILED_TOOL_RESULT_TEXT`; import order; a2a.py `_start_worker` 12-space indent; bedrock `_has_tool_blocks` placement: R1 RT-009, R2 RT-007, R3 RT-009, R4 RT-014, R4 RT-016, R5 RT-010, R5 RT-013, R6 RT-010, R6 RT-013, R7 RT-010, R8 RT-013
16. Zone validation duplicated (config vs runner) and platform-dependent case matching (likely fixed by common/tz.py — see status check): R1 RT-010, R3 RT-010, R4 RT-014, R5 RT-010
17. Route-side timezone values typed `str | None` but carry any raw JSON value; A2A lacks a `_user_timezone` helper: R1 RT-010, R3 RT-010, R4 RT-016, R5 RT-013, R6 RT-013, R7 RT-012, R8 RT-013
18. Generic `timezone` attribute on stable-core BaseAgentSettings clashes with subclass fields; validator lets TypeError through: R4 RT-010
19. `TaskRecord.date_line` never read back by any SDK path (resume-after-restart not implemented): R3 RT-011, R4 RT-007
20. Notice fallback bridges transcript with default text, not the notice the user saw: R4 RT-013, R5 RT-012
21. Sealed-during-summary path drops the UsageEvent for a real call: R5 RT-012
22. FAILED DoneEvent summary not appended to task.history (unlike COMPLETED); A2A streaming shows summary twice: R6 RT-012
23. add-artifact skill (harness + template copies) still teaches `{{ today }}` / render-time date, now conflicting with GH-154: R6 RT-009, R8 RT-004
24. `agent_sdk/common/tz.py` helpers not registered as a C-NNN component: R8 RT-008
25. New settings unbounded (`final_summary_max_tokens` negative accepted; `openai_reasoning_effort` free str): R8 RT-010
26. Inbound `timezone` request field undocumented; DESIGN.md §4.4 boot list lacks AGENT_SDK_TIMEZONE; DESIGN.md:469 GH-155 aside breaks a sentence: R4 RT-015, R5 RT-011
27. GH-154 AC says "Agent/Settings options" but only Settings fields exist; choice not recorded: R8 RT-013

## Codify candidates

- R3 RT-003: A default-on change to prompts, wire status text, error strings or a seam signature goes under Behavior changes with its opt-out, never only under Added.
- R6 RT-002: A bounded fallback reply must check the provider's stop reason, or it can show the same truncated output it was built to replace.
- R6 RT-003: Dropping tool calls from a tools-disabled reply must also drop the lead-in text that only made sense next to them.
- R6 RT-004: A default-on setting must not add a platform data dependency that can fail boot with defaults.
- R6 RT-005: A test whose only assertion sits behind a hasattr/if guard is not coverage; the AC behavior must be driven directly.
- R6 RT-006: Every cap exit named in an AC needs its own end-to-end assertion on each transport.
- R6 RT-007: Changing a public Protocol signature must update the design doc snippet that implementers copy.
- R6 RT-008: Default-on behavior changes and public Protocol signature changes belong under Behavior changes with a Migration line, not Added.
- R6 RT-009: When an SDK feature replaces a harness-taught pattern, update every harness and template skill copy that teaches the old pattern.
- R6 RT-010: Per-task setup in a worker must sit inside the worker's terminal-failure guard.
- R6 RT-011: Each feature's env vars belong under that feature's own docs heading.
- R6 RT-012: Failure and success terminal branches should treat the final agent message the same way.
- R6 RT-013: Untrusted JSON values should be typed as object until validated.
- R8 RT-001: Adding a kwarg to the public ModelClient Protocol must keep old implementers working (signature probe + fallback), and the CHANGELOG must file it under a breaking/changed section, not Added.
- R8 RT-002: When tools cannot be fully disabled on a provider, a summary reply that ended in tool_use is a preamble, not an answer; judge usability on stop_reason, not on whether text is non-empty.
- R8 RT-003: An output cap on a reasoning model includes hidden reasoning; a bounded follow-up call needs a reasoning-aware budget or a retry, or the feature silently degrades on that backend.
- R8 RT-004: When an SDK feature replaces a pattern the harness teaches, update every harness/template skill that teaches it in the same wave, not just the in-code docstring.
- R8 RT-005: A change to a Protocol signature must update the DESIGN.md block that documents that Protocol in the same change.
- R8 RT-006: Every new settings->LoopPolicies field needs a build_app() integration assertion (LRN-077), not just a model_fields alias check.
- R8 RT-007: A test named for an AC must exercise that AC's trigger (here, a resume) and must never wrap its assertion in a conditional that can skip it.
- R8 RT-008: A new shared validator for untrusted input belongs in the component registry the same wave it lands.

## Findings

### R1 RT-003 — medium — agent_sdk/agent/loop.py
At the budget exit, `_summary_max_tokens` can return a very small cap (total_tokens = budget + 1020 gives max_tokens = 4). `_final_summary` (line 485) accepts any non-blank text and never checks `response.stop_reason` for a max_tokens/length cut-off, so the user can get a reply cut off mid-sentence ('Based on the') as the summary — the exact failure GH-155 was filed to remove.
- Fix: Set a minimum useful cap (e.g. skip the call and send the notice when the cap is below 256), and/or treat stop_reason in {max_tokens, length} as unusable, or append the fixed notice after the partial text. Add a FakeModel test with stop_reason max_tokens.

### R1 RT-004 — medium — agent_sdk/config.py
`_valid_timezone` (line 262) always calls `ZoneInfo(v)`, including for the default 'UTC' and when `inject_current_date=False`. No `tzdata` dependency, so on hosts with no system zone database (Windows; some minimal images) every `BaseAgentSettings()` fails at boot, even with the feature off.
- Fix: Add `tzdata` to pyproject dependencies; special-case 'UTC' with `datetime.timezone.utc` in the validator and `current_date_line`; and/or validate only when `inject_current_date` is true.

### R1 RT-005 — medium — agent_sdk/app.py
LRN-077: no test proves `AGENT_SDK_FINAL_SUMMARY` reaches `app.state.loop_policies.final_summary` through `build_app()` (app.py:620). Every `final_summary=False` test builds `LoopPolicies` directly; removing the wiring line would fail no test.
- Fix: Build the app with `AGENT_SDK_FINAL_SUMMARY=false`, assert `app.state.loop_policies.final_summary is False`, and run one max-turns task asserting the fake model saw exactly one call.

### R1 RT-006 — medium — CHANGELOG.md
[Unreleased] (line 9) puts default-on behavior changes under '### Added': system prompt changes (GH-154), extra billable call on cap exits, changed FAILED `status.message` text, and the `ModelClient.converse` signature change. Earlier releases use '⚠️ Behavior changes' / '🔴 Breaking changes', so `~=0.9` pinners will miss them.
- Fix: Move these under '⚠️ Behavior changes', each with a short Migration note (opt-out env var, or add `tool_choice`).

### R1 RT-007 — low — tests/test_gh154_current_date.py
`test_resumed_task_reuses_original_date` never resumes anything; it checks `rec.date_line` inside an `if rec is not None` guard that lets it pass with no assertion. The reuse branch (`record.date_line is not None`) is never run.
- Fix: Use an action_gate interrupt, move the clock across midnight before resume, assert both model calls end with the original date line. Remove the guard.

### R1 RT-008 — low — tests/test_gh155_cap_summary.py
Full-app tests (A2A failed status.message with summary; AG-UI text then RUN_ERROR) cover only max-turns. The token-budget exit is tested only at run_loop level, though the AC lists both.
- Fix: Add A2A and AG-UI tests with a small AGENT_SDK_TASK_TOKEN_BUDGET asserting state=failed, summary + 'token budget' in status.message, and TEXT_MESSAGE_CONTENT before RUN_ERROR.

### R1 RT-009 — low — agent_sdk/agent/runner.py
GH-154 helpers inserted between the RT-A-002 comment and `_TASK_FAILED_TOOL_RESULT_TEXT`; the comment now sits above `_MAX_TZ_LEN = 64` (line 1148). bedrock.py puts `_has_tool_blocks` mid-constants with one blank line before `_EXECUTOR_MAX_WORKERS`; a2a.py `message_send` indents `_start_worker(` args 12 spaces vs 8 in the sibling.
- Fix: Move the helpers above the RT-A-002 comment, move `_has_tool_blocks` below the constants, fix a2a.py indentation.

### R1 RT-010 — low — agent_sdk/routes/ag_ui.py
Zone checking written twice (`BaseAgentSettings._valid_timezone` and `runner.valid_timezone`, same except tuple, can drift). `_user_timezone` (ag_ui.py:426) and a2a `_start_worker(user_timezone: str | None)` pass any JSON value through; only the downstream `isinstance` keeps it safe.
- Fix: One `valid_timezone` helper in agent_sdk/common/ used by the config validator. Type the route value as `object` or validate at the route boundary.

### R1 RT-011 — low — docs/deployment.md
`AGENT_SDK_FINAL_SUMMARY` (GH-155) is listed under '### Current date in the system prompt (GH-154)' (line 103).
- Fix: Own subsection (e.g. 'Final summary on turn/budget limits (GH-155)') next to max-turns/budget notes; mention `final_summary_max_tokens` is LoopPolicies-only.

### R2 RT-003 — medium — agent_sdk/agent/loop.py
Summary-call cost estimate leaves out the last turn's tool results: `last_call_tokens` (loop.py:1298) is the previous call's input+output, but the re-sent transcript (loop.py:1795) also carries later toolResult blocks. The promised bound ('at most final_summary_max_tokens past the budget', DESIGN.md and docs/deployment.md) can be exceeded by the full final-turn tool output. On a resumed run already over budget, `last_call_tokens` is 0.
- Fix: Estimate re-send as last input + last output + estimate of appended messages (e.g. `len(json.dumps(new_messages)) // 4`), or document the bound as approximate. Test with a large final-turn tool result that pushes past the allowance.

### R2 RT-004 — medium — tests/test_gh154_current_date.py
AC 'Resumed/interrupted turns reuse the original date' has no real test. test_resumed_task_reuses_original_date (line 136) never interrupts/resumes; assertion behind `if hasattr(store, '_records')` / `if rec is not None`.
- Fix: Drive an interrupt, advance patched `_clock_now` past midnight, resume, assert the post-resume system prompt ends with the original date line. Remove the guard; use public `TaskStore.get`.

### R2 RT-005 — medium — agent_sdk/agent/loop.py
Adding `tool_choice` to the public ModelClient Protocol breaks custom clients silently: TypeError on every summary call, caught at loop.py:477, notice sent. Nothing at boot detects it.
- Fix: At build_app() with final_summary on, check `inspect.signature(model_client.converse)`; if no `tool_choice` and no `**kwargs`, raise a clear boot error or log one WARNING and turn final_summary off. Test with a legacy client.

### R2 RT-006 — low — agent_sdk/agent/loop.py
`final_summary=False` does not fully restore old behavior: the deadline pre-check at the max-turns exit (loop.py:1791-1794) runs regardless, so both-limits-hit runs end 'task deadline exceeded' instead of 'max turns (N) exceeded'.
- Fix: Run the pre-check only when `policies.final_summary` is on, or fold it into `_final_summary`'s no-call path.

### R2 RT-007 — low — agent_sdk/agent/runner.py
GH-154 helpers sit between the RT-A-002 comment (runner.py:1141-1146) and `_TASK_FAILED_TOOL_RESULT_TEXT`. routes/a2a.py:571-574 and 826-829 use a 12-space hanging indent in a 4-space block.
- Fix: Move helpers above the comment or into their own module; re-indent both a2a.py call sites.

### R2 RT-008 — low — docs/deployment.md
docs/deployment.md:104-110 lists `AGENT_SDK_FINAL_SUMMARY` under the GH-154 heading, and tells operators to raise `final_summary_max_tokens`, which had no env var (see RT-001 of that round).
- Fix: Separate 'Final summary on capped runs (GH-155)' subsection; name only settable knobs.

### R3 RT-002 — medium — agent_sdk/agent/openai_client.py
For `tool_choice=='none'`, converse forces `max_completion_tokens=min(max_tokens, configured)`, usually 1024 (lines 122-128). The module docstring (lines 14-17) warns a small cap on gpt-5 is consumed by reasoning, giving an empty completion; the summary often falls back to the notice while paying for the re-send plus reasoning. Docstring 'cap applied ONLY when explicitly configured' is stale.
- Fix: Send `reasoning_effort='minimal'/'low'` when none configured, or add reasoning headroom (bounded by the allowance). Test empty content with finish_reason='length'. Update docstring.

### R3 RT-003 — medium — CHANGELOG.md
[Unreleased] files everything under Added, including: (1) date line in every prompt by default; (2) extra billed call + streamed text on cap exits; (3) A2A FAILED status.message changes to summary+error; (4) both-limits error string changes to 'task deadline exceeded' (loop.py:1786-1789); (5) custom ModelClient MUST accept `tool_choice` (bold inside an Added bullet).
- Fix: Move (1)-(5) under '### ⚠️ Behavior changes' with opt-out/migration (AGENT_SDK_INJECT_CURRENT_DATE=false, AGENT_SDK_FINAL_SUMMARY=false, add `tool_choice`). State (4) explicitly (LRN-199). Keep only new fields/settings under Added.
- Codify: see Codify candidates.

### R3 RT-004 — medium — pyproject.toml
`_valid_timezone` (config.py:263-275) calls ZoneInfo at boot even for 'UTC'; `valid_timezone`/`current_date_line` need it per task. No `tzdata` dependency, so hosts without system zone data (Windows, alpine/distroless) fail to boot with defaults and a misleading 'must be a valid IANA time zone name' error. Template python:3.12-slim has /usr/share/zoneinfo (checked).
- Fix: Add `tzdata` to [project].dependencies; and/or UTC fast path via `datetime.timezone.utc` in validator and `current_date_line`.

### R3 RT-005 — medium — tests/test_gh154_current_date.py
test_resumed_task_reuses_original_date (lines 136-147) never interrupts/resumes, uses one clock value, asserts only behind a hasattr probe on a private attribute. Separately, GH-155 end-to-end tests cover only max-turns, not the budget exit.
- Fix: Drive action_gate/InterruptEvent with a clock crossing midnight; assert every model call ends with the original date; drop the conditional. Add A2A and AG-UI budget-exit tests (low AGENT_SDK_TASK_TOKEN_BUDGET, high-usage scripted tool call).

### R3 RT-006 — medium — DESIGN.md
§8 ModelClient snippet (lines 461-465) still shows `converse(self, *, system, messages, tools, max_tokens)` without `tool_choice`.
- Fix: Add `tool_choice: Literal['auto','none'] = 'auto'` and one line on 'none' (no tool calls returned; Bedrock keeps toolConfig when history has tool blocks).

### R3 RT-007 — low — agent_sdk/agent/runner.py
Date line computed at runner.py:1200-1205 before run_task_worker's try. If `current_date_line` raises, the worker dies before WORKING: no terminal status, A2A stays 'submitted', AG-UI heartbeats until disconnect. `run_task_worker` also defaults `inject_date=False` while settings default True.
- Fix: Move inside the try, or fall back to 'UTC'. Consider defaulting `inject_date=True`.

### R3 RT-008 — low — docs/deployment.md
`AGENT_SDK_FINAL_SUMMARY` sits inside the GH-154 section; `AGENT_SDK_FINAL_SUMMARY_MAX_TOKENS` has no bullet.
- Fix: '### Final summary at turn/budget limits (GH-155)' section (or next to AGENT_SDK_MAX_TURNS) with one bullet per variable.

### R3 RT-009 — low — agent_sdk/agent/runner.py
GH-154 helpers between the RT-A-002 SI-2 comment and `_TASK_FAILED_TOOL_RESULT_TEXT` (runner.py:1142-1171). a2a.py message_send `_start_worker` (571-574) indents args 12 spaces, closing paren at 8.
- Fix: Move helpers above the comment; re-indent to 4-space continuation.

### R3 RT-010 — low — agent_sdk/config.py
Zone check written twice (config.py:263-275 and runner.py:1155-1164) with different rules (only runner caps length / rejects empty). A2A repeats `(params.message.metadata or {}).get("timezone")` at a2a.py:573 and 828, while AG-UI has `_user_timezone`.
- Fix: One `is_valid_zone(name)` in agent_sdk/common used by both; add `_user_timezone(message)` to routes/a2a.py.

### R3 RT-011 — low — agent_sdk/tasks/store.py
`TaskRecord.date_line` is public and documented as needing durable persistence, but nothing reads it across worker runs: run_task_worker is only called on fresh records (a2a.py:445, ag_ui.py:500), and in-process resume reuses the captured system string. The `is None` check at runner.py:1201 is always true.
- Fix: Mark it in DESIGN.md as reserved for future durable resume-after-restart, or drop it for a local variable; align the CHANGELOG guidance.

### R4 RT-002 — medium — agent_sdk/agent/openai_client.py
On `tool_choice='none'`, cap is min(max_tokens, configured) (≤1024) while any configured `reasoning_effort` is still sent; on gpt-5 the summary likely comes back empty. Docstring line about cap now false. `test_openai_none_uses_operator_reasoning` locks this in.
- Fix: Add reasoning headroom or send lowest reasoning_effort on summary calls; update docstring; log a fixed-text warning on empty summary with stop_reason 'length'/'max_tokens'.

### R4 RT-003 — medium — agent_sdk/agent/loop.py
New deadline check at the max-turns exit (loop.py:1786) runs even with `AGENT_SDK_FINAL_SUMMARY=false`, so the error becomes 'task deadline exceeded'. Contradicts CHANGELOG ('Set AGENT_SDK_FINAL_SUMMARY=false for the old behavior') and the AC ('same error code').
- Fix: Guard it with `policies.final_summary`, or record the change under Behavior changes and drop the 'old behavior' claim.

### R4 RT-004 — medium — agent_sdk/agent/loop.py
`_final_summary` (loop.py:484) never checks `stop_reason` and has no minimum cap; a few tokens of allowance yields e.g. a 3-token call whose cut-off text becomes the final answer and status.message.
- Fix: Use the notice when cap < ~256; on 'max_tokens'/'length' use the notice or append a fixed 'summary was cut short' line. Test both.

### R4 RT-005 — medium — agent_sdk/agent/runner.py
Date line computed at runner.py:1200 before `try:`; a raise leaves the task SUBMITTED, `set_task_status` never called, SSE streams never closed.
- Fix: Move inside the try, or make it total (fall back to `datetime.timezone.utc` with '(UTC)', log nothing about the raw value).

### R4 RT-006 — medium — agent_sdk/config.py
Boot with defaults needs system zone data ('UTC' via ZoneInfo, no tzdata). Reproduced with `zoneinfo.reset_tzpath([])`: `BaseAgentSettings()` raises ValidationError. Template python:3.12-slim unaffected.
- Fix: Add `tzdata`, or map 'UTC' to `datetime.timezone.utc` in validator and `current_date_line`. Test booting with empty TZPATH.

### R4 RT-007 — medium — tests/test_gh154_current_date.py
Resume AC uncovered (test never interrupts; assertion behind `hasattr`/`if rec is not None`). No SDK path calls run_task_worker twice on one record (resume uses deliver_resume), so `record.date_line` is never read back.
- Fix: Real ToolInterrupt over A2A and AG-UI with a clock crossing midnight; assert every model call's prompt ends with the original line; remove guards. Or document date_line as durable-restart-only and test that path.

### R4 RT-008 — medium — tests/test_gh155_cap_summary.py
Only max_turns has end-to-end A2A/AG-UI tests; budget exit loop-level only. No test that `AGENT_SDK_FINAL_SUMMARY`/`_MAX_TOKENS` reach `app.state.loop_policies`; no `/v1/message:stream` test.
- Fix: A2A send, A2A stream and AG-UI tests with low AGENT_SDK_TASK_TOKEN_BUDGET asserting state failed, summary + 'task token budget exceeded', text before RUN_ERROR; assert settings reach the policies.

### R4 RT-009 — medium — agent_sdk/agent/model_client.py
`converse` gained `tool_choice` but DESIGN.md:463 shows the old signature; custom clients raise TypeError hidden by `except Exception`. CHANGELOG files the default-on change under Added.
- Fix: Update DESIGN.md §8 and the 'none' rule; move GH-155 effects under Behavior changes with a Migration line; optionally `inspect.signature` check with a one-time warning.

### R4 RT-010 — medium — agent_sdk/config.py
Stable-core BaseAgentSettings gains a generic `timezone` attribute (config.py:158). A downstream subclass with its own `timezone` field silently replaces it (app.state.timezone follows the subclass), and the inherited validator raises an uncaught TypeError on None/non-str.
- Fix: Rename to e.g. `agent_timezone` (keep alias AGENT_SDK_TIMEZONE); reject non-str with ValueError; test a subclass with its own `timezone` field.

### R4 RT-011 — low — agent_sdk/agent/bedrock.py
With `tool_choice='none'` and tool blocks in history, toolConfig is sent and toolUse dropped (bedrock.py:416); a lead-in sentence with stopReason 'tool_use' becomes the summary.
- Fix: Return empty text_segments on 'none' + 'tool_use', or have `_final_summary` treat 'tool_use' as unusable. Test with `_BEDROCK_RAW`.

### R4 RT-012 — low — agent_sdk/agent/loop.py
`_summary_max_tokens` takes an unused `estimated_input_tokens`; `last_call_tokens` exists only to feed it. LoopPolicies comment (loop.py:201-205) says the cap works 'with the estimated transcript re-send', contradicting the helper docstring. `test_budget_summary_fires_when_resend_fits_allowance` is named for a rule the code lacks.
- Fix: Remove or use the parameter (see R2 RT-003); align the comment; rename the test.

### R4 RT-013 — low — agent_sdk/agent/loop.py
On the notice fallback, `bridge_trailing_user(messages)` is called without text, so the transcript records the default bridge text instead of the notice the user saw.
- Fix: `bridge_trailing_user(messages, notice)`.

### R4 RT-014 — low — agent_sdk/agent/runner.py
Helpers between the RT-A-002 comment and its constant. Zone checks duplicated (config has no length cap, runner does) and platform-dependent: 'asia/tokyo' accepted on macOS, rejected on Linux.
- Fix: Move helpers above the comment or into agent_sdk/common/timezones.py shared by validator and routes; optionally match against cached `zoneinfo.available_timezones()` for exact case.

### R4 RT-015 — low — docs/deployment.md
GH-155 bullet inside the GH-154 section (line 103). Inbound `timezone` field (A2A message.metadata.timezone, AG-UI forwardedProps.timezone) undocumented in DESIGN.md §5.1/§5.3 and protocol docs; §4.4 boot validations omit AGENT_SDK_TIMEZONE.
- Fix: GH-155 subsection with both settings; document the timezone field (IANA check, 64-char cap, silent fallback); add the zone check to §4.4.

### R4 RT-016 — low — agent_sdk/routes/a2a.py
message_send `_start_worker(...)` continuation indented 12 spaces (571-574). `_user_timezone` and the A2A metadata read are typed `str | None` but pass any JSON value to run_task_worker.
- Fix: Fix indentation; call `valid_timezone()` at the route edge, or type as `object`.

### R5 RT-002 — medium — agent_sdk/config.py
`_valid_timezone` (line 265) always calls ZoneInfo, even for 'UTC' and with AGENT_SDK_INJECT_CURRENT_DATE=false; no tzdata. Boot hard-fails on Windows / alpine / some distroless images, which booted before. Deferred twice already (G1 R1 RT-004, R2 RT-002).
- Fix: Add `tzdata` or UTC fast path in validator and `current_date_line`; skip validation when inject_current_date is False; test with ZoneInfo monkeypatched to raise.

### R5 RT-003 — medium — DESIGN.md
§8 snippet (~line 462) lacks `tool_choice`; a client written from DESIGN.md raises TypeError on every summary call, silently becoming the notice. `Agent(model_client=...)` is stable core, so this is an undocumented implementer-contract change.
- Fix: Add `tool_choice: Literal['auto','none'] = 'auto'`; note implementers must accept it and must not return tool calls on 'none'.

### R5 RT-004 — medium — CHANGELOG.md
All GH-154/155 entries under Added (line 9) though several are default-on behavior changes (date line, extra billable call, 'task deadline exceeded' at max-turns when both hit, new ModelClient kwarg). Same misfiling as LRN-153/LRN-267. GH-155 bullet is one ~250-word paragraph.
- Fix: Move default-on changes and the ModelClient requirement under Behavior changes with Migration line; keep only additive fields (DoneEvent.summary, TaskRecord.date_line, settings) under Added; split the GH-155 paragraph.

### R5 RT-005 — medium — agent_sdk/agent/openai_client.py
Summary call capped ≤1024 while configured `reasoning_effort` (line 118) still sent; on gpt-5-class models the reply comes back empty and always degrades to the notice — exactly what the module docstring warns about.
- Fix: On 'none', send `reasoning_effort='minimal'`/'low' when configured, or add headroom; else document unreliability on reasoning models. Pin with a test.

### R5 RT-006 — medium — agent_sdk/agent/loop.py
`_final_summary` (line 518) ignores `stop_reason`; a max_tokens cut-off summary is shown and stored. Bedrock 'none' can also return lead-in text next to a dropped toolUse.
- Fix: On 'max_tokens' (or dropped tool calls leaving only a lead-in), add a fixed truncation suffix or fall back to the notice. Test both.

### R5 RT-007 — medium — tests/test_gh155_cap_summary.py
Only the max_turns exit tested end to end (`test_a2a_failed_status_message_carries_summary`, `test_ag_ui_text_then_run_error`); budget exit loop-level only. `test_settings_expose_final_summary_max_tokens` only checks the alias string.
- Fix: End-to-end A2A send and AG-UI tests crossing the token budget; build_app test setting both env vars and asserting `app.state.loop_policies`.

### R5 RT-008 — medium — tests/test_gh154_current_date.py
test_resumed_task_reuses_original_date (line 136) never interrupts/resumes; only assertion behind `if rec is not None` (None if `InMemoryTaskStore._records` is renamed). A2A message:stream timezone override untested.
- Fix: action_gate interrupt, clock past midnight, resume, assert post-resume prompt has the original date; remove the guard; add a message:stream variant of the override test.

### R5 RT-009 — low — agent_sdk/agent/runner.py
Date line computed at line 1200 before the try/except; a raise leaves the task in a non-terminal state with open streams.
- Fix: Move inside the try, or wrap so failure falls back to no date line with a fixed log message.

### R5 RT-010 — low — agent_sdk/agent/runner.py
Helpers between the RT-A-002 comment and `_TASK_FAILED_TOOL_RESULT_TEXT`, so the security comment sits above the wrong symbol. Zone validation implemented twice (config no length cap, runner 64-char cap); `from zoneinfo` import out of order.
- Fix: Move helpers above the comment; config calls runner's (or a shared common/) helper; sort imports.

### R5 RT-011 — low — docs/deployment.md
GH-155 bullet inside the GH-154 section; `AGENT_SDK_FINAL_SUMMARY_MAX_TOKENS` has no bullet. DESIGN.md:469 GH-155 aside breaks the '→ typed failure event (cost-runaway guard …)' sentence with a second parenthetical.
- Fix: '### Final summary on capped runs (GH-155)' with one bullet per env var; move the DESIGN.md aside into its own sentence.

### R5 RT-012 — low — agent_sdk/agent/loop.py
When the task is sealed during the summary call (line 512), `_final_summary` returns before yielding the UsageEvent, so tokens for a real call are never reported. Notice fallback bridges with '(no response)' instead of the notice.
- Fix: Yield UsageEvent before the sealed check; `bridge_trailing_user(messages, notice)`.

### R5 RT-013 — low — agent_sdk/routes/a2a.py
Both `_start_worker` call sites (~L571, ~L826) pass raw `(params.message.metadata or {}).get('timezone')` into `str | None` params; message_send continuation over-indented. `ag_ui._user_timezone` has the same wrong annotation.
- Fix: Annotate `object`, or filter to str at extraction; fix indentation.

### R6 RT-002 — medium — agent_sdk/agent/loop.py
`_final_summary` (line 482) ignores `stop_reason`; a summary that hits `final_summary_max_tokens` is shown and stored as the final answer — what GH-155 exists to stop.
- Fix: On max_tokens, add a fixed 'cut short' note or fall back to the notice; consider notice-only when max_tokens < 256. Test both.
- Codify: see Codify candidates.

### R6 RT-003 — medium — agent_sdk/agent/bedrock.py
With 'none' and tool history, toolConfig still sent; line 417 drops tool calls but keeps the lead-in text, which `_final_summary` delivers. `test_bedrock_none_keeps_toolconfig_with_tool_history_and_drops_calls` asserts this (text_segments == ['words'] with stopReason tool_use).
- Fix: On 'none' + 'tool_use', return empty text_segments, or keep stop_reason and treat 'tool_use' as unusable in `_final_summary`. Update the test.
- Codify: see Codify candidates.

### R6 RT-004 — medium — agent_sdk/config.py
`_valid_timezone` (line 265) always runs; no tzdata; ZoneInfo('UTC') raises on hosts without zone data with a misleading IANA error. `current_date_line` has the same per-task dependency.
- Fix: Lower-bound `tzdata` dependency, or UTC via `datetime.timezone.utc`; skip/warn when inject_current_date is False; test with zone search path removed.
- Codify: see Codify candidates.

### R6 RT-005 — medium — tests/test_gh154_current_date.py
Resume test never interrupts, resumes or moves the clock; assertion behind `hasattr(..., '_records')` and `if rec is not None`. Reuse branch never exercised with a value already set.
- Fix: Run run_task_worker on a record with date_line set and a later clock, assert reuse; or drive interrupt/resume via the action gate. Remove the guard.
- Codify: see Codify candidates.

### R6 RT-006 — medium — tests/test_gh155_cap_summary.py
Only max-turns tested end to end (lines 189-213); budget exit loop-level only. `/v1/message:stream` untested for both the summary and the GH-154 timezone override.
- Fix: A2A send + stream and AG-UI tests with low AGENT_SDK_TASK_TOKEN_BUDGET and a scripted high-usage tool_call; assert state failed, summary + 'task token budget exceeded', text before RUN_ERROR. Add a message:stream timezone-override test.
- Codify: see Codify candidates.

### R6 RT-007 — medium — DESIGN.md
§8 snippet (line 463) still old; the real Protocol (agent_sdk/agent/model_client.py:27-34, top-level export) requires `tool_choice`. Implementers following DESIGN.md fail type-checking and silently lose summaries.
- Fix: Update the snippet with `tool_choice: Literal['auto','none'] = 'auto'`; one sentence: must accept it and not return tool calls on 'none'.
- Codify: see Codify candidates.

### R6 RT-008 — medium — CHANGELOG.md
All [Unreleased] entries (lines 9-15) under Added, though several are default-on changes (date line, extra paid call, failed status.message text, 'task deadline exceeded' at max-turns). ModelClient Protocol change has only a bold sentence, no Migration line. Repo convention (e.g. line 1252) uses '⚠️ Behavior changes'.
- Fix: Move default-on effects under Behavior changes; add Migration lines for custom ModelClients and clients parsing failed status.message; keep only new knobs/fields under Added.
- Codify: see Codify candidates.

### R6 RT-009 — medium — harness/skills/add-artifact/SKILL.md
add-artifact skill (lines 30, 49-50; mirrored in template/.claude/skills/add-artifact/SKILL.md) still teaches `{{ today }}` via `/add-artifact --vars today`. SDK agents render artifact_vars once at boot (app.py:630), baking a stale date that now conflicts with GH-154's per-task date. GH-154 only updated the artifacts.py docstring.
- Fix: In both copies, state SDK agents get the per-task date automatically (AGENT_SDK_INJECT_CURRENT_DATE / AGENT_SDK_TIMEZONE); limit `--vars today` to pre-SDK agents; warn against `today` in artifact_vars.
- Codify: see Codify candidates.

### R6 RT-010 — low — agent_sdk/agent/runner.py
Date line (lines 1200-1205) computed before `try:`; a raise means no terminal frame, streams never closed (A2A SSE and AG-UI `while not mapper.terminal_sent` hang). Helpers (1148-1172) between the RT-A-002 comment and its constant.
- Fix: Move inside the try or fall back to a UTC line; move helpers above the comment.
- Codify: see Codify candidates.

### R6 RT-011 — low — docs/deployment.md
GH-155 `AGENT_SDK_FINAL_SUMMARY` / `AGENT_SDK_FINAL_SUMMARY_MAX_TOKENS` bullet (line 684) inside the GH-154 section.
- Fix: Own subsection, e.g. '### Final summary on turn/budget limit (GH-155)'.
- Codify: see Codify candidates.

### R6 RT-012 — low — agent_sdk/agent/runner.py
In the FAILED DoneEvent branch (~line 1408), the summary goes only into status.message, not task.history (unlike COMPLETED). A2A streaming clients get the summary twice: WORKING frame from the TextEvent, then the FAILED message.
- Fix: Append the summary agent message to task.history when `event.summary` is set, or document why not; note the duplicate frame in DESIGN.md §5.1.
- Codify: see Codify candidates.

### R6 RT-013 — low — agent_sdk/routes/a2a.py
Metadata timezone reads (571-574, 826-829) and `ag_ui._user_timezone` (ag_ui.py:591-595) return any JSON value into `str | None` params. message_send `_start_worker(` mis-indented. runner.py:21 `from zoneinfo` before `from typing`.
- Fix: Annotate `object`/`Any` or coerce at the route; fix indentation and import order.
- Codify: see Codify candidates.

### R7 RT-004 — medium — tests/test_gh154_current_date.py
Resume test never interrupts/resumes; assertion behind `hasattr(task_store, '_records')` and `if rec is not None`. No real coverage on A2A or AG-UI resume.
- Fix: Real ToolInterrupt/action_gate; clock crossing midnight; resume over A2A (message with taskId) and AG-UI (resume entry); assert every model call's prompt ends with the original date; drop the guard and use `store.get()`.

### R7 RT-005 — medium — agent_sdk/agent/loop.py
`_final_summary` (loop.py:440-488) accepts any non-blank text, ignoring `stop_reason` (Bedrock 'max_tokens' / OpenAI 'length'). On Bedrock, bedrock.py:415-418 clears tool_calls, so a lead-in with a dropped toolUse is delivered, though the AC sends tool-only replies to the notice.
- Fix: 'tool_use' → notice (or append notice after text); 'max_tokens' → append a fixed truncation note. Test both.

### R7 RT-006 — medium — agent_sdk/agent/runner.py
Date line computed in run_task_worker's prologue (~1200-1205) before the try. If ZoneInfo/`current_date_line` raises (unreadable zone file, subclass-supplied non-str zone), the asyncio task dies unretrieved, no FAILED committed, subscribers wait until TTL.
- Fix: Move inside the try, or make it total with a UTC fallback via `datetime.timezone.utc`, logging no raw value.

### R7 RT-007 — medium — agent_sdk/agent/loop.py
Max-turns exit checks the deadline first (loop.py:1782-1785) and returns 'task deadline exceeded' even with `final_summary=False`, contradicting the AC ('same error code') and the opt-out claim.
- Fix: Gate the pre-check on `policies.final_summary`, or keep the max-turns error and only skip the summary call. Add a `final_summary=False` test asserting the original error.

### R7 RT-008 — medium — DESIGN.md
Custom ModelClient without `tool_choice` raises TypeError, silently turned into the notice. DESIGN.md §8 (line 463) shows the old signature. CHANGELOG puts this, the extra billed call and the prompt change under Added.
- Fix: Update §8; move GH-154/155 default-on changes and the ModelClient requirement into '⚠️ Behavior changes' with a migration callout; optionally detect `tool_choice` support with `inspect.signature`.

### R7 RT-009 — medium — agent_sdk/routes/a2a.py
`message.metadata.timezone` is wired at both call sites (~L571, ~L826) but only /v1/message:send is tested (override, fallback, hostile values). /v1/message:stream, used by the console and acceptance suite, has no coverage.
- Fix: Add a /v1/message:stream test in tests/test_gh154_current_date.py with a valid zone and a hostile zone (newline, NUL); assert the prompt suffix and that the marker is absent from SSE frames, logs and prompt.

### R7 RT-010 — low — agent_sdk/agent/runner.py
Helpers between the RT-A-002 SI-2 comment and `_TASK_FAILED_TOOL_RESULT_TEXT`; `zoneinfo` import before `typing`; a2a.py:571-574 12-space indent.
- Fix: Move helpers above the comment or into a common module shared with `config._valid_timezone`; sort imports; fix indentation.

### R7 RT-011 — low — docs/deployment.md
GH-155 bullet under the GH-154 heading; states the operator `max_completion_tokens` ceiling as available though not settable from env (see that round's RT-002).
- Fix: Own GH-155 subsection; correct the ceiling statement or wire the setting.

### R7 RT-012 — low — agent_sdk/routes/ag_ui.py
`_user_timezone` (ag_ui.py:426-430) and A2A `.get('timezone')` sites pass any JSON value as `str | None`; mypy cannot see it because `.get()` returns Any.
- Fix: Run `valid_timezone()` at the route edge, or type as `object`.

### R8 RT-001 — medium — agent_sdk/agent/loop.py
`_final_summary` always passes `tool_choice='none'`; a client written to the pre-0.9.x protocol raises TypeError, swallowed, so every cap exit degrades to the notice. CHANGELOG lists this implementer-breaking change under Added.
- Fix: Probe once whether `converse` accepts `tool_choice` (named param or `**kwargs`); if not, call without it and drop returned tool_calls. Move the requirement into '### Changed (breaking for custom ModelClient implementers)'.
- Codify: see Codify candidates.

### R8 RT-002 — medium — agent_sdk/agent/bedrock.py
Bedrock still sends toolConfig when history has tool blocks, so the model can reply with a preamble plus toolUse (stop_reason 'tool_use'); converse drops tool_calls, keeps the preamble, and `_final_summary` shows 'Let me look up X…' as the final answer.
- Fix: Treat an original stop_reason 'tool_use' (or dropped tool calls) as unusable and use the notice; or keep text only on end_turn/max_tokens. Test with raw reply `[{text:'Let me check'},{toolUse:…}]` at a cap exit.
- Codify: see Codify candidates.

### R8 RT-003 — medium — agent_sdk/agent/openai_client.py
Summary call always sends `max_completion_tokens=min(1024, operator cap)`; on gpt-5 / reasoning deployments hidden reasoning often uses all of it, so GH-155's benefit is off by default on that backend; only a warning log mitigates it.
- Fix: Raise the default for the summary call when reasoning_effort is configured, or retry once with a larger cap on empty + finish_reason='length'. At minimum, note the caveat in harness/skills/setup/SKILL.md, not only docs/deployment.md.
- Codify: see Codify candidates.

### R8 RT-004 — medium — harness/skills/add-artifact/SKILL.md
add-artifact skill and template mirror (lines 43-50, 79, 149-161) still say to render the prompt per request with `today=today_iso`. GH-154 now appends a per-task date by default, and SDK agents build the persona once at boot, so following the skill gives a stale or duplicate, conflicting date.
- Fix: Drop `today=`/`now_utc=` render-time guidance for SDK agents in both copies; point to AGENT_SDK_INJECT_CURRENT_DATE / AGENT_SDK_TIMEZONE; tell migrators to remove persona date placeholders.
- Codify: see Codify candidates.

### R8 RT-005 — medium — DESIGN.md
§8 'ModelClient seam' (~462-463) still lacks `tool_choice`; out of step with agent_sdk/agent/model_client.py.
- Fix: Add `tool_choice: Literal['auto','none'] = 'auto'` and one sentence: honor 'none' or drop returned tool calls; Bedrock keeps toolConfig when history has tool blocks.
- Codify: see Codify candidates.

### R8 RT-006 — medium — tests/test_gh155_cap_summary.py
LRN-077: no test proves `AGENT_SDK_FINAL_SUMMARY` / `_MAX_TOKENS` travel through build_app() into `app.state.loop_policies`; end-to-end tests use defaults and the settings test checks only the alias. A hard-coded `final_summary=True` in app.py would pass every test.
- Fix: build_app() test with FINAL_SUMMARY=false and MAX_TOKENS=77 asserting both policy values; an end-to-end A2A run with FINAL_SUMMARY=false asserting a bare error and exactly one model call.
- Codify: see Codify candidates.

### R8 RT-007 — medium — tests/test_gh154_current_date.py
Resume test runs one non-interrupting task, asserts only inside `if rec is not None`, and the clock iterator holds one value. The `record.date_line` reuse branch is never run by any SDK path (both routes call run_task_worker only on fresh records).
- Fix: Real input-required interrupt/resume with the clock past midnight, unconditional assertion on the post-resume 'Today is' line; plus a unit test calling run_task_worker twice on one record with different clocks asserting date_line unchanged.
- Codify: see Codify candidates.

### R8 RT-008 — medium — agent_sdk/common/tz.py
New reusable helpers `load_zone()` and `valid_timezone()` (untrusted IANA zone validation, length cap, no echo, SI-2) are not registered in workspace/components/README.md, so future features (e.g. contrib/commitments scheduling) may write a weaker second validator.
- Fix: Register agent_sdk/common/tz.py (`load_zone`, `valid_timezone`, `MAX_TZ_LEN`) as a new C-NNN with its contract: never raises, never echoes input, 'UTC' needs no zone data, required entry point for caller-supplied zones.
- Codify: see Codify candidates.

### R8 RT-009 — low — tests/test_gh155_cap_summary.py
Only the max-turns exit is tested through A2A and AG-UI; token-budget exit only at run_loop level.
- Fix: A2A and AG-UI route tests with low AGENT_SDK_TASK_TOKEN_BUDGET and a scripted large-usage tool_call; assert state failed, summary + 'task token budget exceeded', TEXT_MESSAGE_CONTENT before RUN_ERROR.

### R8 RT-010 — low — agent_sdk/config.py
New settings unbounded: negative `final_summary_max_tokens` silently treated as 0 (notice only) instead of rejected; `openai_reasoning_effort` is a free str sent verbatim, so a typo surfaces only as a generic 'model invocation failed' at the first call.
- Fix: `Field(default=1024, ge=0)`; type `openai_reasoning_effort` as `Literal['minimal','low','medium','high'] | None` (or validate) so bad values fail at boot with a fixed message.

### R8 RT-011 — low — agent_sdk/agent/runner.py
Date-line computation (`current_date_line` -> `load_zone`) runs before the worker's try/terminal guard; a runtime raise (zone data removed/upgraded after boot, unvalidated direct-caller `timezone_name`) kills the worker with no terminal state; streams wait until TTL.
- Fix: Small try falling back to UTC (`timezone.utc`) with a fixed log message, or move inside the existing try so FAILED is committed.

### R8 RT-012 — low — docs/deployment.md
GH-155 settings `AGENT_SDK_FINAL_SUMMARY`, `AGENT_SDK_OPENAI_REASONING_EFFORT`, `AGENT_SDK_OPENAI_MAX_COMPLETION_TOKENS` sit under the GH-154 heading; `AGENT_SDK_FINAL_SUMMARY_MAX_TOKENS` has no bullet.
- Fix: Split into 'Current date in the system prompt (GH-154)' and 'Summary at the turn/budget limit (GH-155)' with a bullet for `AGENT_SDK_FINAL_SUMMARY_MAX_TOKENS`; move the two OpenAI settings to the model-backend section.

### R8 RT-013 — low — agent_sdk/routes/a2a.py
Two `_start_worker(...)` calls (~L571, ~L826) over-indented and use inline `(params.message.metadata or {}).get('timezone')` while AG-UI has `_user_timezone()`. GH-154 AC says 'New Agent/Settings options' but only Settings fields were added; the choice is not recorded.
- Fix: Add `_user_timezone(params)` to a2a.py and fix indentation. Either add `inject_current_date`/`timezone` kwargs to Agent, or note in the todo/CHANGELOG that they are settings-only like other loop policies.
