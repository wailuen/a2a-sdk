# w063 — GitHub issues 233, 234

Sourced from open issues on wailuen/a2a-sdk after the v0.20.0 release (w062). GH-186 is deferred by ruling. GH-224 is design-only. GH-232 was closed as already fixed by GH-212.
Groups G1 and G2 are independent and run in parallel.
Target: 0.20.1 — bug fixes only, no public API change.

Do NOT edit `template/` except the peer copy named in GH-233 (LRN-085/LRN-071: it lands via commit+push to wailuen/a2a-agent-template inside this wave; the commit stages only that path). Each item adds its own entry to `CHANGELOG.md` `[Unreleased]` with in-place Edit, never a whole-file rewrite.

CHANGELOG rule (both GH-233 and GH-234; G1 and G2 run in parallel): `CHANGELOG.md` has no `[Unreleased]` section today (top section is `## [0.20.0] — 2026-10-24`, tagged; LRN-145: never write into it). Each todo, in one in-place Edit made right before it finishes, re-reads `CHANGELOG.md` and inserts-if-absent this exact block directly above the `## [0.20.0] — 2026-10-24` line:

```
## [Unreleased]

### Fixed
```

If the heading already exists (the other todo added it), it does not add a second one; it appends its single bullet as the last line under that existing `### Fixed`. After both todos land, `grep -c '^## \[Unreleased\]' CHANGELOG.md` is 1, the lines between `## [Unreleased]` and `## [0.20.0]` hold exactly one `### Fixed` heading with both bullets, and the `## [0.20.0]` section is byte-identical to `git show HEAD:CHANGELOG.md`.

---

## G1 — harness workflow scripts

- [ ] `GH-233` acceptance-api.js does not parse (unescaped apostrophe in GH-210 rule text) ‖ group:G1
  - Creates: (modifies `harness/workflows/acceptance-api.js`, `template/.claude/workflows/acceptance-api.js`, `CHANGELOG.md`; new `tests/test_gh233_workflow_scripts_parse.py`)
  - Reads: `harness/workflows/wave-cycle.js`, `.claude/workflows/sdk-wave.js`, `tests/test_gh131_acceptance_api_args_normalization.py`
  - Severity: high
  - Root cause: line ~203 of `harness/workflows/acceptance-api.js` (and the template copy) has `transport's` inside a single-quoted JS string, so the string ends early and the Workflow runtime cannot load the script; `/acceptance` stops before any scenario.
  - AC: Reword the rule text to "set the minScore of that transport to 1 ..." in both copies; the two copies stay byte-identical for that line.
  - AC: New test wraps every `*.js` under `harness/workflows/`, `.claude/workflows/` and `template/.claude/workflows/` exactly like the issue (strip leading `export `, wrap in `(async()=>{ ... })`) and runs `node --check`; it fails on a syntax error and skips only when `node` is not on PATH. The template paths are skipped when `template/` is absent.
  - AC: The test fails on the pre-fix file (prove it by running it before the edit).
  - AC: Template copy committed and pushed to wailuen/a2a-agent-template main, staging only `.claude/workflows/acceptance-api.js`.
  - AC: `CHANGELOG.md` entry follows the wave-header CHANGELOG rule: insert-if-absent `## [Unreleased]` + `### Fixed` above `## [0.20.0] — 2026-10-24`, then one GH-233 bullet under that `### Fixed`; nothing is written inside the 0.20.0 section; exactly one `## [Unreleased]` heading exists afterwards.
  - GH: https://github.com/wailuen/a2a-sdk/issues/233

## G2 — AG-UI test client (`agent_sdk/testing/chat.py`, console)

- [ ] `GH-234` testing/chat.py AG-UI path: credentials not sent, unterminated stream counted as success ‖ group:G2
  - Creates: (modifies `agent_sdk/testing/chat.py`, `agent_sdk/console/static/chat.js`, `agent_sdk/console/static/a2ui.js`, `CHANGELOG.md`; new `tests/test_gh234_agui_chat_driver.py`)
  - Reads: `agent_sdk/routes/ag_ui.py`, `agent_sdk/testing/turns.py` (C-055 `_agui_attempt`, `run_turn` — the real consumer; not modified), `tests/test_chat_driver.py`, `tests/test_card_console.py`, `tests/test_gh210_testing_turns.py` (MockTransport + `run_turn` test pattern)
  - Severity: medium
  - Root cause: `_run_agui` posts `/ag-ui/run` with no merged headers, treats a stream without a terminal event as success, joins separate messages with "", and keeps reading after RUN_ERROR. The console keeps every painted surface forever now that no `deleteSurface` arrives (GH-214), and drops a pending interrupt when the resume POST fails.
  - AC: `_run_agui` sends `headers=self._merged_headers({"Accept": "text/event-stream"})`, so `credentials=` reaches AG-UI as `X-Agent-Credentials` exactly as on A2A. Test with a recording transport.
  - AC: A stream that ends with neither RUN_FINISHED nor RUN_ERROR fires the `error` callback with fixed text `stream closed without a terminal event`. Test.
  - AC: `_run_agui` returns `""` whenever the stream did not end with RUN_FINISHED (no terminal event, or RUN_ERROR seen); partial text is still delivered through the `text` emit but is never returned. So neither `agui_turn` nor `agui_resume` appends a partial reply to `messages` (both keep their `if reply:` guard). Tests: one for `agui_turn`, one for `agui_resume`, each asserting `messages` gains no `{role: assistant}` entry on an unterminated stream and on a RUN_ERROR stream.
  - AC: End-to-end through the consumer: `agent_sdk.testing.turns.run_turn(transport="agui", ...)` against an `httpx.MockTransport` that streams TEXT_MESSAGE_CONTENT and then closes with no terminal event reports the turn as failed (`_agui_attempt` sets `failed` via its existing `bool(errors) and not at.reply`; `turns.py` itself is unchanged). Same for a stream with partial text then RUN_ERROR. A normal RUN_FINISHED stream still passes. Failing tests written RED before the `chat.py` change, GREEN after. Follow the `tests/test_gh210_testing_turns.py` pattern.
  - AC: Frames after RUN_ERROR are ignored (loop breaks). Test with a late TEXT_MESSAGE_CONTENT after RUN_ERROR.
  - AC: Text from different `messageId`s is joined with "\n" in arrival order; deltas of one message are still concatenated. `TEXT_MESSAGE_CHUNK` is handled like START+CONTENT for its `messageId` (chat.py and chat.js). Tests for chat.py.
  - AC: `a2ui.js` exports `resetSurfaces()` that clears the `surfaces` Map, and `chat.js` calls it from "Reset session". After painting, a surface entry keeps only what a later `updateComponents`/`updateDataModel` for the same surface needs; no cap that changes what the page shows.
  - AC: `chat.js` restores `pendingInterrupt` when the resume POST fails, so the user can retry.
  - AC: No change to the server routes or the wire.
  - AC: `CHANGELOG.md` entry follows the wave-header CHANGELOG rule: insert-if-absent `## [Unreleased]` + `### Fixed` above `## [0.20.0] — 2026-10-24`, then one GH-234 bullet under that `### Fixed`; nothing is written inside the 0.20.0 section; exactly one `## [Unreleased]` heading exists afterwards.
  - GH: https://github.com/wailuen/a2a-sdk/issues/234
  - SI: SI-2  # caller credentials (the dict sent as X-Agent-Credentials) go on the AG-UI request for the first time, and a new error message is added; SI-5 untouched (no route or auth change)
  - AC (SI-2): Credential values never appear in any `error` emit, any `text` emit, exception text, or console trace. Regression test: the recording-transport test passes `credentials={"k": "<sentinel secret>"}`, asserts the sentinel reaches the request only inside the `X-Agent-Credentials` header, and asserts the sentinel is absent from every recorded `error`/`text` emit and from `str()`/`repr()` of any raised exception, for a RUN_FINISHED stream, an unterminated stream, a RUN_ERROR stream and an HTTP error status.
  - AC (SI-2): The new terminal-event error uses only the fixed text `stream closed without a terminal event`, with no interpolated values (no headers, body, thread id or frame content). Test asserts exact string equality.

---

Archived by hand 2026-10-24. The archive gate failed on one test (LRN-491 Check clause named a bare `a2ui.js`); fixed. Phase mediums RT-001..RT-003 (chunk messageId inheritance in chat.py and chat.js; console folds chunk-only text only after RUN_FINISHED) and RT-006 (docstrings) fixed by hand. Template copy pushed by the wave (template main 62fa197). Remaining lows in `deferred/w063-*-medium-low.md`.
