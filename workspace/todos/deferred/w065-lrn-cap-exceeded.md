# w065 — LRN capture cap exceeded

- Wave: w065
- Date: 2026-10-24
- MAX_LRN_PER_WAVE: 20
- Findings over cap: 4

These findings were already fixed but not codified as LRN files due to the 20-per-wave cap. Review and codify opportunistically, or fold into a future wave.

## RT-002 (high) — agent_sdk/routes/oauth.py:62 — sdkCandidate: true

- Quote: `from ..common.body import BodyTooLarge, read_capped_body`
- Description: [SDK] LRN-491 check fails. `agent_sdk/routes/oauth.py` was changed: `/oauth/register` and `_parse_form` now use `read_capped_body`. The file is not named in the CHANGELOG `[Unreleased]` section, nor in any w065 todo's Creates/Modifies. New test `tests/test_rt001_oauth_capped_body.py` is also unlisted.
- Fix: Add the oauth.py change to the GH-246 CHANGELOG bullet (`/oauth/register` and the consent form read their body through `read_capped_body`, same 400/413 replies). Name `agent_sdk/routes/oauth.py` and `tests/test_rt001_oauth_capped_body.py`. Add both paths to GH-246's Creates/Modifies in the wave file.
- Codify: A fix-round edit to an agent_sdk file outside the todo scope still needs its own CHANGELOG mention; run the LRN-491 grep after every fix round, not only after implement.

## RT-001 (high) — tests/test_gh212_id_safe_text.py:165 — sdkCandidate: true

- Quote: `for ch in "\r\x07\x1b\n\x85\x9b‮":` (control chars shown escaped)
- Description: [SDK] LRN-500 check fails: the is_id_hostile absence loop asserts U+202E is not in the rendered text, but HOSTILE_STANDALONE (line 38) and the 'b' cell never contain U+202E, so the assertion is vacuous and the GH-250 AC "U+202E added to the GH-212 hostile set" is not met; the route-level Cf drop for ids is untested (the standalone loop at line 159 also has no U+202E and checks `\n` twice).
- Fix: Put U+202E (and another bidi char such as U+2066) into HOSTILE_STANDALONE, add U+202E to the standalone loop at line 159, drop the duplicated `\n`, and confirm the test fails when drop_format_chars is removed from safe_id_text / safe_cell_text.
- Codify: An absence assertion only counts when the character is also in the hostile input; add the char to the input constant in the same edit as the assertion.

## RT-002 (high) — CHANGELOG.md:12 — sdkCandidate: true

- Quote: `### Fixed`
- Description: [SDK] LRN-501 repeats: new rejections and withheld output from GH-246 (id-less/null-id request now -32600 and the tool no longer runs; /mcp/messages now 415), GH-247 (AG-UI status approved/rejected and non-list resume now RUN_ERROR), GH-248 (role!=user now 400, malformed pageToken now 400) and GH-249 (A2UI extension removed from the card) are filed under `### Fixed`; only GH-250 is under Breaking changes.
- Fix: Move one bullet per new rejection/withheld output (GH-246 ids + 415, GH-247 status/resume shape, GH-248 role + pageToken, GH-249 card extension) under `### 🔴 Breaking changes` in [Unreleased], each with its ruling URL and a **Migration:** line; keep non-breaking parts under Fixed.
- Codify: Every change that makes a previously accepted request fail, or removes something from the card or response, goes under Breaking changes with ruling URL and Migration line, even in a planned minor bump.

## RT-003 (high) — agent_sdk/app.py:893 — sdkCandidate: true

- Quote: `# and fixed text; only the exception TYPE is logged (SI-2). Other paths`
- Description: [SDK] GH-248 item 1 AC ("logging the exception type only") is not met and the SI-2 claim is false: the handler is installed on Starlette 1.3.1 ServerErrorMiddleware, which always re-raises after responding, so uvicorn still logs "Exception in ASGI application" with full traceback and str(exc) for every /v1/* 500; no caplog test checks the log.
- Fix: Catch /v1/* exceptions in a small pure-ASGI middleware inside ServerErrorMiddleware that logs type(exc).__name__, sends the fixed -32603 JSON when the response has not started, and does not re-raise (or add a logging filter stripping exc_info/message for those records); add a caplog test asserting the hostile marker is absent from every log record; keep the 500 text/plain test for non-/v1 paths.
- Codify: A Starlette exception_handler(Exception) does not stop the exception: ServerErrorMiddleware re-raises and the server logs the full traceback, so "log type only" needs a non-re-raising catch or a log filter, pinned by a caplog test.
