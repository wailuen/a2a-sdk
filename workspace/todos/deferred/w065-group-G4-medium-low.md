# w065 — unit:G4 — deferred medium/low findings

- Wave: w065
- Scope: unit:G4 (GH-247, follow-up to GH-235: AG-UI resume validation, strict tool JSON, capped body)
- Date: 2026-10-24

Non-blocking — these did not block w065's archive. Address opportunistically or fold into a future wave.

Findings were raised across several redteam rounds. Duplicates (same file + same problem) are merged below; RT ids from each round are listed.

## Medium

### D1. Docs and docstrings still advertise AG-UI `status="approved"/"rejected"` [SDK]
- Files: `docs/testing.md:173`, `docs/tools.md:222-224`, `agent_sdk/contrib/action_gate/__init__.py:40`, `agent_sdk/contrib/action_gate/gate.py:131-132` (RT-002, RT-003, RT-008, RT-009 across rounds)
- Problem: the route now ends such a resume with RUN_ERROR `invalid resume entry`. The `ChatDriver.agui_resume` example in docs/testing.md sends `status="approved"` (and its comment is stale). docs/tools.md, the action_gate module docstring and the `parse_decision` docstring still call the shorthand in `status` "this SDK's core convention".
- Fix: docs/testing.md example → `status="resolved", payload={"decision": "approved"}` (or omit status); comment says publish_note reads `payload.decision`. docs/tools.md and both docstrings: AG-UI `status` is `resolved`/`cancelled` (or absent), decision in `payload.decision`; A2A sends reply text or DataPart `payload.decision`; other status words are refused by `POST /ag-ui/run` (GH-247) and reachable only by direct callers.
- Codify: when a route starts rejecting an input form, grep `docs/` and `agent_sdk/` for every literal use of it.

### D2. CHANGELOG entry hides a breaking change under Fixed [SDK]
- File: `CHANGELOG.md:11` (RT-004, RT-005, RT-002, RT-011 across rounds)
- Problem: the GH-247 entry removes a documented, accepted wire form (AG-UI shorthand status) but sits under `### Fixed` with only a Migration line — no `🔴 Breaking changes` heading, no AG-UI spec citation, no "spec-conformance fix, kept under Fixed (GH-221 precedent)" note (LRN-201 / LRN-436). It re-announces the multi-entry RUN_ERROR already shipped in 0.21.0. The "before any interrupt lookup" claim needs checking against RT-001. Changed/Tests lists omit `tests/test_contrib_action_gate.py`, `agent_sdk/example/agent.py`, `docs/tools.md`. It does not say that absent/null/`[]` resume means a fresh run. The GH-247 ruling did not name the shorthand removal.
- Fix: record the shorthand removal on GH-247 as an explicit trade-off for ratification. Then either move it under `### 🔴 Breaking changes` (DESIGN.md §4.0; impact: emit none, parse shorthand → RUN_ERROR) or add spec citation + GH-221 precedent note — or keep the shorthand by mapping approved/rejected to resolved + `payload.decision`. Drop the already-shipped sentence; complete the file lists; state the fresh-run rule here and in docs/protocols.md:114.
- Codify: an entry that removes an accepted input form needs a spec clause or a Breaking heading.

### D3. `_tool_json` fallback is too broad in one way and too narrow in another [SDK]
- File: `agent_sdk/routes/ag_ui.py:194-195`, `:361` (RT-005 r1, RT-005 r3, RT-007 r4)
- Problem: (a) switching from `json.dumps(default=str)` to `dumps_strict` turns any dict/list result with datetime, Decimal, UUID or Enum into `tool result not serializable` — silent fidelity loss. (b) Only ValueError/TypeError are caught: a value whose `__str__` raises RuntimeError, or a BaseModel whose `model_dump` (run outside the try) raises, ends the run with RUN_ERROR `internal error` instead of the fallback. (c) No log line on fallback.
- Fix: do `model_dump` inside the helper's try; first convert with `pydantic_core.to_jsonable_python(value, fallback=str)`, then `dumps_strict`; catch Exception; log `ag-ui tool json fallback error_type=%s` (type only, SI-2). Tests: datetime in a dict result renders; model whose dump raises gives the fallback.

### D4. AG-UI Content-Type check is case-sensitive substring [SDK]
- File: `agent_sdk/routes/ag_ui.py:633-637` (RT-009 r1/r2, RT-003 r3, RT-005 r4)
- Problem: GH-246/GH-248 fixed MCP and A2A this wave; AG-UI still uses `"application/json" not in ct`. `Application/JSON` gets 415 here (RFC 9110 §8.3.1 says case-insensitive) and `application/json-patch+json` / `application/json-seq` pass. Breaks LRN-093 three-surface uniformity.
- Fix: `ct.split(";",1)[0].strip().lower() != "application/json"` → 415, ideally sharing mcp.py's `_is_json_content_type`. Tests: `Application/JSON; charset=utf-8` accepted; `application/json-seq` 415.
- Codify: a Content-Type rule changed on one protocol surface must change on all three in the same wave.

### D5. No test for the AG-UI 413 body cap
- File: `agent_sdk/routes/ag_ui.py:639-640`, tests in `tests/test_gh235_nested_json_and_resume.py` (RT-006 r1, RT-007 r2, RT-004 r4)
- Problem: the AC moved `/ag-ui/run` onto `read_capped_body`, but nothing tests it (only MCP in `tests/test_gh246_mcp_route.py`).
- Fix: tests for declared Content-Length > cap → 413 `request body too large` before read; chunked over-cap body → 413; body exactly at cap admitted; no RUN_STARTED, no task created.

### D6. Test-file rewrite deleted GH-235 regression tests [SDK]
- File: `tests/test_gh235_nested_json_and_resume.py` (RT-004 r3, RT-003 r4)
- Problem: removed with no replacement: `test_oauth_register_nested_is_invalid_client_metadata`, `test_a2a_deep_metadata_never_breaks_task_list`, the object-nesting case of the `loads_strict` depth test, and the below-cap two-entry resume test with MARKER in entry 2 (SI-2). All pass on current code — lost coverage, not a bug. Docstring names only GH-247.
- Fix: restore all four (here or in `tests/test_gh250_core_hardening.py`); docstring covers GH-235, GH-247, GH-250.
- Codify: a wave that rewrites a test file must keep every earlier issue's regression test.

### D7. Missing/null status test is too weak
- File: `tests/test_gh235_nested_json_and_resume.py:71` (RT-006 r2, RT-009 r4)
- Problem: only checks RUN_FINISHED for a missing status; never sends `"status": null`; never checks the handler got `status None` or that the tool published (LRN-418).
- Fix: parametrize over missing and `None`; assert TOOL_CALL_RESULT holds `"published":true` and/or spy `store.deliver_resume` for `envelope.value["status"] is None`.

## Low

### D8. docs/protocols.md describes an A2A `status` field that does not exist [SDK]
- File: `docs/protocols.md:123-124` (RT-007 r1, RT-004 r2, RT-007 r3, RT-001 r4)
- Problem: says the shorthand in `status` is "accepted on the A2A resume path only". A2A has no status: TextPart text goes to `parse_decision` as a string; a DataPart becomes `{"status": None, "payload": data}` (a2a.py:428). "The two are merged REJECT-WINS" then refers to forms that cannot co-occur.
- Fix: "On A2A the decision is the reply text (e.g. `approved`) or `payload.decision` in a DataPart; there is no `status` field. On AG-UI a `cancelled` status plus `payload.decision` is merged REJECT-WINS."

### D9. Resume-entry rules written in three places [SDK]
- File: `agent_sdk/routes/ag_ui.py:557`, `:756-760`, `_validate` (RT-008 r2, RT-006 r3, RT-006 r4)
- Problem: list / one-entry / dict / status rules are duplicated across `_validate`, `_run` and `_resume_interrupt_id`, whose docstring says it exists so pre-admission and `_run` never disagree. Docstring omits the new rules.
- Fix: one helper `_resume_entry_problem(body) -> str | None`, called from `_validate` and `_resume_interrupt_id` (return `""` on problem); update docstring.

### D10. Tool-result fallback text not pinned
- File: `tests/test_gh235_nested_json_and_resume.py:125/147` (RT-010 r1/r2, RT-008 r3/r4)
- Problem: asserts only that `inf` is absent (via an odd replace); an empty or wrong fallback passes.
- Fix: `assert content == "tool result not serializable"` (or import `_RESULT_FALLBACK`).

### D11. DESIGN.md §5.3 lacks the new resume rules [SDK]
- File: `DESIGN.md:357` (RT-010 r4)
- Fix: add: `resume` holds exactly one entry; non-list, multi-entry, non-object entry, or a present status other than resolved/cancelled ends the run with RUN_ERROR `invalid resume entry` (code validation); missing/null status delivered as None; absent/null/empty `resume` is a fresh run (GH-247).
