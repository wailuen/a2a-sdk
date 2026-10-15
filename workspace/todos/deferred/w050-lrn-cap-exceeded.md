wave: w050
date: 2026-10-15
MAX_LRN_PER_WAVE: 20
status: lrn-cap-exceeded
overflow_count: 10

## Context

These findings were already fixed but not codified as LRN files due to the 20-per-wave cap. Review and codify opportunistically, or fold into a future wave.

These 10 critical/high findings were surfaced by the w050 redteam loop and were already fixed in code during the wave, but exceeded MAX_LRN_PER_WAVE (20) and so were not individually codified as LRN files in workspace/learning/. Note: RT-NNN ids repeat across redteam rounds; identify each entry by id + file.

## Findings

### RT-003 — workspace/components/README.md
- severity: high
- description: [SDK] LRN-287 Check fails for two Reuses directives that landed neither branch. (1) Reuses: C-021 said to define BASIC_CATALOG_COMPONENTS next to the A2UI catalog (agent_sdk/a2ui/catalog.py or the planned profile.py). It landed in agent_sdk/models/content_types.py:164, nothing is imported from the catalog, and the C-021 row (README line 25 and lines 155-156) is unchanged. It now holds a third copy of the 18 names, with the a2ui-advisor docs holding the other two. (2) Reuses: C-036 asked for a cross-reference in the C-034 and C-036 registry entries, so a later wave does not merge the tail-cut '…' marker with truncate_middle's counted marker. The C-034 entry does not mention C-036, and the C-036 row (line 35 and lines 200-201) is unchanged. Unit rounds deferred both as medium (G2 RT-005, G3 RT-004). The LRN-287 Check is binary, so the item inherits high.
- fix: The smallest change that passes LRN-287 is to edit the registry rows. In C-021, record that `BASIC_CATALOG_COMPONENTS` lives in `agent_sdk/models/content_types.py` because catalog.py imports content_types (circular import), and that C-021/profile.py must import it from there when it lands. Also note that the a2ui-advisor lists are copies. In C-034, add: 'tail cut with a one-char `…` (LINE_TEXT_CUT_MARKER) counted in the cap; NOT the C-036 middle cut; do not merge'. Add the reverse note in C-036. Optionally move the tuple to a leaf module with no imports (for example agent_sdk/a2ui/basic_catalog.py) and import it in both places.
- codify: A Reuses: C-NNN directive that names a placement or a registry cross-reference is unmet unless the code imports the component or the README row for that C-NNN changes in the same wave.
- sdkCandidate: true

### RT-001 — agent_sdk/routes/mcp.py
- severity: high
- description: [SDK] The legacy MCP SSE queue writer at mcp.py:1200 now uses dumps_strict, which sets ensure_ascii=False. It used json.dumps with ensure_ascii=True before. A tool result holding a lone surrogate (for example json.loads('"a\\ud800b"'), which is common when an upstream API cuts an emoji in half) now passes _is_writable (mcp.py:361), because that check never encodes to bytes. The SSE generator then raises UnicodeEncodeError at mcp.py:1119 (f"...data: {payload}".encode()). That kills the legacy session stream, and the client never gets a reply. Probe: the old bytes were '{"result": ... "a\\ud800b"}' and encoded fine; the new bytes raise UnicodeEncodeError. The CHANGELOG line 'MCP and SSE output bytes are unchanged' is also false: separators and ensure_ascii both changed for the legacy queue. Per LRN-364, CHANGELOG claims must be checked against a probe.
- fix: Make _is_writable check dumps_strict(payload).encode('utf-8'). UnicodeEncodeError is a subclass of ValueError, so the existing except clause already catches it, and both MCP transports then answer with the fixed isError or -32603 reply. Or keep ensure_ascii=True for the legacy queue write. Add a /mcp/messages route test whose tool output holds a lone surrogate, and fix the CHANGELOG 'bytes unchanged' claim. sse_data (common/sse.py) and _strict_json_response have the same un-encodable-string gap; the A2A path is already caught because UnicodeEncodeError is a ValueError. Cover them in the same test sweep.
- codify: When a shared strict serializer replaces an ensure_ascii=True writer, the writability check must encode to UTF-8 bytes too, or a lone surrogate passes the check and crashes the stream.
- sdkCandidate: true

### RT-001 — agent_sdk/agent/runner.py
- severity: high
- description: [SDK] build_artifact's serialize gate (runner.py:471) still uses json.dumps(..., ensure_ascii=False, allow_nan=False) with no UTF-8 check. It does not use the new dumps_strict. A tool result holding a lone surrogate passes the gate and the task is stored COMPLETED with its artifact. Every later read of that task then fails. Verified with a probe: message:send returned 200 (submitted), the stored state was completed, GET /v1/tasks/{id} returned 502 -32006, and GET /v1/tasks returned 502 for the whole list. The stream path sends a FAILED tail while the store says COMPLETED. This is the false-COMPLETED split that the RT-001 comment in build_artifact says this gate exists to prevent. The CHANGELOG says lone surrogates now get a clean -32006, but the task itself is poisoned.
- fix: Replace the json.dumps call at runner.py:471 with dumps_strict(artifact.wire()). Keep catching (TypeError, ValueError) so the task fails deterministically with -32006 before COMPLETED. Add a route test: a tool returns a model_construct'ed BarChart with category=json.loads('"a\\ud800b"'). Assert the task ends FAILED, and that GET /v1/tasks/{id} and GET /v1/tasks both return 200.
- codify: When a strict serializer gains a new rejection rule, the pre-commit artifact gate in build_artifact must call the same helper. Otherwise tasks commit COMPLETED and then fail on every read.
- sdkCandidate: true

### RT-002 — agent_sdk/common/json_strict.py
- severity: high
- description: [SDK] loads_strict accepts JSON escapes that decode to a lone surrogate ("\ud800"), so client input that no writer can encode gets past every ingress. Two cases were verified by probe. (1) A2A: message:send with text "hi\ud800" creates a task and starts a worker, then answers 502 -32006 'invalid agent response'. That is a server-fault code for client-caused input. GET /v1/tasks then returns 502 for that identity until the task is evicted (a self-inflicted or shared-key DoS). (2) AG-UI: threadId "t\ud800" raises an unhandled ValueError from the unguarded `yield sse_data({"type": "RUN_STARTED", ...})` at ag_ui.py:675. Every fallback RUN_ERROR frame also echoes threadId, so no terminal frame can be written. This fails the LRN-363 Check (every sse_data call in ag_ui.py must sit inside a ValueError guard). It also contradicts the CHANGELOG RT-001 claim that AG-UI answers with a RUN_ERROR.
- fix: Make loads_strict reject any decoded string (key or value) that cannot be encoded as UTF-8. Raise the same fixed-text ValueError the transports already map to 400/-32700/-32602, so the request is refused before any task, stream or worker exists. Also guard the RUN_STARTED write in ag_ui.py, or validate threadId/runId before the stream starts. Add ingress tests for A2A (text, messageId, contextId), AG-UI (threadId, runId, state) and MCP.
- codify: Outbound UTF-8 refusal needs a matching inbound refusal. A strict ingress parser must reject every value a strict writer will later refuse, or client input poisons stored state.
- sdkCandidate: true

### RT-001 — agent_sdk/agent/runner.py
- severity: high
- description: The w050 RT-001/RT-002 claim (CHANGELOG.md:35) that a lone-surrogate string 'can no longer be stored in a task' is false. Only ingress (loads_strict) and build_artifact enforce the rule. Model text (TextEvent), ProgressEvent, NoteEvent and ToolProgressEvent messages go through set_task_status/_agent_message (runner.py:1282-1322, 91, 120) with no check. Probe confirmed: fake_model.script(reply('hello ' + json.loads('"a\\ud800b"'))) then POST /v1/message:send returns 200, then GET /v1/tasks/{id} returns 502 -32006 and GET /v1/tasks returns 502 -32006. So one bad task blocks task listing for the whole identity until it is evicted. A tool progress message built from upstream data (the 'upstream API cut an emoji in half' case the CHANGELOG names) reaches the same path.
- fix: Apply the rule at the one place status and history are committed. In _agent_message, or in set_task_status before it mutates record.task, replace code points that cannot be encoded (for example text.encode('utf-8','surrogatepass').decode('utf-8','replace'), or a regex swapping [\ud800-\udfff] for U+FFFD). Do this for every message text and metadata string. Also make tasks_list serialize each task on its own and leave out or redact one that fails, so a single bad record cannot 502 the whole list. Add route tests for TextEvent and ToolProgressEvent carrying a lone surrogate: tasks/get and tasks/list must stay 200. Correct the CHANGELOG RT-001/RT-002 entry.
- codify: An encodability or finiteness rule must be enforced at the store-commit choke point (set_task_status / artifact commit), not only at ingress and one artifact gate, or any other producer of task text poisons every later read.
- sdkCandidate: true

### RT-002 — agent_sdk/models/content_types.py
- severity: high
- description: GH-177 AC 'The plain-text fallback still shows the modified date and modified_by as today' is not met. DocumentList._body_text (line 1470) now uses `d.modified or d.last_modified`; before, it used `d.last_modified or d.modified`. Combined with the wire remap, which drops last_modified whenever modified is set, a value in last_modified now appears on NO surface. The ruling names the downstream agent that hits this: a2a-ilevel get_document sets modified=periodEnd and last_modified=uploadDate (src/tools/documents.py:143-149). Its upload date used to show in content[0].text. Now it is gone from the wire, the text fallback and the A2UI value. The CHANGELOG migration ('read modified instead of last_modified') points such a consumer at a different date.
- fix: Keep today's text output. When both are set and differ, render both, e.g. '    modified: <modified>' and '    last modified: <last_modified>'. When only one is set, render that one. Update test_text_date_matches_wire_modified_when_both_set to match. Add a CHANGELOG note that when both fields are set, last_modified is not on the wire, and say where it can still be read.
- codify: When a wire remap folds an alias into a contract key, check every existing producer that sets both with different meanings; a 'fill when empty' rule silently deletes the alias's value from all surfaces.
- sdkCandidate: true

### RT-003 — agent_sdk/console/static/a2ui.js
- severity: high
- description: GH-177 AC 'The console renderer (a2ui.js) reads modified/link' is not met. renderDocumentList (lines 867-885) only swaps the order of modified and last_modified and never reads d.link. The CHANGELOG Breaking entry (CHANGELOG.md:13) still says 'the console renderer reads modified/link'. That contradicts the CHANGELOG's own Fixed entry for the console, which describes only the modified fallback. The release notes misdescribe shipped behaviour.
- fix: Either render d.link as an <a> built through el() with text nodes only, allowing only the http: and https: schemes (no javascript:/data:) per the todo's console-href SI note, with a fallback to d.web_url. Or drop 'link' from the AC and from CHANGELOG.md:13 so the release notes match the code. If you render the link, add a console test for the scheme allowlist.
- codify: A CHANGELOG claim about a renderer must be checked against the renderer source before release; ACs naming a field the renderer must read need a grep-level verification.
- sdkCandidate: true

### RT-004 — workspace/todos/active/w050-gh-issues.md
- severity: high
- description: LRN-361 Check fails (scope drift). Files changed in the tree but on no Creates:/Modifies: line: tests/test_gh171_fallback_schema_required.py (compact-schema pin edited), tests/test_rt001_lone_surrogate_writers.py and tests/test_rt_w050_lone_surrogate_state.py (new), uv.lock. A listed file has no diff: tests/test_rt003_super_to_plain_text_no_recursion.py (G1). The mid-wave loads_strict change (it now refuses lone surrogates) also changes agent_sdk/routes/oauth.py /register: such a body now gets 400 invalid_client_metadata. The CHANGELOG lists A2A, AG-UI and MCP but not OAuth dynamic client registration.
- fix: Add the four paths to the matching todo Modifies/Creates lines (G5 or a fix-round note), and remove test_rt003_super_to_plain_text_no_recursion.py from G1 or add a GH-174 assertion to it. Extend the CHANGELOG RT-001/RT-002 entry to name POST /oauth/register.
- codify: Fix rounds that add tests or widen a shared ingress helper must back-propagate every touched path and every newly affected route into the todo and CHANGELOG in the same round (LRN-361).
- sdkCandidate: true

### RT-001 — workspace/todos/active/w050-gh-issues.md
- severity: high
- description: LRN-359 Check fails: workspace/components/README.md is in the working-tree diff (C-020 placement note, C-034/C-036 cross-references), but no todo lists it under Creates:/Modifies:. GH-175 names it only under Reads:, even though its own AC requires editing it.
- fix: Add workspace/components/README.md to the GH-175 Creates/Modifies line, and to GH-176's, which added the C-020 placement note. Then rerun the LRN-359 check: every path from `git diff --name-only` must appear in a Creates/Modifies line.
- codify: When an AC requires editing a file, the todo must list that file under Modifies, not Reads, or the scope scan and LRN-359 check miss it.
- sdkCandidate: true

### RT-001 — agent_sdk/models/content_types.py
- severity: high
- description: [SDK] GH-177's `DocumentItem._wire_contract_keys` (line 1434) is a model-wide `@model_serializer(mode='wrap')`. It removes `web_url`/`last_modified` from every `model_dump()`, not only from the wire. `agent/loop.py::fold_result_content` (line 286) folds tool results into the LLM transcript with `model_dump(mode='json', by_alias=True, exclude_none=True)`. So the agent's own model no longer sees `last_modified` when `modified` is set. Verified: `fold_result_content(DocumentList(documents=[DocumentItem(id='1', name='n', modified='2025-12-31', last_modified='2026-02-03T10:00Z')]))` returns only `modified`. The a2a-ilevel agent, which the ruling names, sets modified=periodEnd and last_modified=uploadDate (src/tools/documents.py:143-149), so its model can no longer answer 'when was it uploaded'. The ruling (issue 177 comment 6187888894) limited the drop to 'the wire and the compact schema' and said to keep the fields because ilevel reads `last_modified`. Other effects: `DocumentItem.model_validate(doc.model_dump())` loses the value, and `model_json_schema(mode='serialization')` collapses to `{type: object, additionalProperties: true}`.
- fix: Apply the remap only on wire paths. Gate the serializer on a serialization context, e.g. `if not (info.context or {}).get('wire'): return data` using `SerializationInfo`. Pass `context={'wire': True}` from `_Wire.wire()` and from `build_artifact`'s non-A2UI DataPart `model_dump`. Leave `model_dump()` (the LLM fold, round trips) with all fields. Add a test that `fold_result_content` keeps `last_modified` while `wire()` and the A2A DataPart do not.
- codify: A wire-only key remap must not be a model-wide @model_serializer, because model_dump also feeds the LLM tool-result fold and round trips. Gate it on a wire serialization context.
- sdkCandidate: true
