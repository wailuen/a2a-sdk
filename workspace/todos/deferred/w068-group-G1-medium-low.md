# w068 — G1 deferred medium/low findings

- Wave: w068
- Scope: unit:G1
- Date: 2026-10-25

Non-blocking — these did not block w068's archive. Address opportunistically or fold into a future wave.

Findings come from several redteam rounds. IDs repeat across rounds, so each entry is tagged with its round batch (a = first batch, b = second batch). Entries were deduped by file + description. Some overlap in substance: a-RT-005 / b-RT-001 (card driver cached after a failed fetch), a-RT-007 / b-RT-003 (docs/testing.md stale), a-RT-006 / b-RT-010 (missing guard tests), and a-RT-008 / b-RT-009 (malformed-stream string match). Fix each pair once.

## Medium

### a-RT-005 — agent_sdk/testing/turns.py:146
- Quote: `except (httpx.HTTPError, ValueError) as exc:`
- Issue: Ruling item 3 says the card driver is cached only after a successful fetch. A card-fetch TransportError, a non-429/5xx status error, or a non-JSON body becomes card={}, and run_turn caches that driver for every retry. A2UI never turns on after a transient first failure. The C-055 and C-080 rows overstate the code.
- Fix: Let TransportError propagate from _card_driver like 429/5xx; catch it in run_turn._run_attempt and _a2a_attempt/_agui_attempt and return reason 'transport-error' with nothing cached. Or return (driver, ok) and cache only when ok. Test: ConnectError on card GET at attempt 1, good A2UI card at attempt 2, assert real catalogs sent.
- Codify: 'Cache only on success' must cover every failure class, transport errors included.

### b-RT-001 — agent_sdk/testing/turns.py:146
- Quote: `except (httpx.HTTPError, ValueError) as exc:`
- Issue: Transport error, non-JSON card body, or non-429 4xx card fetch becomes card={} and is cached for the whole turn. Probe: card GET raises ConnectError on attempt 1, POST returns 503, attempt 2 never refetches; both POSTs lack X-A2A-Extensions though the card advertises A2UI. C-055, C-080 and the CHANGELOG claim otherwise.
- Fix: _card_driver returns a flag or None on any failed fetch. In _run_attempt set card_driver only when fetch_agent_card returned a dict. For a non-retryable failure use an uncached ChatDriver(card={}) for this attempt only. Test: ConnectError on first card GET, success on second, assert second POST carries the A2UI header and real catalogs.
- Codify: A success-only memo is written only on the success branch; a fallback built in an except branch never reaches the memo.

### a-RT-006 — agent_sdk/testing/chat.py:388
- Quote: `if not isinstance(delta, str):`
- Issue: New guard branches with no test that fails when removed (LRN-544, LRN-550, LRN-560): AG-UI non-string delta (chat.py:388-391, claimed in CHANGELOG); A2A artifact-update guards (non-object artifact, non-list parts, non-object part metadata, turns.py:247-254); message-kind non-list parts (turns.py:243); RUN_FINISHED with non-object outcome (chat.py:410-412).
- Fix: Parametrized cases. tests/test_gh234_agui_chat_driver.py: TEXT_MESSAGE_CONTENT with delta {x: MARKER} and delta 5; RUN_FINISHED with outcome 'x'. tests/test_gh237_testing_clients.py (_bad_a2a_bodies): artifact-update with artifact 'x', parts {}, part metadata 'x'; message event with parts 'x'. Each asserts reason 'malformed-stream' and marker absence.
- Codify: Every guard branch named in a CHANGELOG line needs its own test that fails when the guard is deleted.

### a-RT-007 — docs/testing.md:95
- Quote: "`turns` fetches the card once, inside the same slot wait and time budget as the turn, ..."
- Issue: Documented behaviour changed but the doc was not updated. Card is refetched after a 429/5xx; supportedCatalogIds is filtered (non-empty, <=512 chars, <=32, standard first); bad frame yields 'malformed-stream'.
- Fix: Rewrite the sentence to cover all three. Add docs/testing.md to the GH-268 CHANGELOG file list.

### b-RT-002 — agent_sdk/testing/turns.py:256
- Quote: `dtype = _obj(art.get("metadata")).get("data_type") or art.get("name")`
- Issue: Non-string artifact name, metadata.data_type or part metadata.mimeType is appended to at.content_types as-is. Probe: name={"k":1} gives reason='' and content_types=[{'k': 1}]. Breaks the malformed-stream ruling and the list[str] contract.
- Fix: Route dtype, meta.get('data_type') and meta.get('mimeType') through _str_of (or raise _MalformedStream when not None and not str). Add non-string-name and non-list-parts shapes to _bad_a2a_bodies().
- Codify: Every frame field that reaches a returned result passes the same type guard as control-flow fields.

### b-RT-003 — docs/testing.md:95
- Quote: same as a-RT-007.
- Issue: Doc still says turns 'fetches the card once'; missing catalog bounds and the 'malformed-stream' reason. The todo made this doc a conditional deliverable, and the condition was met.
- Fix: Card fetched once per successful fetch; 429/5xx fetch fails the attempt (http-429 / http-error) and is retried. State supportedCatalogIds bounds. List 'malformed-stream' among run_turn failure reasons. Add docs/testing.md to the GH-268 CHANGELOG bullet.
- Codify: When a doc is conditional on a behaviour change, the redteam diffs the doc's claims against the new code.

### b-RT-004 — agent_sdk/testing/chat.py:356
- Quote: `self._fire(emit, "tool_args", args)`
- Issue: TOOL_CALL_ARGS fires whatever json.loads returns (int, list, str) though the contract is tool_args(args: dict). A fragment '12' parses to int; the test-chat CLI calls args.items() (agent_sdk/__main__.py) and raises AttributeError. _fire sits inside `except (ValueError, TypeError): pass`, so a TypeError from the caller's callback is swallowed.
- Fix: Parse outside the try; skip on ValueError/TypeError; fire only when isinstance(args, dict); call _fire outside the except. Test deltas '12' and '[1]': no tool_args emit, no exception.
- Codify: An emit bus enforces its documented payload type and never wraps the user callback in a broad except.

### b-RT-005 — agent_sdk/testing/chat.py:529
- Quote: `st = task["status"]["state"]`
- Issue: Ruling says no raw exception escapes run_turns/ChatDriver, but a2a_turn and resume index server JSON unguarded (result.get('kind') on a non-object, task['id'], task['status']['state']). Bad shape gives raw AttributeError/KeyError/TypeError; the CLI shows a traceback.
- Fix: Guard result and polled task with isinstance(..., dict); read status/state via a helper. On bad shape fire the MALFORMED_STREAM_TEXT error emit and raise A2AError(None, MALFORMED_STREAM_TEXT). Tests: list response; task with no status.
- Codify: A 'no raw exception escapes X' ruling covers every public method of X.

### b-RT-006 — agent_sdk/testing/turns.py:201
- Quote: `return _card_failed(at, exc)`
- Issue: The Reuses: C-055 note forbids a new per-attempt try/except, but three copies of try/except HTTPStatusError wrap _card_driver (_a2a_attempt, _agui_attempt, run_turn._run_attempt). The inner two only run for direct callers with no driver; logic is duplicated and can drift.
- Fix: Put the card fetch and failure-to-_Attempt mapping in the run_turn attempt guard only; _a2a_attempt/_agui_attempt require a driver or share one helper. Remove the duplicates.
- Codify: A Reuses note forbidding a new per-call guard is a design constraint; duplicated guards fail Dimension 8 even when tests pass.

### b-RT-007 — workspace/learning/LRN-509-testing-client-real-app.md:17
- Quote: Check clause allowlist ending "... `test_card_429_then_success_gets_the_real_card`, `test_card_429_failure_reports_http_429` and `test_card_retry_builds_no_new_client`."
- Issue: The Check clause allowlist was widened for the three new GH-268 MockTransport tests, but the LRN file is not in G1's Creates/Modifies. The group relaxed the guard on its own tests out of scope. The edit also drops the ', ' separator before test_mcp_client_rejects_unsupported_negotiated_version.
- Fix: Revert and widen via codify (or a todo listing the LRN) with a recorded reason; otherwise add the LRN to G1's Modifies list and fix the separator.
- Codify: A wave group must not edit the LRN Check clause that polices its own tests unless the todo lists that file.

## Low

### a-RT-008 — agent_sdk/testing/turns.py:302
- Quote: `if MALFORMED_STREAM_TEXT in errors:`
- Issue: Malformed-stream is detected by matching error text. A server RUN_ERROR with message exactly 'malformed stream frame' is mislabelled, skipping the rate-limit check and task-failed. Public MALFORMED_STREAM_TEXT (chat.py:34) becomes a cross-module signal with no CHANGELOG Added bullet.
- Fix: ChatDriver._run_agui records the cause on a flag (private attribute or distinct 'malformed' emit key); _agui_attempt reads it. Rename to _MALFORMED_STREAM_TEXT or list under Added.

### b-RT-008 — agent_sdk/testing/chat.py:160
- Quote: `"catalogs": list(dict.fromkeys([_STANDARD_CATALOG, *(extra_catalogs or [])])),`
- Issue: card_catalog_ids caps at 32, but ChatDriver prepends the standard catalog, so the sent catalogs list can have 33 entries.
- Fix: Apply the 32 cap after the merge (in __init__), or reserve slot 0 for the standard catalog in card_catalog_ids. Assert on the sent caps length.

### b-RT-009 — agent_sdk/testing/turns.py:310
- Quote: `if MALFORMED_STREAM_TEXT in errors:`
- Issue: Same string-compare problem as a-RT-008. Also _a2a_attempt uses two mechanisms for one outcome: set reason + break for bad JSON / non-object frame, raise _MalformedStream for field shapes. MALFORMED_STREAM_TEXT is a new unprefixed public name with no Added bullet (LRN-559).
- Fix: Distinct channel (dedicated 'malformed' emit key or ChatDriver attribute). In _a2a_attempt raise _MalformedStream for JSON/non-object cases too. Make the constant private or add an Added bullet.

### b-RT-010 — tests/test_gh234_agui_chat_driver.py:784
- Quote: `def _bad_shape_frames():`
- Issue: Guards with no failing-when-removed test (LRN-544/560): AG-UI non-string TEXT_MESSAGE_CONTENT delta (claimed in CHANGELOG); non-string AGENT_ARTIFACT dataType or toolName; A2A artifact-update non-object artifact and non-list parts; card-429 retry on AG-UI (only A2A tested).
- Fix: Add {type: TEXT_MESSAGE_CONTENT, delta: 5} then RUN_FINISHED, and AGENT_ARTIFACT with value {dataType: 1}, to _bad_shape_frames. Add artifact-update shapes to _bad_a2a_bodies. Add an AG-UI run_turn variant of test_card_429_then_success_gets_the_real_card asserting forwardedProps catalogs.

### b-RT-011 — agent_sdk/testing/chat.py:426
- Quote: `if not isinstance(outcome, dict):`
- Issue: RUN_FINISHED with a non-object outcome (string, list) is treated as success, while non-list interrupts is malformed-stream. Inconsistent with the ruling.
- Fix: Present-but-non-object outcome is malformed (finished=False, errored=True, fixed error emit, break). Keep None meaning success.

### b-RT-012 — tests/test_gh237_testing_clients.py:1176
- Quote: `# MockTransport: build_app cannot serve a 429 agent card then a good one.`
- Issue: test_card_retry_builds_no_new_client serves a 503, not a 429; the comment was copy-pasted from the line-1127 test, so the LRN-509 justification is inaccurate.
- Fix: Change to `# MockTransport: build_app cannot serve a 503 agent card then a good one.`

All findings above are sdkCandidate: true.
