wave: w045
scope: lrn-cap-exceeded
date: 2026-10-11
MAX_LRN_PER_WAVE: 20
status: non-blocking (fixed, not codified)

These findings were already fixed but not codified as LRN files due to the 20-per-wave cap. Review and codify opportunistically, or fold into a future wave.

Count: 3 findings over the cap.

## RT-003 (high) — sdkCandidate

- File: `tests/test_gh154_current_date.py`
- Description: The SI-2 test `test_hostile_zone_never_leaks` asserts `marker not in caplog.text` on root caplog after `_build()` calls build_app(), which calls configure_logging() and sets `agent_sdk.propagate=False`. When this is the first app built in the process (running the file or test alone), that undoes the autouse `_restore_sdk_log_propagation` fixture mid-test, caplog captures nothing from `agent_sdk.*`, and the negative assertion is vacuously true. Verified with a probe: after `_build(tmp_path)`, a warning on `agent_sdk.agent.runner` does not appear in caplog.text in isolation. This is the LRN-106 Check clause, and the log half of the AC-mandated SI-2 regression test does not reliably test anything (LRN-128).
- Fix: Use the `sdk_caplog` fixture (handler attached directly to the `agent_sdk` logger), or call build_app before setting `agent_sdk.propagate=True` inside the test with restoration. Add a positive control: emit a known record and assert it is captured before asserting the marker is absent.
- Codify: A negative log assertion must prove its capture works, with a positive control or a handler attached directly to the agent_sdk logger, because build_app can switch off propagation mid-test.

## proto-A2A-d3-d7-6 — Part handling / -32005 ContentTypeNotSupported on message/send+stream (high)

- File: protocol-surface (`agent_sdk/routes/a2a.py`)
- Description: agent_sdk/routes/a2a.py:363-364 (_message_text) keeps only TextPart text. A valid inbound Message holding only FilePart or DataPart parts (for example an A2UI userAction DataPart) is accepted, and the model is fed the placeholder text ' ' (line 480). The parts are silently dropped. The request is neither processed nor rejected with -32005/415. File parts mixed with text are also dropped without any signal.
- Fix: In _parse_send or _config_error, reject unsupported part kinds with a2a_error(A2A_CONTENT_TYPE_NOT_SUPPORTED). Alternatively, route DataPart and FilePart content into the model turn or the A2UI action path. Reject a message that has no text and no supported part, instead of sending ' ' to the model.
- Codify: Server MUST NOT silently discard inbound Part kinds it does not process; return -32005 (HTTP 415).

## proto-AG-UI — serialization uses exclude_none; optional fields must be omitted, never sent as null (high)

- File: protocol-surface (`agent_sdk/routes/ag_ui.py`)
- Description: agent_sdk/routes/ag_ui.py:238 and :273 always emit TOOL_CALL_START with parentMessageId set to self.last_message_id, which is None when the turn has no preceding assistant text (the common tool-first turn, and every synthetic START on a resume run). sse_data (common/sse.py) uses json.dumps, so the frame carries "parentMessageId":null. The reference encoder uses model_dump_json(by_alias=True, exclude_none=True), and parent_message_id is Optional[str]. Strict clients that validate with the published schema (string-or-absent) reject null and can drop the event or abort the stream. The code comment says this is deliberate ('always present so consumers can key on the field'), but that contradicts the wire contract.
- Fix: Build the START frame without the key when last_message_id is None (add parentMessageId only if not None) at both sites (lines ~232-239 and ~269-274). Add a test that no emitted frame contains a null value for an optional field.
- Codify: Wire frames must follow exclude_none: omit optional keys instead of emitting null.
