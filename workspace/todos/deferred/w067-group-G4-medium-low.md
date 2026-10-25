# w067 — group G4 deferred medium/low findings

- Wave: w067
- Scope: unit:G4
- Date: 2026-10-25

Non-blocking — these did not block w067's archive. Address opportunistically or fold into a future wave.

Findings were merged across redteam rounds and de-duplicated by file + description. The source RT IDs from each round are listed.

## D-1 (medium) AG-UI path: malformed SSE frames escape as tracebacks
- File: agent_sdk/testing/chat.py:321 (`frame = json.loads(raw[5:].strip())`); agent_sdk/testing/turns.py:245 (`_agui_attempt`)
- Source: RT-002 (rounds 1, 2), RT-003 (round 3). SDK candidate.
- Problem: GH-264 item 6 was fixed only for A2A. `ChatDriver._run_agui` calls `json.loads` and `frame.get` with no guard. `_agui_attempt` catches only `HTTPStatusError` and `TransportError`. Probe: `run_turn(transport='agui')` raises JSONDecodeError on `data: {bad` and AttributeError on `data: []` / `data: [1]`. The CLI crashes instead of returning the failure record. The CHANGELOG claims malformed frames fail the attempt.
- Fix: In `_run_agui`, treat a non-JSON or non-object frame as a run error (fixed-text 'error' emit, return `(False, '')`), or catch `(ValueError, TypeError, AttributeError)` in `_agui_attempt` and set `at.reason = 'malformed-stream'` so `_restore_if_failed` rolls back the message list. Add AG-UI twins of `test_malformed_sse_frame_is_a_failed_attempt_not_a_traceback` via `run_turn` for `data: {bad` and `data: []`, asserting ok False, reason 'malformed-stream', unchanged message list.
- Codify: A malformed-input fix must cover every stream reader the helper drives (A2A and AG-UI), with one test per transport.

## D-2 (medium) A2A path: valid-JSON frames with wrong-shaped fields still escape as tracebacks
- File: agent_sdk/testing/turns.py:149 (`_text_of`: `p["text"]`), also :198, :213-215
- Source: RT-003 (rounds 1, 2), RT-002 (round 3). SDK candidate.
- Problem: GH-264 item 6 cites turns.py:147 and :180; only :180 was fixed. Probes: text part without 'text' -> KeyError; non-string text -> TypeError; `"status":"x"` -> AttributeError at :198; `"artifact":[1]` -> AttributeError at :213; `"parts":["x"]` -> AttributeError at :215.
- Fix: `_text_of` keeps only parts where `isinstance(p.get("text"), str)`. Guard status, message, artifact and each part with `isinstance(..., dict/list)`, or wrap per-frame handling in `except (KeyError, TypeError, AttributeError): at.reason = "malformed-stream"; break`. Add parametrized tests for each shape.
- Codify: "Malformed frame" includes bad field shapes inside valid JSON objects. When an issue names several line sites for one defect, every site needs a fix and a test.

## D-3 (medium) Failed card fetch is cached for the whole turn
- File: agent_sdk/testing/turns.py:141 (`except (httpx.HTTPError, ValueError) as exc:`); memo at :335
- Source: RT-004 (rounds 1, 2), RT-001 (round 3). SDK candidate.
- Problem: `_card_driver` turns any card-fetch failure (429, 5xx, transport) into `card={}`; `run_turn` caches that driver and reuses it on every retry. A2UI is silently off for the turn (no header, no `a2uiClientCapabilities`), not counted as rate-limited, never refetched. Probe: card GET 429 -> `{ok: True, contentTypes: [], attempts: 1}` with one GET. Old code refetched per attempt.
- Fix: Cache only after a successful fetch. On `HTTPStatusError`, return a failed `_Attempt` (status 429 -> classified http-429 with back-off; else reason 'card-fetch-failed'), and refetch next attempt. Test: card 429 then 200 -> two GETs, attempts == 2, A2UI header + card catalogs on final POST.
- Codify: A fetch-once cache must never store a failure; a transient capability-probe error must be retried, not pinned as "not advertised".

## D-4 (medium) New `referencing` dependency outside todo scope, not in CHANGELOG, uv.lock not updated
- File: pyproject.toml:25 (`"referencing>=0.28.4",`)
- Source: RT-005 (rounds 1, 2), RT-004 (round 3). SDK candidate.
- Problem: Added for the `referencing.exceptions.Unresolvable` import in agent_sdk/testing/mcp.py. pyproject.toml is not in any w067 Creates/Modifies list; CHANGELOG silent; uv.lock agent-sdk `requires-dist` lacks it (`uv lock --check` drift). LRN-322 / LRN-361 / LRN-413 scope drift.
- Fix: Add pyproject.toml (dependencies only) and uv.lock to the GH-264 todo scope; add CHANGELOG line "New direct dependency `referencing>=0.28.4` (already pulled in by jsonschema>=4.20)"; run `uv lock`. Or drop the direct import and catch the jsonschema-wrapped error instead.
- Codify: A new import needing a dependency declaration puts pyproject.toml, uv.lock and a CHANGELOG line into todo scope.

## D-5 (medium) C-080 registry row out of date
- File: workspace/components/README.md:73; agent_sdk/testing/chat.py:58 (`fetch_agent_card`)
- Source: RT-006 (rounds 1, 2), part of RT-006 (round 3). SDK candidate.
- Problem: New public helper `fetch_agent_card` (shared by `ChatDriver._discover_card` and `turns._card_driver`) is not in the symbol column. Row says shared by `_a2a_attempt` only, though `_agui_attempt` uses it too. Row claims catalog IDs go in through `card`, but only `extra_catalogs` feeds catalogs.
- Fix: Symbol column -> `agent_sdk/testing/chat.py (fetch_agent_card + ChatDriver._discover_card + _caps + a2ui_client_activation)`; mention turns `_card_driver`, `_a2a_attempt` and `_agui_attempt`; state catalogs come from `extra_catalogs` while `card` only pre-seeds the cache.

## D-6 (medium) Card catalog list has de-dup but no cap
- File: agent_sdk/testing/chat.py:146 (`list(dict.fromkeys([_STANDARD_CATALOG, *(extra_catalogs or [])]))`); `card_catalog_ids` at :50-55
- Source: RT-008 (round 1, low), RT-008 (round 2 duplicate not applicable), RT-005 (round 3, medium). Severity taken as medium. SDK candidate.
- Problem: GH-264 item 2 said "no de-dup or cap"; only de-dup landed. Every string from an untrusted card's `supportedCatalogIds` (any count, any length, empty strings) is copied into every A2A message metadata and AG-UI forwardedProps.
- Fix: Drop empty strings; add `_MAX_CATALOGS` (e.g. 32) and per-ID length limit (e.g. 512), standard catalog always first; log only dropped count. Test with oversized list and an over-long ID.
- Codify: A list copied from a remote document into outbound requests needs both de-dup and a count/length cap.

## D-7 (low) ChatDriver `card=` parameter undocumented and does not set catalogs
- File: agent_sdk/testing/chat.py:137 / :150 (`self._card: dict[str, Any] | None = card`)
- Source: RT-007 (rounds 1, 2), RT-006 (round 3). SDK candidate.
- Problem: `card=` only seeds the discovery cache; its `supportedCatalogIds` are not declared. `ChatDriver(client, card=c)` declares only the standard catalog (pinned by `test_chat_driver_card_parameter_skips_fetch`), unlike `turns._card_driver`. Not in class or module docstring.
- Fix: When `extra_catalogs is None` and `card` is given, default to `card_catalog_ids(card)`; or document that `card` never contributes catalogs and `extra_catalogs=card_catalog_ids(card)` must be passed.

## D-8 (low) Magic one-key dict used as memo cell
- File: agent_sdk/testing/turns.py:335 (`card_driver: dict[str, ChatDriver] = {}`)
- Source: RT-008 (round 2). SDK candidate.
- Problem: Key 'd' dict used as a mutable cell; obscures intent.
- Fix: `driver: ChatDriver | None = None` with `nonlocal driver` in `_driver()`. Combine with D-3.
