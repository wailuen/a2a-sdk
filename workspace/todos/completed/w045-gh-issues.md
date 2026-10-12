# w045 — GitHub issues 154–155

Sourced from open issues on wailuen/a2a-sdk (a2a-pitchbook /acceptance run-020).
Maintainer rulings 2026-10-11:
Checkable reference: https://github.com/wailuen/a2a-sdk/issues/154#issuecomment-6109637560
Checkable reference: https://github.com/wailuen/a2a-sdk/issues/155#issuecomment-6109637759
Both items edit `agent_sdk/agent/runner.py`, so run them in order: G1 then G2.
Target: next release (version chosen at /sdk-release).

---

- [x] `GH-154` System prompt carries the current date per task ‖ group:G1
  - Creates: (modifies `agent_sdk/agent/runner.py`, `agent_sdk/app.py`, `agent_sdk/config.py`, `agent_sdk/routes/a2a.py`, `agent_sdk/routes/ag_ui.py`, `agent_sdk/tasks/store.py` (`TaskRecord.date_line`), `agent_sdk/agent/artifacts.py` (docstring only), new `tests/test_gh154_current_date.py`, `DESIGN.md`, `docs/deployment.md`, `CHANGELOG.md`)
  - Reads: `agent_sdk/app.py:621-642,823-824`, `agent_sdk/agent/runner.py:1150-1158,1200-1204`, `agent_sdk/routes/a2a.py:440-447`, `agent_sdk/routes/ag_ui.py:492-499`, `agent_sdk/agent/loop.py:1001,1141-1142`, `DESIGN.md:190`
  - Severity: medium
  - Root cause: `build_app()` renders the system prompt once and stores it on `app.state.system_prompt`; A2A and AG-UI pass that same string to every task. No per-request date exists, so models guess the year and send out-of-range dates to date-bounded tools.
  - AC: New Agent/Settings options `inject_current_date` (default **True**, env `AGENT_SDK_INJECT_CURRENT_DATE`) and `timezone` (default `"UTC"`, env `AGENT_SDK_TIMEZONE`). Boot fails with a clear message on an invalid IANA zone.
  - AC: Helper `current_date_line(tz, now=...)` returns `Today is YYYY-MM-DD (<tz>).` — date only, no time; unit-tested with an injected clock.
  - AC: The line is computed once per task in the worker and appended as the LAST segment (after persona, skills catalog, A2UI section): `system_for_task = state.system_prompt + "\n\n" + line`. `app.state.system_prompt` is never mutated (DESIGN.md:190). Resumed/interrupted turns of the same task reuse the task's original date.
  - AC: Per-request user time zone, optional: AG-UI `RunAgentInput.forwardedProps.timezone`, A2A `message.metadata.timezone`. Accepted only if it is a valid IANA name (`zoneinfo`), length-capped; otherwise silently fall back to the agent setting. The value is never echoed into errors or logs beyond the validated zone name.
  - AC: Tests: two tasks with a clock crossing midnight get different dates; user zone overrides agent zone for both A2A and AG-UI; invalid user zone falls back; with `inject_current_date=False` the system prompt is byte-identical to before; line is the final segment. Existing tests that assert an exact system prompt are updated, not skipped.
  - AC: DESIGN.md §2 documents the per-task date suffix (placed last for future prompt-cache stability); `artifacts.py` docstring `today=` example marked superseded; docs/deployment.md lists both env vars; CHANGELOG `[Unreleased]` entry.
  - GH: https://github.com/wailuen/a2a-sdk/issues/154
  - Reuses: C-007  # The per-request timezone from A2A message.metadata.timezone and AG-UI forwardedProps.timezone is untrusted. On the fallback path, log nothing about the rejected value, or only sanitize_text(raw, max_len=...). Never put the raw value in an f-string. Only the validated zoneinfo name may reach the prompt or a log.
  - SI: SI-2  # This todo reads a new untrusted field from caller requests (A2A message.metadata.timezone, AG-UI RunAgentInput.forwardedProps.timezone) in agent_sdk/routes/a2a.py and agent_sdk/routes/ag_ui.py, and it adds a boot-time validation error for AGENT_SDK_TIMEZONE. The raw user value must never be interpolated into an exception, a log line or the system prompt; only the zoneinfo-validated name may be. Add a test that an invalid zone containing control characters or newlines does not appear in captured logs or in the prompt.

- [x] `GH-155` Capped run (max_turns / token budget) ends with a summary, not cut-off text ‖ group:G2
  - Creates: (modifies `agent_sdk/agent/loop.py`, `agent_sdk/agent/model_client.py`, `agent_sdk/agent/bedrock.py`, `agent_sdk/agent/openai_client.py`, `agent_sdk/agent/runner.py`, `agent_sdk/config.py`, `tests/test_loop.py`, `tests/test_gh147_assistant_turn_fold.py`, new `tests/test_gh155_cap_summary.py`, `agent_sdk/agent/events.py` (new `DoneEvent.summary`), `agent_sdk/app.py` (`final_summary=settings.final_summary` wiring; shared with G1), `agent_sdk/testing/fake_model.py` (`tool_choice` param + `calls` key), `DESIGN.md`, `docs/deployment.md`, `CHANGELOG.md`, `workspace/learning/LRN-144-transcript-bridge-must-cover-out-of-loop-writers.md` (Check amended for `_final_summary`))
  - Reads: `agent_sdk/agent/loop.py:174-178,1133-1145,1661-1662`, `agent_sdk/agent/model_client.py:27-34`, `agent_sdk/agent/bedrock.py:298-311`, `agent_sdk/agent/openai_client.py:114-120`, `agent_sdk/agent/runner.py:1363-1384`, `agent_sdk/routes/ag_ui.py:401-406`, `DESIGN.md:465`
  - Severity: medium
  - Root cause: both cap exits yield `DoneEvent(ok=False)` without another model call; the runner commits FAILED with only the error string, so the user gets no answer and gathered tool results are lost.
  - AC: `ModelClient.converse` gains optional `tool_choice: Literal["auto","none"] = "auto"`. OpenAI/Azure send `tool_choice="none"`. Bedrock keeps `toolConfig` whenever history has toolUse/toolResult blocks (Converse rejects it otherwise) and discards any returned tool_calls when `"none"`. Anthropic client (if present) handled equivalently.
  - AC: OpenAI client honors a passed `max_tokens` as `min(max_tokens, max_completion_tokens)` so the summary call is bounded.
  - AC: New `LoopPolicies.final_summary` (default **True**, env `AGENT_SDK_FINAL_SUMMARY`) and `final_summary_max_tokens` (default 1024). `final_summary_max_tokens` is the summary call's OUTPUT cap only (min with `max_output_tokens`). The call is made at both cap exits regardless of how far spend overshot; the fixed notice is used only when the call fails or returns no usable text. (Corrected w045 round 5 to the GH-155 maintainer ruling as written; the earlier planner-added spend-allowance skip rule, and the round-4 re-send charging built on it, narrowed the ruling without sign-off.)
  - AC: Helper `_final_summary()` used at both cap exits: appends the summarize instruction to the trailing user turn (no two same-role messages in a row; before `bridge_trailing_user`), makes one tools-disabled call, yields TextEvent + UsageEvent, folds the reply via `append_assistant_turn`, re-checks `is_sealed()` after the await.
  - AC: If the summary call raises, returns empty text, or returns only tool calls, yield a fixed SDK notice TextEvent ("I reached my step/budget limit before finishing. …") instead. No secrets or raw provider errors in the notice.
  - AC: The run **stays failed** (ruling): `DoneEvent(ok=False)` with the same error code; A2A task state `failed` with the summary/notice text included in `status.message`; AG-UI emits the summary text then RUN_ERROR. Deadline and sealed exits are unchanged (no extra call).
  - AC: Tests: summary on max_turns and on budget exit (A2A status message carries it, state failed; AG-UI text then RUN_ERROR); fallback notice when model raises; `final_summary=False` restores old behavior; transcript alternation holds; Bedrock request for the summary call includes toolConfig when history has tool blocks; OpenAI sends `tool_choice="none"` and the bounded max tokens. Existing cap tests updated, not skipped.
  - AC: DESIGN.md:465 notes the summary-before-failure behavior (substance unchanged: still a typed failure); docs/deployment.md lists the env var; CHANGELOG `[Unreleased]` entry.
  - SI: SI-2 — no secrets or raw upstream errors in the notice or status message.
  - GH: https://github.com/wailuen/a2a-sdk/issues/155
  - Reuses: C-017  # _final_summary must use the existing loop.py helpers bridge_trailing_user and append_assistant_turn (agent_sdk/agent/loop.py:802) to fold the summarize instruction and reply. Do not hand-roll a new fold. The AC names them, so keep them as the only path and test alternation through them.
  - Reuses: C-019  # The FAILED commit that now carries the summary or notice text in status.message must still go through set_task_status (agent_sdk/agent/runner.py, DoneEvent branch ~L1376). Build the message from text_segments plus error_msg there. Do not mutate record.task.status directly.
  - Reuses: C-007  # If the summary-call failure is logged, log only an SDK-fixed reason or sanitize_text/frame_locations output from agent_sdk/common/redact.py. Never log str(exc) from Bedrock or OpenAI. The fixed notice stays a module constant, the same way _TASK_FAILED_TOOL_RESULT_TEXT is.

---

**Archived 2026-10-12 (by /gh-review).** sdk-wave run wf_855518c4-adc: both items landed; phase redteam
used all 8 rounds (round-4 debug briefly narrowed the GH-155 budget ruling, then restored to
output-only cap per the ruling). Wave ended testsRed on two test-hygiene failures (component README
line anchor; tzdata-blocking control in test_gh154_current_date.py) — both fixed by hand, suite green.
protocolBlocked by two HIGHs pre-existing in v0.9.0, not caused by this wave; maintainer chose to ship
and file them: GH-158 (AG-UI parentMessageId null), GH-159 (A2A non-text parts dropped).
