# w059 — Group G6 deferred findings (medium/low)

- Wave: w059
- Scope: unit:G6
- Date: 2026-10-22

Non-blocking — these did not block w059's archive. Address opportunistically or fold into a future wave.

## RT-007 (medium) — agent_sdk/testing/turns.py — sdkCandidate
**Finding:** AG-UI RUN_ERROR after partial text is scored as success. Line 203 sets `at.failed = bool(errors) and not at.reply`, so any streamed text before a RUN_ERROR hides the error. Verified: TEXT_MESSAGE_CONTENT 'partial' followed by RUN_ERROR 'tool crashed' gives ok=True, reply='partial', attempts=1. The run then persists messages with a truncated assistant turn.
**Fix:** Treat any RUN_ERROR as a failed attempt (reason 'run-error'), whatever text came before it. Retry only when it matches the rate-limit signal; otherwise return turn-failed. Add a test for the partial-text-then-RUN_ERROR case.

## RT-008 (medium) — agent_sdk/testing/turns.py — sdkCandidate
**Finding:** Errors that cannot succeed on retry are still retried for the full budget. classify() (lines 109-112) marks any non-429 HTTP status and any transport error as a failure, and the loop (lines 299-307) backs off on all of them. Verified: HTTP 401 is retried until the budget runs out. This goes beyond the acceptance criteria (retry only on 429, too-many-requests text, failed task, or empty reply). It wastes up to 540 s per turn on a bad key or a 404 route while holding a shared slot.
**Fix:** Return at once (no retry) for 4xx other than 408/429. Optionally retry 5xx and transport errors a bounded number of times. Add a test asserting a 401 makes one attempt and returns failureClass turn-failed with status 401.

## RT-009 (medium) — agent_sdk/testing/turns.py — sdkCandidate
**Finding:** When no slot frees up before the deadline, the turn is labelled rate-limited. Lines 283-287 set `any_rate_limited = True` on 'slot-wait-exceeded', so the helper's own queueing delay is reported as server throttling. The pipeline in acceptance-api.js (~234) still starts every scenario at once. The todo named the pipeline (~295-322) for change but it was not touched, so 60+ callers compete for 3 slots and long waits are the expected case. Because of RT-001, these untested turns can then count as passes.
**Fix:** Give slot timeouts a distinct failureClass, for example 'harness-throttled', that blocks the pass gate. Also cap pipeline concurrency in acceptance-api.js (for example a semaphore of ceil(slots × 2)) so callers do not pile up behind the file locks.

## RT-010 (medium) — agent_sdk/testing/turns.py — sdkCandidate
**Finding:** State files default to tempfile.gettempdir() (line 254). On macOS that is $TMPDIR (/var/folders/.../T), not /tmp; verified on this machine. Yet acceptance-api.js:141 and :173 tell agents to clean up /tmp/acc-<runKey>-*, and SKILL.md:319 says the files are written to /tmp. Cleanup silently misses, and conversation transcripts (user queries and replies in acc-*-agui-msgs.json) pile up. On Linux they are written with default 0644 permissions in shared /tmp.
**Fix:** Have acceptance-api.js pass an explicit --state-dir (a per-run directory) and --lock-dir. Or add a `--cleanup` mode to the helper that removes its own files. Write state files with 0600 permissions. Update SKILL.md to name the real location.

## RT-011 (medium) — template/pyproject.toml — sdkCandidate
**Finding:** The 'pin resolves to >=0.18.0' requirement is only a comment (line 9). /new-agent and /setup fill {{SDK_SHA}} from HEAD or `--sdk-ref` with no version check. Any agent pinned below 0.18.0 that gets this acceptance-api.js will fail at `python -m agent_sdk.testing.turns` with ModuleNotFoundError. No JSON is printed and the turn is scored 1 as 'no reply'. Nothing in the acceptance SKILL checks for the module up front.
**Fix:** Add a Phase 0 check to the acceptance SKILL (all three copies): `.venv/bin/python3 -c 'import agent_sdk.testing.turns'`. If it fails, abort with 'agent-sdk >=0.18.0 required'. Optionally add a version check to new-agent/setup when --sdk-ref is given.

## RT-012 (medium) — tests/test_gh210_testing_turns.py — sdkCandidate
**Finding:** Every run_turn test injects `client=`, so the real path is never exercised: reading the key file and building the Authorization header (turns.py:259-264). The SI-6 regression only inspects the function signature and greps the source. Several tests (lines ~65-115 and 146-165) also omit lock_dir, so they use the machine-wide default <tmp>/acc-slots, the same one live acceptance runs use. With _sleep patched to a no-op, SlotLimiter.acquire would busy-spin for up to 540 s whenever a live run holds the 3 slots.
**Fix:** Pass lock_dir=tmp_path/'locks' in every test. Add a test that leaves out `client` and routes through respx (a permitted test double): assert the outbound Authorization header equals the key-file contents, and that the key never appears in stdout from main().

## RT-013 (medium) — harness/skills/acceptance/SKILL.md — sdkCandidate
**Finding:** The fix offered for rate-limited runs cannot be acted on. SKILL.md:488 and acceptance-api.js:189 say to re-run 'with fewer slots (--slots 1)', but acceptance-api.js has no slots argument and never passes --slots to the helper (lines 114-115 and 154-155). Users have no way to change the limit, so the acceptance criterion's 'configurable' only holds at the Python level.
**Fix:** Add an `args.slots` option to acceptance-api.js, pass it as `--slots N` in both helper commands, and document `/acceptance --slots N` in the SKILL (all three copies).

## RT-014 (low) — agent_sdk/testing/turns.py — sdkCandidate
**Finding:** Some errors are not caught: a malformed SSE data line (`json.loads` at line 148), an unexpected ChatDriver exception, or a PermissionError on a lock file owned by another user (line 75). Any of these crashes run_turn, so the CLI prints a traceback instead of the one-JSON-line contract, and the agent scores the turn 1.
**Fix:** In main(), catch Exception and print {ok:false, failureClass:'turn-failed', reason:<fixed text>}, with no exception text, to keep SI-2. Inside attempts, treat a JSON decode failure as reason 'bad-frame'.

## RT-015 (low) — tests/test_gh210_testing_turns.py — sdkCandidate
**Finding:** Dead expression at line 236: `content=BODY.encode() if False else _a2a_ok()`. The first branch never runs, so this test never sends the BODY marker on the success path. The paths in the shell command in acceptance-api.js:115 and :155 (--base-url, --key-file) are also unquoted, so a key-file path with spaces breaks the command.
**Fix:** Replace the line with `content=_a2a_ok()` (or add a real BODY-carrying failure case). Single-quote the --base-url and --key-file values in the prompt command.
