wave: w045
group: G1
date: 2026-10-11
status: non-blocking (medium/low)

Non-blocking — these did not block w045's archive. Address opportunistically or fold into a future wave.

Findings were accumulated across every unit redteam round for group G1 and deduped by file+description. Redteam IDs restart each round, so each heading carries its round label (R1 = first batch, RT-003..RT-011; R2 = second batch, RT-001..RT-008). Several findings recur across rounds with different wording. They are kept separately because their descriptions differ, and the theme index below groups them. All are flagged sdkCandidate.

## Theme index

- Default 'UTC' zone needs zoneinfo at boot and per task; no `tzdata` dependency, so boot fails on hosts without system zone data: R1 RT-004, R2 RT-002
- Resume test never interrupts/resumes and can pass with zero assertions (`hasattr`/`if rec is not None` guard): R1 RT-003, R2 RT-003
- Date line computed before run_task_worker's `try:`, so a raise leaves the task non-terminal and streams open: R1 RT-005, R2 RT-005
- GH-154 helpers inserted between the RT-A-002 comment and `_TASK_FAILED_TOOL_RESULT_TEXT`: R1 RT-008, R2 RT-006
- docs/deployment.md GH-154 section contains the GH-155 `AGENT_SDK_FINAL_SUMMARY` bullet: R1 RT-007, R2 RT-007
- a2a.py message_send `_start_worker` call mis-indented (12 spaces): R1 RT-006, R2 RT-008
- Generic `timezone` field name on stable-core BaseAgentSettings clashes with subclass fields; validator lets TypeError through: R2 RT-001
- Zone validation duplicated (config._valid_timezone vs runner.valid_timezone, 64-char cap only in one) and platform-dependent (case-insensitive filesystems): R1 RT-009, R2 RT-006
- `user_timezone: str | None` annotations wrong (raw JSON value crosses into worker): R1 RT-006
- /v1/message:stream timezone override untested: R2 RT-004
- Inbound `timezone` request field undocumented (DESIGN.md §5.1/§5.3, docs/protocols.md) and not namespaced/advertised in the agent card: R2 RT-007, R2 RT-008
- DESIGN.md §4.4 boot-validation list missing AGENT_SDK_TIMEZONE: R1 RT-010
- Agent(...) constructor has no inject_current_date / timezone kwargs despite AC wording "Agent/Settings": R1 RT-011

## Codify candidates (from R2)

- R2 RT-001: New fields on stable-core BaseAgentSettings must use SDK-scoped attribute names (not generic words like `timezone`), because subclasses inherit validators by field name and a clash breaks or silently rewires downstream agents.
- R2 RT-002: Any default-on code path that calls zoneinfo.ZoneInfo needs the tzdata PyPI package or a UTC fast path; system time zone data is not guaranteed in containers or on Windows.
- R2 RT-003: A test that wraps its only assertion in `if <private attr exists>` can pass without asserting anything; acceptance-criterion tests must assert unconditionally and exercise the named path (here, interrupt/resume).

## Findings

### R1 RT-003 — medium — tests/test_gh154_current_date.py
test_resumed_task_reuses_original_date (line 136) never interrupts or resumes a task. It also wraps its only assertion in `if rec is not None` behind a hasattr(_records) check, so it can pass without asserting anything. The acceptance criterion 'resumed/interrupted turns of the same task reuse the task's original date' has no real coverage.
- Fix: Drive a real interrupt: use a tool that raises input-required or an action_gate. Script the clock so a second value would fall on a different date. Resume through A2A message:send and through the AG-UI resume branch. Assert that both model calls' system prompts end with the same original date line. Remove the hasattr/if guard so the test fails loudly.

### R1 RT-004 — medium — agent_sdk/config.py
The `_valid_timezone` validator (config.py:262) runs on every Settings construction, even with the default 'UTC' and even when AGENT_SDK_INJECT_CURRENT_DATE=false. It calls ZoneInfo(), which needs a system time-zone database or the `tzdata` package, and pyproject.toml does not depend on `tzdata`. On a host without one (Windows, or distroless/minimal images), every agent will fail to boot after upgrading. The error would wrongly say AGENT_SDK_TIMEZONE is not a valid IANA name.
- Fix: Add `tzdata` to [project].dependencies, or treat 'UTC' specially (datetime.timezone.utc) in both the validator and current_date_line. Also consider skipping the zone check when inject_current_date is false.

### R1 RT-005 — medium — agent_sdk/agent/runner.py
The date line is computed in run_task_worker's prologue (runner.py:1200-1205), before the worker's try block and its terminal except-handlers. If current_date_line/ZoneInfo raises there (for example, an OSError re-reading a zone file, or a TaskStore subclass handing in a malformed date_line state), the task never reaches a terminal state, its SSE streams are never closed, and the asyncio task's exception is never retrieved. Every other worker failure path is guaranteed to end in a terminal state.
- Fix: Move the date-line computation inside the existing try so _fail() covers it, or wrap it with a fallback (e.g. on any exception use the UTC line built from datetime.timezone.utc) so it can never raise.

### R1 RT-006 — low — agent_sdk/routes/a2a.py
The `user_timezone: str | None` annotations on a2a._start_worker (a2a.py:436), ag_ui._start_worker (ag_ui.py:493) and run_task_worker (runner.py:1190) are wrong. Both routes pass the raw JSON value from metadata/forwardedProps, which can be a dict, list, int or bool. Only valid_timezone(object) stops this from being a type bug, and mypy cannot see it because .get() returns Any. The a2a.py:571 call site is also mis-indented (12 spaces).
- Fix: Type the parameter as `object`, or run valid_timezone() at the route edge so only a validated `str | None` crosses into the worker. Fix the indentation at a2a.py:571.

### R1 RT-007 — low — docs/deployment.md
The 'Current date in the system prompt (GH-154)' section (line 106) contains the GH-155 `AGENT_SDK_FINAL_SUMMARY` bullet, placed between the two GH-154 variables. An operator looking for the final-summary setting will not find it under a matching heading.
- Fix: Move the AGENT_SDK_FINAL_SUMMARY bullet into its own GH-155 subsection, e.g. next to the `AGENT_SDK_MAX_TURNS` section, and leave only the two GH-154 variables here.

### R1 RT-008 — low — agent_sdk/agent/runner.py
The new helpers were inserted between the RT-A-002 comment block and the constant it describes. The comment ('fixed, SDK-authored ... synthetic toolResult content') now sits on `_MAX_TZ_LEN = 64` (runner.py:1142-1148), and `_TASK_FAILED_TOOL_RESULT_TEXT` has lost its rationale.
- Fix: Move _MAX_TZ_LEN, _clock_now, valid_timezone and current_date_line above the RT-A-002 comment, or into their own module, so the comment sits directly above _TASK_FAILED_TOOL_RESULT_TEXT again.

### R1 RT-009 — low — agent_sdk/config.py
Zone validation is written twice. config._valid_timezone (with a function-local zoneinfo import and no length cap) and runner.valid_timezone (with the 64-character cap) catch the same exceptions separately. They can drift apart, e.g. the boot check would accept a 200-character zone name that the request path rejects.
- Fix: Put one helper in agent_sdk/common (e.g. common/timezones.py) and call it from both the settings validator and the routes/worker.

### R1 RT-010 — low — DESIGN.md
DESIGN.md §4.4's list of BaseAgentSettings boot validations (line 239) was not updated with the new rule that boot fails on an invalid AGENT_SDK_TIMEZONE. That list says it enumerates all validations, so it is now incomplete.
- Fix: Add 'AGENT_SDK_TIMEZONE must load as an IANA zone (zoneinfo)' to the §4.4 validation sentence.

### R1 RT-011 — low — agent_sdk/app.py
The acceptance criterion says 'New Agent/Settings options inject_current_date ... and timezone', but only BaseAgentSettings fields were added. The Agent(...) constructor (app.py:78-92) has no way to set them, so an agent author cannot fix a zone or turn off injection in code without a settings subclass or env vars.
- Fix: Either add `inject_current_date: bool | None` and `timezone: str | None` kwargs to Agent.__init__ that override settings (validated the same way), or get a ruling that 'Agent/Settings' meant settings only and update the todo text.

### R2 RT-001 — medium — agent_sdk/config.py
The new stable-core BaseAgentSettings field is named plain `timezone`, and its `_valid_timezone` field_validator is inherited by name. Any downstream Settings subclass that already declares its own `timezone` field takes over the SDK's date zone without warning, and its env var silently changes from AGENT_SDK_TIMEZONE to TIMEZONE. If that field is `str | None = None`, boot crashes with a raw `TypeError: expected str, bytes or os.PathLike object, not NoneType`. The validator only catches ValueError, OSError and ZoneInfoNotFoundError, so the TypeError is never turned into a clear message. Verified: `class S(BaseAgentSettings): timezone: str | None = None; S(DEV_MODE=True, ...)` raises TypeError. DESIGN.md §4.0 says BaseAgentSettings follows strict SemVer.
- Fix: Rename the field to an SDK-scoped name such as `agent_timezone` (keep alias AGENT_SDK_TIMEZONE) and `inject_current_date` likewise if desired, update app.py:827 (`app.state.timezone`), and make the validator reject non-str input with a ValueError (`if not isinstance(v, str): raise ValueError(...)`). Add a test that a subclass with its own `timezone` field still boots and does not change the SDK date zone.

### R2 RT-002 — medium — agent_sdk/config.py
The feature is on by default, and the default zone `UTC` now has to load through `zoneinfo.ZoneInfo` at boot (config.py `_valid_timezone`) and on every task (runner.py `current_date_line`). pyproject.toml does not depend on the `tzdata` package. On any host with no system time zone files (Windows dev machines, distroless or Alpine images without tzdata), the default config fails to boot. The error then wrongly tells the operator that 'UTC' is not a valid IANA name. python:3.12-slim happens to ship /usr/share/zoneinfo today (checked), so the template image works, but nothing guarantees it.
- Fix: Add `tzdata` (for example `tzdata>=2024.1`) to [project].dependencies, which is the Python docs' recommended fallback. Or map 'UTC' to `datetime.timezone.utc` without touching the time zone database. Add a test that boots with an empty `zoneinfo.TZPATH` (`zoneinfo.reset_tzpath([])`) and the default settings.

### R2 RT-003 — medium — tests/test_gh154_current_date.py
`test_resumed_task_reuses_original_date` never interrupts or resumes a task. It runs one plain A2A send and then checks `rec.date_line` only `if hasattr(app.state.task_store, "_records")`. If that private attribute is renamed, the test passes with zero assertions. The AC 'Resumed/interrupted turns of the same task reuse the task's original date' therefore has no real test. A regression that recomputes the date on resume, or across the AG-UI interrupt path, would go unnoticed.
- Fix: Rewrite the test to use a tool that raises ToolInterrupt (as other interrupt tests do). Feed a clock that crosses midnight between the first turn and the resume. Resume over A2A (message with taskId) and over AG-UI (resume entry). Assert that every FakeModelClient call's `system` ends with the original day's line. Remove the `hasattr`/`if rec is not None` guard and use the store's public `get()`.

### R2 RT-004 — medium — agent_sdk/routes/a2a.py
The A2A `message.metadata.timezone` override was added at two `_start_worker` call sites: message_send (~L571) and message_stream (~L826). Only message_send is tested (`test_a2a_user_zone_overrides` and `test_hostile_zone_never_leaks` both post to /v1/message:send). /v1/message:stream, the path the console and the acceptance suite use, has no test for the override, the fallback, or the hostile-value handling.
- Fix: Add a /v1/message:stream case to tests/test_gh154_current_date.py. Send `metadata.timezone='Asia/Tokyo'` and a hostile value with a newline and NUL byte. Assert the system prompt suffix, and assert the marker does not appear in the SSE frames, captured logs or the prompt.

### R2 RT-005 — low — agent_sdk/agent/runner.py
The date line is computed before run_task_worker's `try:` block (runner.py ~L1199-1205). If `current_date_line` raises, the asyncio task dies with an unhandled exception. That can happen if a subclass field holds a non-str zone (see R2 RT-001) or if the time zone file can no longer be loaded. No FAILED status is committed, so the task stays SUBMITTED and the AG-UI/A2A stream subscriber waits until TTL.
- Fix: Move the date computation inside the existing `try:` so the terminal handlers commit FAILED. Better still, make it never fail: wrap it in try/except and fall back to `datetime.now(timezone.utc).date()` with '(UTC)', with no logging of the raw value.

### R2 RT-006 — low — agent_sdk/agent/runner.py
The new `_MAX_TZ_LEN`, `_clock_now`, `valid_timezone` and `current_date_line` were inserted between the RT-A-002 comment block and the constant it documents (`_TASK_FAILED_TOOL_RESULT_TEXT`). That SI-2 rationale comment now sits on `_MAX_TZ_LEN`. Separately, `valid_timezone` gives different results on different platforms: on case-insensitive filesystems (macOS dev) `asia/tokyo` passes and is echoed into the prompt as typed, and AGENT_SDK_TIMEZONE=`asia/singapore` boots locally but fails boot on Linux.
- Fix: Move the GH-154 helpers above the RT-A-002 comment block so it sits directly on `_TASK_FAILED_TOOL_RESULT_TEXT` again. To fix the case issue, check names against `zoneinfo.available_timezones()` (cached once) instead of only checking that ZoneInfo loads, so validation is exact-case and the same on every platform.

### R2 RT-007 — low — docs/deployment.md
The section headed 'Current date in the system prompt (GH-154)' lists GH-155's `AGENT_SDK_FINAL_SUMMARY` between the two GH-154 variables. The final-summary setting is unrelated to the date, and operators looking for it will not find it under a date heading. The new inbound request fields (A2A `message.metadata.timezone`, AG-UI `forwardedProps.timezone`) are also missing from DESIGN.md §5.1/§5.3 and docs/protocols.md. Those docs list the other inbound keys, such as `a2uiClientCapabilities`.
- Fix: Move the AGENT_SDK_FINAL_SUMMARY bullet into its own GH-155 subsection (for example 'Final summary on capped runs'). Add one line each to DESIGN.md §5.1 and §5.3 (and docs/protocols.md) documenting the optional `timezone` request field, its IANA validation, the 64-character cap and the silent fallback.

### R2 RT-008 — low — agent_sdk/routes/a2a.py
A2A v0.3.0 defines Message.metadata keys as extension-specific identifiers. The new bare `timezone` key is not namespaced, is not tied to any declared extension, and is not advertised in the agent card (x-sdk or skills). A2A clients have no way to discover that the agent honors it. The message_send call site also uses an inconsistent 12-space continuation indent (L571-574), unlike the matching message_stream call.
- Fix: Advertise the field in the agent card's `x-sdk` block (for example `x-sdk.requestMetadata: ["timezone"]`), or accept a namespaced alias such as `agent_sdk/timezone` alongside the AC-mandated bare key. Fix the indentation so the message_send call matches message_stream.
