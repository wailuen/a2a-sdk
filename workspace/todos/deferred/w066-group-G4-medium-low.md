# w066 — unit:G4 — deferred medium/low findings

- Wave: w066
- Scope: unit:G4
- Date: 2026-10-25

Non-blocking — these did not block w066's archive. Address opportunistically or fold into a future wave.

Findings are deduped by file + description across all redteam rounds. Round-local IDs are listed per item.

## Medium

### D1. Message-kind stream leaves stale task/state files — `agent_sdk/testing/turns.py:195`, `:366` (rounds: RT-003, RT-004) [sdkCandidate]
- Quote: `elif kind == "message":` / `if last.ids.get(k):`
- Problem: the message branch ends with state `""`. run_turn writes only truthy ids, so the old state file (e.g. `input-required`) and task file (e.g. `t1`) stay on disk. The next turn sends a stale taskId to a finished task. GH-256 item 3 is half done.
- Fix: on a Message end, write an explicit terminal marker (`""` or `completed`) and clear/overwrite the task file; or have run_turn write/unlink every state file after a successful attempt. Test: input-required turn → message-reply turn → third turn carries no taskId.
- Codify: a stream path that ends a turn without a task state must still overwrite the persisted task and state files, or the next turn resumes a dead task.

### D2. `_card_driver` decides catalogs from one probe; failed first fetch drops domain catalogs — `agent_sdk/testing/turns.py:139`, `:141`; `agent_sdk/testing/chat.py:136` (rounds: RT-001, RT-005 x2, RT-008, RT-004) [sdkCandidate]
- Quote: `if not await probe._a2ui_advertised():` / `driver = ChatDriver(client, extra_catalogs=card_catalog_ids(probe._card))` / `"catalogs": [_STANDARD_CATALOG] + list(extra_catalogs or []),`
- Problems:
  - If the first card GET fails (503 at boot, 429 from unauth limiter), the probe is returned with standard-only catalogs; a later `a2ui_client_activation()` refetch succeeds and turns A2UI on without the card's domain catalogs. Reproduced: GET 503 then 200 with `['urn:dom:v1']` → posted catalogs `['urn:a2ui-profile:standard:v1']`.
  - turns.py reaches into ChatDriver private state (`_a2ui_advertised`, `_card`, `driver._card = ...`).
  - Standard catalog ID appears twice (card list already includes it); card list has no size cap.
  - `meta` reused at line 205 for part metadata after holding A2UI message metadata at line 164.
- Fix: move into ChatDriver (C-080): `a2ui_client_activation()` merges `card_catalog_ids(card)` into `_caps` from the same fetch it just checked (or a public `from_card` / `with_card_catalogs` method). De-dup with `list(dict.fromkeys(...))`, cap extra IDs (e.g. 32). Drop the probe/rebuild and private access in turns.py. Rename part-level var to `pmeta`. Test: first card GET fails, later succeeds, domain catalog still declared.
- Codify: when a client decides an option from a fetched document, use the same fetch result for every value that depends on it.

### D3. Card fetch runs outside slot limiter and time budget — `agent_sdk/testing/turns.py:317` (rounds: RT-008, RT-005) [sdkCandidate]
- Quote: `a2a_driver = await _card_driver(client) if transport == "a2a" else None`
- Problem: the GET is not counted against the cross-process slot cap and is not under `asyncio.wait_for(..., deadline - _now())`. httpx timeouts are per read, so a slow card endpoint can run up to the client timeout (up to 300s). Before this change it ran inside `_a2a_attempt`.
- Fix: build the driver lazily inside the first slot-held, `wait_for`-bounded attempt and cache it in a local holder reused on retries; or wrap in `asyncio.wait_for(deadline - _now())`.

### D4. AG-UI acceptance path declares only the standard catalog — `agent_sdk/testing/turns.py:227` (round: RT-004) [sdkCandidate]
- Quote: `at.reply = await ChatDriver(client).agui_turn(`
- Problem: `_agui_attempt` builds `ChatDriver(client)` with no extra_catalogs, so domain-catalog components are filtered by `A2uiCapabilities.allows` on every AG-UI turn. docs/testing.md:95 and C-080 say this applies to all of turns.
- Fix: build the card-aware driver once in run_turn for both transports and pass it to `_agui_attempt`. Add a build_app() ASGI test asserting `forwardedProps.a2uiClientCapabilities.catalogs` has a domain catalog ID. Or scope docs/C-080 to A2A only.

### D5. build_app() catalog test proves nothing; fake clients used where build_app works — `tests/test_gh237_testing_clients.py:605` (also :596, :693, :745) (round: RT-002) [sdkCandidate]
- Quote: `for cid in card_catalog_ids(card):`
- Problem: the test builds `ChatDriver(client)` itself, skipping `_card_driver`; the app emits only the Standard catalog, which ChatDriver always includes. AC item 2 and header gating are tested only via MockTransport fakes, against LRN-496.
- Fix: build_app() test with a domain ContentModel having its own catalog_id; call `_a2a_attempt(client, q, {})` with no driver; assert the domain ID is in posted `a2uiClientCapabilities.catalogs`. Move header-gating test onto `_fake_tools_app` / `_a2ui_app` over ASGI. Keep MockTransport only for non-object card, fetch failure, message-kind stream.
- Codify: a test of "client forwards card value X" must use an app whose X differs from the client's default, through the code path under test.

### D6. McpClient accepts a missing protocolVersion — `agent_sdk/testing/mcp.py:120-121` (rounds: RT-009, RT-002) [sdkCandidate]
- Quote: `if negotiated is None:` / `negotiated = PROTOCOL_VERSION`
- Problem: MCP 2025-06-18 InitializeResult requires `protocolVersion`; the client silently falls back to its own. Contradicts the CHANGELOG "stricter" framing. Fallback path is untested.
- Fix: treat missing or non-string as `McpError("mcp negotiated protocol version is not supported")`. MockTransport tests for missing key and non-string value. Update CHANGELOG GH-256 entry.
- Codify: a conformance test client must reject a missing required response field, not fill it in with its own default.

## Low

### D7. Catch-all `except Exception` mislabelled as unresolvable $ref — `agent_sdk/testing/mcp.py:244` (rounds: RT-004, RT-003 x2, RT-006) [sdkCandidate]
- Quote: `except Exception:`
- Problem: TypeError, RecursionError, format-checker bugs are all reported as "outputSchema has an unresolvable $ref".
- Fix: catch `referencing.exceptions.Unresolvable` (jsonschema 4.26 raises `_WrappedReferencingError`, a subclass); per LRN-504 add `referencing` to `[project].dependencies`, or use `jsonschema.exceptions.RefResolutionError` via `getattr`. Other exceptions propagate, or map to a separate fixed text such as "outputSchema could not be checked".

### D8. `a2a_turn` crashes on a non-object card — `agent_sdk/testing/chat.py:426` (rounds: RT-007, RT-006) [sdkCandidate]
- Quote: `transport = card.get("preferredTransport", "JSONRPC")`
- Problem: list/string card raises AttributeError instead of the documented ValueError. `self._card` typed `dict | None` but may hold list/str, so mypy misses it.
- Fix: in `_discover_card`, raise `ValueError("agent card is not a JSON object")` and do not cache when `r.json()` is not a dict. Parametrised test reusing the non-object card cases.

### D9. Dead `_a2ui_advertised` wrapper — `agent_sdk/testing/turns.py:132` (round: RT-006) [sdkCandidate]
- Quote: `async def _a2ui_advertised(driver: ChatDriver) -> bool:`
- Problem: one-line pass-through used only by tests (:645, :653); looks like a second gate entry point.
- Fix: delete; point tests at `ChatDriver._a2ui_advertised` or `ChatDriver.a2ui_client_activation()`.

### D10. Malformed SSE frames escape as tracebacks — `agent_sdk/testing/turns.py:180` (also `_text_of` :147) (round: RT-007) [sdkCandidate]
- Quote: `ev = json.loads(line[5:].strip())`
- Problem: only HTTPStatusError/TransportError handled. Non-JSON `data:` (ValueError), non-object event (AttributeError), text part without `text` (KeyError) escape run_turn instead of a fixed-reason failure record.
- Fix: catch ValueError/KeyError/TypeError/AttributeError → `at.reason = "bad-stream"`; skip non-dict events; `_text_of` uses `p.get("text")` and keeps only str. Add malformed-frame test.

### D11. Test swallows any exception from resume() — `tests/test_gh237_testing_clients.py:778` (round: RT-005) [sdkCandidate]
- Quote: `except Exception:  # unknown task: the server refuses, the request still went out`
- Problem: a ChatDriver crash after the POST is hidden; test still passes.
- Fix: `pytest.raises(A2AError)` and assert code TASK_NOT_FOUND.

---
Filed 2026-10-25 by /sdk-autoloop cycle 2: verified still-present mediums (and lows sharing a fix) are in #261–#267. Other lows stay here, unfiled.
