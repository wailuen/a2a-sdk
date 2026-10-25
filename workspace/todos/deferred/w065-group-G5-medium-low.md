# w065 — group G5 deferred medium/low findings

- Wave: w065
- Scope: unit:G5
- Date: 2026-10-24

Non-blocking — these did not block w065's archive. Address opportunistically or fold into a future wave.

## RT-001 (medium) — agent_sdk/app.py:893 — sdkCandidate: true

Quote: `# and fixed text; only the exception TYPE is logged (SI-2). Other paths`

The comment and the GH-248 item 1 AC ('logging the exception type only') are not true end to end. Starlette 0.52's ServerErrorMiddleware runs this handler and then always re-raises the exception. Uvicorn then logs 'Exception in ASGI application' with the full traceback, including str(exc). Any user payload or upstream value carried in the exception message still reaches the server log (SI-2 exposure).

Fix: Either (a) catch the exception for /v1/* in a small pure-ASGI middleware mounted inside ServerErrorMiddleware: log type(exc).__name__, send the fixed -32603 JSON if the response has not started, and do not re-raise. Or (b) keep this handler, correct the comment, and add a logging filter on the 'uvicorn.error' logger (agent_sdk/observability/logging.py) that drops exc_info/message for 'Exception in ASGI application' records whose scope path starts with /v1/. Add a caplog test asserting MARKER is absent from every record.

Codify: A Starlette exception_handler(Exception) does not stop the exception: ServerErrorMiddleware re-raises after responding, so the server still logs the full traceback. 'Log type only' needs a non-re-raising catch or a log filter.

## RT-002 (medium) — agent_sdk/routes/a2a.py:1064 — sdkCandidate: true

Quote: `if pageToken and not _TASK_ID_SHAPE.fullmatch(pageToken):`

The route now refuses any pageToken that is not 32 lowercase hex characters. The public TaskStore.list_tasks_for_identity contract (agent_sdk/tasks/store.py:487-489, C-005) still promises an 'opaque nextPageToken', and Agent(task_store=...) is a public override. A custom store minting a different cursor gets every page-2 request rejected with 400 -32602. CHANGELOG.md has no compatibility note.

Fix: Apply the shape check only when the store's list method is the built-in one (`type(store).list_tasks_for_identity is InMemoryTaskStore.list_tasks_for_identity`) and pass the token through otherwise. Or, if intended, record it in CHANGELOG (Compatibility/Changed) and DESIGN.md §5.2. Add a test with a TaskStore subclass minting non-hex tokens.

Codify: A route-level shape check on a token that a pluggable store mints must match the store's documented contract, or it silently breaks every third-party store.

## RT-003 (low) — docs/protocols.md:68 — sdkCandidate: true

Quote: `` `POST /v1/tasks/{id}:subscribe` and AG-UI's `POST /ag-ui/run` each hold an ``

Item 8 added GET /v1/tasks/{id}:subscribe under the same admission cap, but stream-admission text still lists only POST. Same stale wording in docs/protocols.md:68, DESIGN.md:269, DESIGN.md:378 (§5.5), DESIGN.md:444 (rate-limiting layer 3), and the agent_sdk/common/admission.py:6 docstring.

Fix: Change each reference to 'POST or GET /v1/tasks/{id}:subscribe' (DESIGN.md edits were outside this todo's scope; route through a follow-up item or ruling).

## RT-004 (low) — tests/test_gh248_a2a_route.py:122 — sdkCandidate: true

Quote: `async def test_stream_first_snapshot_honours_history_length_zero(client, fake_model) -> None:`

Test gaps: (1) message:stream resume branch (a2a.py:1011, history_length) untested with historyLength=0. (2) No test that a non-/v1 500 still returns text/plain (MCP/AG-UI unchanged). (3) test_subscribe_get_shares_admission_cap (line 226) uses GET for both streams, so it does not prove GET and POST share one budget, and relies on a fixed asyncio.sleep(0.3) (line 235).

Fix: Add a resume test with configuration.historyLength=0 asserting the first frame has no history. Add a test making a non-/v1 route raise and asserting 500 text/plain. Hold the slot with POST :subscribe and assert GET :subscribe gets 429. Replace the sleep with polling _a2a_streams until the first stream is admitted.

## RT-005 (low) — agent_sdk/routes/a2a.py:170 — sdkCandidate: true

Quote: `_MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MB — consistent with AG-UI cap`

_mode_accepted was inserted mid constant block; _MAX_BODY_BYTES follows its `return` with no blank lines (PEP 8 E305), reading as part of the function body.

Fix: Move _mode_accepted below the constant block (after the RT-002 comment and constants), with two blank lines before and after.

---
Filed 2026-10-25 by /sdk-autoloop cycle 1: verified still-present mediums (and lows sharing a fix) are in #251–#260. Other lows stay here, unfiled.
