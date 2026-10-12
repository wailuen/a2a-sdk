wave: w045
group: G2
date: 2026-10-11
status: non-blocking (medium/low)

Non-blocking — these did not block w045's archive. Address opportunistically or fold into a future wave.

Findings were accumulated across every unit redteam round for group G2 and deduped by file+description. Redteam IDs restart each round, so each heading carries its round label (R1 = RT-004..RT-008; R2 = RT-002..RT-011; R3 = RT-002..RT-008; R4 = RT-004..RT-011; R5 = RT-001..RT-011). Many findings recur across rounds with different wording. They are kept separately because their descriptions differ, and the theme index below groups them. All are flagged sdkCandidate.

## Needs maintainer ruling before any fix

- R5 RT-005: the wave changed the GH-155 budget rule itself (the summary allowance charges only output tokens, not the re-sent transcript). Per project policy a reinterpretation made inside a wave is a proposal until the user ratifies it. Record approval (or rejection) as a comment URL on GH-155.
- R5 RT-001: the budget-exit summary is nearly unreachable with realistic per-turn costs. The finding itself says to escalate for a ruling on GH-155 before changing the rule.

## Theme index

- Budget-exit summary nearly unreachable (allowance of +1024 is smaller than one normal turn; test uses a 1-token overshoot): R5 RT-001
- Budget allowance rule reinterpreted (output-only) without recorded maintainer approval: R5 RT-005
- `last_input_tokens` resets to 0 on resume while `total_tokens` carries over, so fresh and resumed runs get different caps: R2 RT-002
- Max-turns exit applies no budget allowance when under budget; the two exits treat the allowance differently: R2 RT-008
- Summary call has no minimum cap and ignores `stop_reason`, so cut-off text is shown as the final answer: R2 RT-003, R3 RT-002, R5 RT-002
- OpenAI/Azure reasoning models: `reasoning_effort` still sent while `max_completion_tokens` <= 1024, so reasoning eats the cap and the summary comes back empty; module docstring now inaccurate: R1 RT-004, R2 RT-004, R3 RT-003, R4 RT-007, R5 RT-003
- Bedrock with tool_choice='none': lead-in text sent alongside a dropped toolUse is delivered as the summary: R1 RT-006
- `ModelClient.converse` gained `tool_choice`: DESIGN.md §8 not updated; custom clients silently degrade via broad `except`: R2 RT-005, R3 RT-005, R4 RT-004, R5 RT-004
- No end-to-end (A2A send/stream, AG-UI) test of the budget exit; no realistic-token or combined-cap tests: R1 RT-005, R2 RT-006, R3 RT-004, R4 RT-005, R5 RT-006
- No test that AGENT_SDK_FINAL_SUMMARY reaches `app.state.loop_policies`: R4 RT-006
- CHANGELOG files GH-155 under Added instead of Behavior changes; no migration line for custom ModelClients: R2 RT-007, R4 RT-008
- Max-turns exit now checks the deadline first and reports 'task deadline exceeded' (also when final_summary=False), contradicting 'same error code': R3 RT-008, R4 RT-011, R5 RT-007
- docs/deployment.md: AGENT_SDK_FINAL_SUMMARY under the GH-154 heading; `final_summary_max_tokens` presented as tunable but has no setting/env var: R1 RT-007, R2 RT-011, R3 RT-007, R4 RT-010, R5 RT-008
- GH-154 helpers inserted between the RT-A-002 comment and `_TASK_FAILED_TOOL_RESULT_TEXT`; `zoneinfo` import unsorted: R1 RT-008, R2 RT-010, R5 RT-009
- FAILED branch: summary not appended to task.history; summary sent twice (WORKING frame then FAILED message); uses `event.summary` not `text_segments` per C-019 note: R1 RT-008, R2 RT-009
- FakeModelClient docstring and docs/testing.md do not mention the extra tool_choice='none' call on capped runs: R3 RT-006
- Notice-fallback path folds '(no response)' into the transcript instead of the notice the user saw: R4 RT-009
- test_token_budget_exceeded asserts `done.summary == "never reached"` (name contradicts behavior): R5 RT-010
- `_user_timezone` / A2A timezone extraction annotated `str | None` but returns any JSON value; a2a.py `_start_worker` continuation mis-indented: R5 RT-011

## Codify candidates

- R3 RT-002: A last-chance summary call needs a minimum output floor and a truncation check, otherwise it reintroduces the cut-off-answer bug it was meant to fix.
- R5 RT-001: A cap-exit fallback whose allowance is smaller than one turn's normal cost is unreachable; test the allowance against a realistic per-turn cost, not a hand-picked 1-token overshoot.
- R5 RT-002: A bounded fallback reply must check the provider's stop reason and enforce a minimum useful cap, or it can show the same truncated output it was built to replace.
- R5 RT-003: Applying the OpenAI max_completion_tokens cap to a reasoning model must leave room for reasoning tokens; the module already documents that a small cap yields an empty completion.
- R5 RT-004: Adding a parameter to a public Protocol method is a breaking change for structural implementers; detect support at the call site instead of relying on a broad except to hide the TypeError.
- R5 RT-005: A wave must not reinterpret a budget or guard AC on its own; record maintainer ratification as an issue comment URL before archiving.
- R5 RT-006: Every cap exit named in an AC needs its own end-to-end assertion on each transport; a loop-level test does not prove the route's translation.

## Findings

### R1 RT-004 — medium — agent_sdk/agent/openai_client.py
For tool_choice='none', the client sets max_completion_tokens to min(max_tokens, configured) (openai_client.py:122-129) but still sends reasoning_effort. In OpenAI's API, max_completion_tokens covers reasoning tokens AND visible output. For reasoning models (the very case where reasoning_effort is configured), a 1024 cap is often used up by reasoning. The reply then comes back with finish_reason='length' and empty content, so the run always falls back to the notice on OpenAI/Azure reasoning deployments.
- Fix: On the tool_choice='none' call, either drop reasoning_effort or force it to the lowest supported level, or add reasoning headroom to the cap when reasoning_effort is set. Add a test asserting the summary request's reasoning_effort and max_completion_tokens when reasoning_effort is configured.

### R1 RT-005 — medium — tests/test_gh155_cap_summary.py
The coverage gap matches the AC's test list. The AC requires end-to-end tests of the budget exit too ('summary on max_turns and on budget exit (A2A status message carries it, state failed; AG-UI text then RUN_ERROR)'), but the A2A and AG-UI tests only set AGENT_SDK_MAX_TURNS=1. No test drives the budget exit through the routes. No test uses realistic input-token counts on the summary reply (which would have caught RT-001). No test covers max_turns combined with an exceeded budget or deadline (RT-002).
- Fix: Add test_a2a_budget_failed_status_message_carries_summary and an AG-UI version with AGENT_SDK_TASK_TOKEN_BUDGET set low and a scripted tool_call carrying input/output tokens. Add the realistic-token and combined-cap loop tests from RT-001 and RT-002.

### R1 RT-006 — low — agent_sdk/agent/bedrock.py
With tool_choice='none' and tool blocks in history, toolConfig is still sent (correct for Converse), so the model can still emit toolUse. bedrock.py:416 throws away the tool calls but keeps any text sent alongside them. That text is usually a lead-in such as 'Let me look that up', and it is delivered as the user's final summary and folded into the transcript. The AC treats a reply of only tool calls as unusable, but a lead-in plus a tool call slips through.
- Fix: When tool_choice='none' and stop_reason == 'tool_use', return empty text_segments, or keep stop_reason and have _final_summary treat stop_reason 'tool_use' as unusable so the run falls back to the notice. Add a test using _BEDROCK_RAW (text + toolUse, stopReason tool_use).

### R1 RT-007 — low — docs/deployment.md
AGENT_SDK_FINAL_SUMMARY (GH-155) is listed inside the 'Current date in the system prompt (GH-154)' subsection (docs/deployment.md:106), between the two GH-154 variables. Operators looking for cap behaviour will not find it there, and the section heading is now wrong.
- Fix: Move the bullet to its own subsection, e.g. '### Final summary on turn/budget limit (GH-155)'. Note there that the task still ends as failed and that final_summary_max_tokens is not settable through an environment variable.

### R1 RT-008 — low — agent_sdk/agent/runner.py
The GH-154 helpers (_MAX_TZ_LEN, _clock_now, valid_timezone, current_date_line) were inserted between the RT-A-002 comment block and the constant it documents (runner.py:1142-1173). That comment now sits above _MAX_TZ_LEN, detached from _TASK_FAILED_TOOL_RESULT_TEXT. Separately, the FAILED branch (runner.py:1410) builds status text from event.summary rather than text_segments as the C-019 Reuses note asked. Unlike the COMPLETED path, it also does not append the summary message to task.history, so A2A clients reading history never see the summary.
- Fix: Move the GH-154 helpers above the RT-A-002 comment so the comment stays next to _TASK_FAILED_TOOL_RESULT_TEXT. In the FAILED branch, append the summary message to task.history when event.summary is set, for parity with COMPLETED, or record why it is left out.

### R2 RT-002 — medium — agent_sdk/agent/loop.py
`last_input_tokens` starts at 0 on every `run_loop` call (loop.py:1185), but `total_tokens` starts from `spent_tokens`, which carries over across resumes (runner.py:1244). A task can cross the budget on the same turn that a tool interrupts it (input-required or auth-required). On resume, the first iteration takes the budget exit with an input estimate of 0. The summary call then runs with up to `1024 - overshoot` output tokens and re-sends the full transcript. That breaks the 'at most final_summary_max_tokens beyond budget' bound in the opposite direction from RT-001. As a result, behavior depends on whether the task was ever interrupted.
- Fix: Keep the last turn's input and output tokens on the TaskRecord, next to `spent_tokens`, and pass them into `run_loop`. Or estimate the re-send size from `messages` itself. Then the budget-exit cap gives the same answer for fresh and resumed runs. Add a resumed-over-budget test.

### R2 RT-003 — medium — agent_sdk/agent/loop.py
`_final_summary` (loop.py:444-492) never checks `response.stop_reason`, and it accepts any positive `max_tokens`. When `_summary_max_tokens` returns a tiny cap (for example 5-50 tokens near the budget edge), or the model fills the 1024 cap, the reply is cut off mid-sentence. It is still streamed as the final answer and folded into the transcript. Cut-off text at the cap is exactly the symptom GH-155 is titled to remove ('ends with a summary, not cut-off text').
- Fix: Set a minimum useful cap (for example, skip the call and use the notice when `max_tokens < 256`). When `stop_reason == "max_tokens"`, either add a fixed SDK note saying the summary was cut short, or fall back to the notice. Test both cases.

### R2 RT-004 — medium — agent_sdk/agent/openai_client.py
On a summary call (`tool_choice="none"`, openai_client.py:122-129) the client sets `max_completion_tokens` to at most 1024, but still sends `reasoning_effort` when one is configured. For OpenAI and Azure reasoning models, `max_completion_tokens` counts hidden reasoning tokens too. At medium or high effort the model often spends the whole 1024 on reasoning and returns empty content with finish_reason `length`. The loop then always falls back to the notice. So reasoning-model deployments get no summary, and no warning says why.
- Fix: On the summary call, lower `reasoning_effort` (for example to the lowest supported value), or leave it out. Or add reasoning headroom to the cap when `reasoning_effort` is set, while still limiting visible output. Log a warning naming only the fixed reason when a summary comes back empty with stop_reason max_tokens. Add a test where `reasoning_effort` is set.

### R2 RT-005 — medium — DESIGN.md
The ModelClient seam block in DESIGN.md §8 (lines 462-465) still shows `converse(self, *, system, messages, tools, max_tokens)`. The Protocol in agent_sdk/agent/model_client.py:27-35 now also takes `tool_choice: Literal["auto","none"] = "auto"`. Anyone writing a custom ModelClient from the design doc will leave out the parameter. Their summaries then silently fall back to the notice, as the CHANGELOG itself warns.
- Fix: Update the §8 signature to include `tool_choice`. Add one sentence: implementations must accept it, and on `"none"` must not return tool calls (Bedrock keeps toolConfig when the history holds tool blocks and drops returned calls).

### R2 RT-006 — medium — tests/test_gh155_cap_summary.py
The AC asks for end-to-end tests of 'summary on max_turns and on budget exit (A2A status message carries it, state failed; AG-UI text then RUN_ERROR)'. The end-to-end tests (`test_a2a_failed_status_message_carries_summary`, `test_ag_ui_text_then_run_error`) only cover the max_turns exit, via `AGENT_SDK_MAX_TURNS=1`. No end-to-end test covers the budget exit on either A2A or AG-UI, and none checks the final FAILED frame on A2A `message:stream`. The unit tests check the loop events but not how the runner or routes render the budget path.
- Fix: Add A2A (`message:send` and `message:stream`) and AG-UI end-to-end tests that set `AGENT_SDK_TASK_TOKEN_BUDGET` low enough to hit the budget exit. Script the FakeModelClient so the summary call fires (this depends on fixing RT-001). Assert state `failed`, the summary plus `task token budget exceeded` in status.message, and text frames before RUN_ERROR.

### R2 RT-007 — low — CHANGELOG.md
The GH-155 entry is filed under `### Added`, but it changes default behavior. Every capped run now makes an extra paid model call, a FAILED `status.message` now starts with model text, and a run that hits both max_turns and the deadline now reports `task deadline exceeded` instead of `max turns (N) exceeded` (loop.py:1788-1791). The custom-ModelClient requirement is a migration step that is only written in bold. Past releases put default-on changes like these under `### ⚠️ Behavior changes` (CHANGELOG.md:1250, 1579; see LRN-153 and LRN-267).
- Fix: Move the GH-155 default-on effects (extra call and spend, new status.message content, deadline now taking precedence at the max-turns exit) under `### ⚠️ Behavior changes` in [Unreleased]. Add a `Migration:` line for custom ModelClient implementations. Keep only the new knobs (`LoopPolicies.final_summary`, `final_summary_max_tokens`, `AGENT_SDK_FINAL_SUMMARY`, `DoneEvent.summary`) under Added.

### R2 RT-008 — low — agent_sdk/agent/loop.py
At the max-turns exit, when `total_tokens <= token_budget` (loop.py:1792-1797), the summary cap is `min(final_summary_max_tokens, max_output_tokens)` with no budget allowance. The call re-sends the whole transcript and can push spend past `token_budget` by the full input size. The CHANGELOG says the max-turns exit 'applies the same budget cap', but it does so only when the budget is already exceeded. The two exits treat the allowance differently.
- Fix: Use one rule at both exits, the same allowance helper once RT-001 is resolved. Or reword the CHANGELOG and DESIGN.md to say the max-turns summary is charged like a normal turn.

### R2 RT-009 — low — agent_sdk/agent/runner.py
The summary is sent to A2A clients twice. The summary TextEvent sets a WORKING status whose message holds the summary (runner.py:1286-1291). Then the DoneEvent branch commits FAILED with `f"{summary}\n\n{error}"` (runner.py:1410-1419). A streaming client that shows each status.message displays the same paragraph twice. Also, the C-019 reuse note says to build the message from `text_segments` plus error_msg, but the code uses `event.summary`.
- Fix: Either do not publish the summary as a separate WORKING frame (let the FAILED frame carry it), or keep the FAILED status.message to the error only when the summary already went out as a WORKING frame. Pick one and pin it in a `message:stream` test. Update the C-019 note to match the chosen source of the text.

### R2 RT-010 — low — agent_sdk/agent/runner.py
The GH-154 helpers (`_MAX_TZ_LEN`, `_clock_now`, `valid_timezone`, `current_date_line`) were inserted between the RT-A-002 comment block and the `_TASK_FAILED_TOOL_RESULT_TEXT` constant it describes (runner.py:1142-1173). The SI-2 rationale comment now sits above `_MAX_TZ_LEN`. Also, `from zoneinfo import ...` sits between the `datetime` and `typing` imports (runner.py:21), so the import block is no longer sorted.
- Fix: Move the RT-A-002 comment back directly above `_TASK_FAILED_TOOL_RESULT_TEXT`, and put the timezone helpers above the comment or in their own section. Sort the `zoneinfo` import after `typing`.

### R2 RT-011 — low — agent_sdk/app.py
`final_summary_max_tokens` can only be set on `LoopPolicies`. `Agent.build_app()` builds LoopPolicies from settings (app.py:615-621) and does not pass it, and there is no `BaseAgentSettings` field or Agent kwarg for it. An agent built the normal way cannot change the summary cap or the budget allowance (always 1024), even though DESIGN.md and the CHANGELOG present it as a control.
- Fix: Add `final_summary_max_tokens: int = Field(default=1024, alias="AGENT_SDK_FINAL_SUMMARY_MAX_TOKENS")` with a non-negative check, wire it into the LoopPolicies built in app.py, and list it in docs/deployment.md. Or document that it is only for callers who use `run_loop` directly.

### R3 RT-002 — medium — agent_sdk/agent/loop.py
_final_summary makes the call with any max_tokens > 0. When headroom is tiny (e.g. 1-20 tokens), the full transcript is re-sent and the cut-off reply is presented as the final answer. The reply's stop_reason is never checked, so a truncated summary (Bedrock stopReason 'max_tokens' / OpenAI finish_reason 'length') is also shown as complete. GH-155 exists to stop exactly this cut-off-text symptom.
- Fix: In _final_summary, use the notice instead of calling when max_tokens is below a floor (e.g. 256). Also, when response.stop_reason == 'max_tokens', either fall back to the notice or add a fixed SDK truncation line. Add tests for both cases.
- Codify: A last-chance summary call needs a minimum output floor and a truncation check, otherwise it reintroduces the cut-off-answer bug it was meant to fix.

### R3 RT-003 — medium — agent_sdk/agent/openai_client.py
For the summary call (tool_choice='none'), max_completion_tokens is set to min(max_tokens, configured) at openai_client.py:122-129, while reasoning_effort is still sent when configured. For OpenAI reasoning models, max_completion_tokens includes hidden reasoning tokens. A 1024 cap can be used up by reasoning alone, giving empty content (finish_reason 'length'). Agents on reasoning models would then nearly always get the fixed notice instead of a summary, and no test covers reasoning_effort + tool_choice='none'.
- Fix: When tool_choice == 'none' and self._reasoning_effort is set, either send a low or minimal reasoning_effort for the summary call, or add reasoning headroom on top of the visible-output cap. Add a test in tests/test_gh155_cap_summary.py with reasoning_effort set.

### R3 RT-004 — medium — tests/test_gh155_cap_summary.py
The AC test list requires 'summary on max_turns AND on budget exit (A2A status message carries it, state failed; AG-UI text then RUN_ERROR)'. The end-to-end tests (test_a2a_failed_status_message_carries_summary, test_ag_ui_text_then_run_error) cover only the max-turns exit through AGENT_SDK_MAX_TURNS=1. No A2A or AG-UI test drives the token-budget exit, so the runner path that adds the 'task token budget exceeded' summary to status.message is unverified.
- Fix: Add A2A and AG-UI end-to-end tests built with AGENT_SDK_TASK_TOKEN_BUDGET set low and a scripted tool_call with large usage followed by reply(...). Assert state 'failed', that status.message holds both the summary and 'token budget', and that TEXT_MESSAGE_CONTENT comes before RUN_ERROR.

### R3 RT-005 — medium — DESIGN.md
The ModelClient seam snippet in DESIGN.md §8 (around line 463) still shows `async def converse(self, *, system, messages, tools, max_tokens)` without the new `tool_choice` parameter. This is the documented public extension seam, and custom ModelClient implementations that follow it will lack tool_choice. They then raise TypeError on every summary call, which is quietly caught, so the summary always falls back to the notice. Only CHANGELOG warns about this.
- Fix: Update the DESIGN.md §8 snippet to `async def converse(self, *, system, messages, tools, max_tokens, tool_choice='auto')`. Add one sentence: 'none' must disable tool use (or discard returned calls) and must be accepted by every implementation.

### R3 RT-006 — medium — agent_sdk/testing/fake_model.py
The FakeModelClient docstring (fake_model.py:52-54) and docs/testing.md:21-23 promise that exhausting the script raises and fails loudly. With final_summary on by default, every max-turns or budget exit now makes one extra converse(tool_choice='none') call. An exhausted script there is caught and turned into the notice (tests/test_loop.py::test_max_turns_exhaustion now depends on this). The extra call is also recorded in fake.calls, so downstream agent tests that count calls or script spare replies after a cap now see one more call or have a reply used as the summary. Neither doc mentions this.
- Fix: Update docs/testing.md and the FakeModelClient docstring: a capped run makes one extra tool_choice='none' call, recorded in fake.calls, and script exhaustion on that call becomes the notice. Add a CHANGELOG line aimed at downstream test suites, or have the fixture build LoopPolicies(final_summary=False) when old call counts are needed.

### R3 RT-007 — low — docs/deployment.md
The AGENT_SDK_FINAL_SUMMARY bullet (docs/deployment.md:106) sits under the '### Current date in the system prompt (GH-154)' heading, between the two GH-154 date and timezone bullets. An unrelated GH-155 setting is filed under the wrong subsection.
- Fix: Move AGENT_SDK_FINAL_SUMMARY into its own '### Final summary on capped runs (GH-155)' subsection, next to the AGENT_SDK_MAX_TURNS section.

### R3 RT-008 — low — agent_sdk/agent/loop.py
The new deadline check at the max-turns exit (loop.py around 1786) runs even when final_summary=False. A run whose deadline expired during its last turn used to end with 'max turns (N) exceeded' and now ends with 'task deadline exceeded'. This contradicts the AC 'final_summary=False restores old behavior'. test_max_turns_with_exceeded_deadline_makes_no_call asserts the new error string.
- Fix: Run the deadline check only when policies.final_summary is true (its only job is to skip the extra call). Otherwise, state the error-string change in CHANGELOG and adjust the AC wording.

### R4 RT-004 — medium — DESIGN.md
DESIGN.md §8 (line 463) still shows the ModelClient Protocol as converse(self, *, system, messages, tools, max_tokens) without the new tool_choice parameter. It also does not say that custom ModelClient implementations must accept tool_choice, even though the summary path silently falls back to the notice when they don't.
- Fix: Update the §8 snippet to include tool_choice: Literal['auto','none'] = 'auto'. Add one sentence: Bedrock keeps toolConfig when the history has tool blocks and drops any returned tool calls, OpenAI sends tool_choice='none' plus a bounded max_completion_tokens, and implementations that don't accept tool_choice degrade to the fixed notice.

### R4 RT-005 — medium — tests/test_gh155_cap_summary.py
The AC asks for end-to-end tests of the summary on BOTH the max_turns and the budget exit (A2A status.message carries it with state failed; AG-UI streams the text then RUN_ERROR). test_a2a_failed_status_message_carries_summary and test_ag_ui_text_then_run_error only set AGENT_SDK_MAX_TURNS=1. No route-level test drives the token-budget exit, which is the path RT-001 shows is dead by default.
- Fix: Add A2A and AG-UI end-to-end tests that set AGENT_SDK_TASK_TOKEN_BUDGET low and script the fake model's usage to trip the budget exit. Assert state=failed, that status.message contains the summary (or notice) plus 'token budget', and that TEXT_MESSAGE_CONTENT arrives before RUN_ERROR.

### R4 RT-006 — medium — agent_sdk/app.py
The new setting AGENT_SDK_FINAL_SUMMARY (config.py:217) is wired to LoopPolicies.final_summary at app.py:620, but no test checks that the setting reaches app.state.loop_policies. test_final_summary_false_restores_old_behavior builds LoopPolicies directly. LRN-222's Prevention asks for a test at the settings-to-object seam for every new setting.
- Fix: Add a test that builds the app with AGENT_SDK_FINAL_SUMMARY='false' and asserts app.state.loop_policies.final_summary is False. Better, run a max_turns=1 task end to end and assert the fake model receives no tool_choice='none' call.

### R4 RT-007 — medium — agent_sdk/agent/openai_client.py
For the summary call (tool_choice='none'), max_completion_tokens is forced to min(max_tokens, configured) = 1024 by default (openai_client.py:122-129). For OpenAI/Azure reasoning models, max_completion_tokens also covers reasoning tokens. With reasoning_effort set (openai_client.py:118), the model can spend all 1024 tokens reasoning and return empty content (finish_reason=length). _final_summary then always falls back to the fixed notice, so reasoning-model deployments never get a summary.
- Fix: Do not send reasoning_effort on the summary call (or send the lowest supported effort), or raise the cap by a reasoning allowance when reasoning_effort is set. Add a test asserting the request shape when reasoning_effort is configured with tool_choice='none'.

### R4 RT-008 — medium — CHANGELOG.md
The GH-155 entry is filed under '### Added', but it is a default-on change to existing behavior. Every capped run now makes an extra paid model call. A2A FAILED status.message text changes from the bare error to summary + error. A max-turns exit whose deadline has also passed now reports 'task deadline exceeded'. Custom ModelClient implementations without tool_choice now log a warning on every cap exit. These belong under a behavior-change heading per the repo's CHANGELOG conventions (LRN-153/LRN-267).
- Fix: Move the user-visible behavior shifts (extra call, status.message content, deadline-before-max-turns precedence, custom ModelClient requirement) under '### ⚠️ Behavior changes', with a short migration note (set AGENT_SDK_FINAL_SUMMARY=false; add tool_choice to custom clients). Keep only the new options under Added.

### R4 RT-009 — low — agent_sdk/agent/loop.py
On the notice-fallback path, _final_summary (loop.py:486-487) streams the fixed notice to the user but folds the default bridge text '(no response)' into the transcript via bridge_trailing_user(messages). RT-008 in bridge_trailing_user's docstring says a caller whose bridged turn followed something real should pass its own fixed SDK string. On a continuation turn the model sees '(no response)', while the user saw 'I reached my step/budget limit...'.
- Fix: Call bridge_trailing_user(messages, notice). The notice is an SDK-fixed module constant, so this is SI-2 safe. Add a test assertion on messages[-1] content for the fallback path.

### R4 RT-010 — low — docs/deployment.md
AGENT_SDK_FINAL_SUMMARY (GH-155) is listed between the two GH-154 date settings, under the heading 'Current date in the system prompt (GH-154)' (docs/deployment.md:103-108). The page does not mention that the budget-exit summary is usually skipped, or that final_summary_max_tokens has no env var.
- Fix: Give GH-155 its own subsection (for example 'Summary on turn/budget cap (GH-155)') and move the FINAL_SUMMARY bullet there. Note that final_summary_max_tokens is code-only (LoopPolicies) and explain when the fixed notice is used instead.

### R4 RT-011 — low — agent_sdk/agent/loop.py
The max-turns exit now checks deadline.exceeded() first (loop.py:1785-1788). A run that hits max_turns after the deadline has also passed now ends with error 'task deadline exceeded' instead of 'max turns (N) exceeded'. The AC says the run stays failed 'with the same error code'. This changes the terminal error for an existing exit path, and only CHANGELOG prose records it.
- Fix: Either keep the 'max turns' error and only skip the summary call when the deadline has passed, or record this precedence change as a deliberate decision on GH-155 and in DESIGN.md §8 loop policies.

### R5 RT-001 — medium — agent_sdk/agent/loop.py
The token-budget summary almost never runs in practice. `_summary_max_tokens` (loop.py:427-440) skips the call once `total_tokens >= token_budget + final_summary_max_tokens`. The budget exit (loop.py:1236) is only checked after a whole turn is charged, and each turn re-sends the full transcript (often 10k to 100k tokens). So the overshoot is usually far more than 1024, and the budget exit falls back to the fixed notice. The only passing proof, tests/test_gh155_cap_summary.py::test_budget_summary_fires_with_default_policies, uses a hand-picked 1-token overshoot (200_001), which hides this. The code matches the AC wording, but GH-155's goal ('ends with a summary') is not met on the budget exit.
- Fix: Escalate for a maintainer ruling on GH-155 before changing the rule. Options: (a) base the skip test on how far the spend ran past the budget before the last turn, or on a multiple of the budget, rather than a flat +1024; (b) predict the overshoot before starting a turn that would cross the budget, and summarize instead of starting it. Add a test where the last turn costs a realistic amount (for example 30k input) and the summary still fires, or the documented outcome is asserted.
- Codify: A cap-exit fallback whose allowance is smaller than one turn's normal cost is unreachable; test the allowance against a realistic per-turn cost, not a hand-picked 1-token overshoot.

### R5 RT-002 — medium — agent_sdk/agent/loop.py
The summary call's output cap has no lower limit, and its stop_reason is ignored. That brings back the 'cut-off text' GH-155 was filed to fix. At the budget exit the cap is `token_budget + 1024 - total_tokens`, which can be any value from 1 to 1024. Any non-empty fragment is shown as the summary (loop.py:483-489). Examples: a 3-token reply, or a 1024-token reply that stopped with stop_reason='max_tokens' mid-sentence. Both go out as the user-facing answer and into A2A status.message with no sign they were cut off.
- Fix: In `_summary_max_tokens`, treat a cap below a minimum (for example 256, or a new `final_summary_min_tokens`) as 0, which sends the fixed notice. In `_final_summary`, when `response.stop_reason == 'max_tokens'`, add a fixed SDK suffix (for example '…(summary cut short by the limit)') or use the notice instead. Add tests for a tiny cap and for a reply cut off at the limit.
- Codify: A bounded fallback reply must check the provider's stop reason and enforce a minimum useful cap, or it can show the same truncated output it was built to replace.

### R5 RT-003 — medium — agent_sdk/agent/openai_client.py
On OpenAI reasoning models (gpt-5, the model this module's own docstring targets), the summary call usually comes back empty. With tool_choice='none', `converse` now always sets `max_completion_tokens = min(max_tokens, configured)`, which is 1024 or less (openai_client.py:122-129). The module docstring (lines 14-17) says a small max_completion_tokens 'would be consumed by reasoning and yield an empty completion'. So on that backend the summary nearly always falls back to the notice. The docstring's claim 'the token cap is applied ONLY when explicitly configured' is now also false. No test covers a reasoning-model response with empty content and finish_reason='length'.
- Fix: For the summary call, leave room for reasoning tokens. Option: send max_completion_tokens = max_tokens + a reasoning reserve, and cap the visible text separately. Option: when reasoning_effort is configured, send the lowest supported effort for this call. Do not send reasoning_effort to models that do not accept it. Update the module docstring to describe the summary-call exception. Add a test where the fake completion returns content=None with finish_reason='length' and assert the fallback is documented and logged.
- Codify: Applying the OpenAI max_completion_tokens cap to a reasoning model must leave room for reasoning tokens; the module already documents that a small cap yields an empty completion.

### R5 RT-004 — medium — agent_sdk/agent/model_client.py
Public API break with no visible failure: the `ModelClient.converse` Protocol, exported from `agent_sdk` (__init__.py:19), gains a `tool_choice` parameter. Any existing custom ModelClient, and any test subclass of FakeModelClient that overrides `converse` without `tool_choice`, now raises TypeError on every capped run. `_final_summary` catches it with a broad `except Exception` (loop.py:474), logs a WARNING, and quietly sends the notice. The feature is then off for those deployments with no error the operator would notice, and mypy flags such implementations as not matching the Protocol. DESIGN.md §8 (lines 461-464) still shows the old 4-argument Protocol signature. CHANGELOG files the change under 'Added', not under a behavior-change or breaking note for implementers. The A2A failed status.message text also changes for every capped run, because notice + error replaces the bare error.
- Fix: Check once whether the client's `converse` accepts `tool_choice` (via inspect.signature, cached per client). If it does not, call without it and ignore any tool calls in the reply. When the call is skipped, log one ERROR-level warning per process that names the class. Update the DESIGN.md §8 Protocol block to include `tool_choice`. Move the CHANGELOG note to a 'Changed / Note for ModelClient implementers' heading. Also mention that status.message on capped failures changes from the bare error to text plus error.
- Codify: Adding a parameter to a public Protocol method is a breaking change for structural implementers; detect support at the call site instead of relying on a broad except to hide the TypeError.

### R5 RT-005 — medium — agent_sdk/agent/loop.py
The wave changed the budget rule itself, without recorded maintainer approval. The todo AC says the summary 'may spend at most final_summary_max_tokens beyond the budget'. The landed `_summary_max_tokens` (loop.py:427-440) charges only output tokens against that allowance; the docstring says this was decided in an earlier redteam round (RT-001). The summary call re-sends the full transcript, so a budget-exit summary can spend about one more full-context turn (up to ~token_budget again) past DESIGN.md §8's 'cost-runaway guard'. The maintainer ruling (GH-155 comment 6109637759) only asks for 'a small output cap'. It does not approve going past the budget by the input cost. Per project policy, a reinterpretation made inside a wave is only a proposal until the user ratifies it.
- Fix: Escalate this reading to the maintainer and record the approval as a comment URL on GH-155 before archiving. If it is not approved, charge input against the allowance as well, or estimate input cost from the last turn's input_tokens and skip when it would go over. Note that RT-001 makes the budget-exit summary nearly unreachable either way.
- Codify: A wave must not reinterpret a budget or guard AC on its own; record maintainer ratification as an issue comment URL before archiving.

### R5 RT-006 — medium — tests/test_gh155_cap_summary.py
The end-to-end tests miss the budget exit and the streaming route. The AC asks for 'summary on max_turns and on budget exit (A2A status message carries it, state failed; AG-UI text then RUN_ERROR)'. The only end-to-end tests (test_a2a_failed_status_message_carries_summary, test_ag_ui_text_then_run_error) use AGENT_SDK_MAX_TURNS=1. The token-budget exit is only tested at the loop level. A2A `/v1/message:stream` is never checked for a final failed status frame with summary plus error. The test also never checks that TEXT_MESSAGE_END comes before RUN_ERROR.
- Fix: Add end-to-end tests with a small AGENT_SDK_TASK_TOKEN_BUDGET for A2A send, A2A stream (assert the last status frame is failed and carries summary plus error), and AG-UI (assert TEXT_MESSAGE_START/CONTENT/END come before RUN_ERROR).
- Codify: Every cap exit named in an AC needs its own end-to-end assertion on each transport; a loop-level test does not prove the route's translation.

### R5 RT-007 — low — agent_sdk/agent/loop.py
The max-turns exit now checks the deadline first (loop.py:1785-1788). A run that hits both max_turns and the deadline used to end with 'max turns (N) exceeded' and now ends with 'task deadline exceeded'. The AC says the cap exits keep 'the same error code'. This visible change is not in the CHANGELOG.
- Fix: Keep the deadline check but report it only for skipping the summary call: use the notice and keep the 'max turns (N) exceeded' error. Or document the changed error text in the CHANGELOG.

### R5 RT-008 — low — docs/deployment.md
AGENT_SDK_FINAL_SUMMARY (GH-155) is listed inside the 'Current date in the system prompt (GH-154)' section, between the two GH-154 variables. The doc also cites `final_summary_max_tokens` (1024) as if operators can tune it, but there is no setting or env var for it. It can only be changed through LoopPolicies in code.
- Fix: Move AGENT_SDK_FINAL_SUMMARY into its own '### Final summary on cap exits (GH-155)' section. State that final_summary_max_tokens can only be set through LoopPolicies, or add an AGENT_SDK_FINAL_SUMMARY_MAX_TOKENS setting wired in app.py.

### R5 RT-009 — low — agent_sdk/agent/runner.py
The new date helpers (`_MAX_TZ_LEN`, `_clock_now`, `valid_timezone`, `current_date_line`) were inserted between the RT-A-002 comment block and the `_TASK_FAILED_TOOL_RESULT_TEXT` constant it describes (runner.py:1142-1173). That SI-2 rationale now sits above `_MAX_TZ_LEN`, so the comment points at the wrong code.
- Fix: Move the GH-154 helpers above the RT-A-002 comment, so the comment sits directly over `_TASK_FAILED_TOOL_RESULT_TEXT` again.

### R5 RT-010 — low — tests/test_loop.py
test_token_budget_exceeded now asserts `done.summary == "never reached"`. The scripted reply's text says it is never reached, but the test now proves it is reached and used as the summary. The fixture name contradicts the test.
- Fix: Rename the scripted reply text (for example "budget summary") and update the assertion.

### R5 RT-011 — low — agent_sdk/routes/ag_ui.py
`_user_timezone` (ag_ui.py:426-430) is annotated `-> str | None` but returns any JSON value from forwardedProps (dict, int, list). The A2A call sites pass `(params.message.metadata or {}).get("timezone")` into a `str | None` parameter the same way. It is safe at runtime only because `valid_timezone` accepts `object`. The type is wrong, so a future caller could treat it as a string. The `_start_worker(...)` continuation in a2a.py message_send (around line 571) is also over-indented.
- Fix: Annotate the return and parameters as `object`, or narrow with `isinstance(v, str)` in `_user_timezone` and at the A2A extraction. Fix the indentation.
