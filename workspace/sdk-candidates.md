# SDK issue candidates — w040 (2026-09-02)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

## Candidate 1: GH-148's cross-turn $ref substitution mechanism is claimed (reuse.py docstring, loop.py, CHANGELOG, regression test) to work identically on A2A and AG-UI, but routes/ag_ui.py's _fold_history only reads type=='text' parts, dropping every toolResult block (and the __resolved__ markers folded inside them) on the client-resent transcript; scan_resolved() is empty at the start of every AG-UI run, so the fix is a silent no-op on the exact transport GH-148's own repro used.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/agent/reuse.py:16-20 (root cause: agent_sdk/routes/ag_ui.py:88-109 _fold_history)
- Rationale: Core SDK protocol-route behavior (agent_sdk/routes/ag_ui.py history fold) with no agent-domain code involved; the defect and both proposed fix paths (persist server-side per threadId, or round-trip via state/forwardedProps) live in the AG-UI transport handling itself.

## Candidate 2: Reusable is unwrapped only on loop.py's synchronous dispatch path; ToolEntry.invoke_any (registry.py:481) returns the raw wrapper to every other caller, so MCP tools/call folds the literal dataclass repr onto the wire (and fails ValidationError when the tool declares emits), admin's try-tool leaks the wrapper's internal shape through _safe_result, and contrib/commitments passes an unresolved $ref argument straight into the tool body.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/registry.py:481
- Rationale: Fix is entirely inside registry.py's shared dispatch helper (ToolEntry.invoke_any); the MCP/admin/commitments surfaces are just callers, not where the code changes. Core SDK internals per the rubric.

## Candidate 3: reuse_fields_for_model calls typing.get_type_hints(include_extras=True) at @tools.tool decoration time, which resolves string annotations against module globals only; pydantic v2 also resolves against the defining frame's locals, so a tool whose input_model is defined in a local scope raises NameError at registration even though pydantic itself built the model fine — breaking the AC that unaffected tools see byte-identical behavior.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/reuse.py:114
- Rationale: Pure agent/reuse.py fix (read Annotated metadata from model_fields[...].metadata instead of re-resolving hints). Core SDK internals, no agent-domain code.

## Candidate 4: The GH-87 deferred-handoff path returns out of run_loop after the assistant toolUse message is appended but before the matching toolResult, and _run_deferred_background never appends the missing toolResult to record.messages — leaving a dangling toolUse that Converse-shaped backends (Bedrock) reject on the next contextId turn, contradicting GH-147 AC-3.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/loop.py:595
- Rationale: Fix lives in agent/runner.py's background awaiter (append the real toolResult on resolve, synthetic error toolResult on failure). Core SDK loop/runner internals.

## Candidate 5: The __resolved__ marker block folds result.value raw into messages instead of going through _fold_result_content like the sibling result block does; since Reusable.value is typed Any and BaseModel returns are explicitly supported, a Reusable wrapping a pydantic model plants a non-JSON-serializable object in messages and poisons the whole conversation on the next json.dumps.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/loop.py:645-647
- Rationale: Pure agent/loop.py fix (normalize marker value via _fold_result_content before folding). Core SDK internals.

## Candidate 6: A deferred (GH-87) tool whose handle resolves to a Reusable leaks the raw dataclass repr into record.messages and onto the A2A/AG-UI wire, and folds no __resolved__ marker, because _run_deferred_background bypasses invoke_any and never unwraps Reusable the way loop.py's synchronous branch does — making GH-148 dead for long-running resolver tools.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/runner.py:485
- Rationale: File is agent_sdk/agent/runner.py — core SDK agent-runner internals, not agent-domain code. Input data tagged this sdkCandidate:false; I'm overriding that per the stated rubric since nothing here is agent-specific tool code, a domain adapter, or a test.

## Candidate 7: The ReuseKind mismatch rejection error tells the model how to bypass the check itself ("prefix it with $raw: ... to bypass this check"), so a model that hallucinated a wrong id can immediately re-submit it via $raw: and execute it, turning GH-148's only correctness gate into a speed bump and contradicting the todo's AC that the error should only suggest re-resolve or $ref.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/reuse.py:464
- Rationale: Pure agent/reuse.py fix (drop the $raw: hint from the model-facing error text; make raw-override an explicit per-field operator opt-in). Core SDK internals; overriding the input's sdkCandidate:false per the file-location rubric.

## Candidate 8: resolve_reuse_fields treats an explicit None argument on an Optional ReuseKind field as a raw value to check against prior resolutions, so once any resolution of that kind exists, the tool becomes permanently uncallable with its optional field omitted-as-null (and $raw: can't recover it, since it yields empty string, not None).
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/reuse.py:403
- Rationale: Pure agent/reuse.py fix (skip the raw-value contract entirely when raw is None). Core SDK internals; overriding the input's sdkCandidate:false per the file-location rubric.

## Candidate 9: GH-147 AC3 (no two consecutive same-role messages across a contextId continuation) is not met for a deferred task: run_loop returns at the DeferredEvent handoff without calling _bridge_trailing_user, runner.py's repair_dangling_tool_use appends a user toolResult, and routes/a2a.py appends another user turn on continuation — yielding a role sequence Bedrock's Converse API rejects. The same gap applies to GH-150's tasks_cancel repair.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/loop.py:790
- Rationale: Fix is exporting and calling loop.py's own _bridge_trailing_user from every out-of-loop transcript writer (runner.py, routes/a2a.py::tasks_cancel). Core SDK loop internals; overriding the input's sdkCandidate:false per the file-location rubric.

## Candidate 10: ToolEntry.input_schema() unconditionally appends the $ref:<kind> affordance hint to a ReuseKind field's description, but that same schema is served on MCP tools/list and the agent card (routes/agent_card.py) where the substitution/validation gate does not exist — an MCP client is told it may send $ref:entity_id, and the SDK's own test proves that literal string then reaches the tool body verbatim.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/registry.py:364
- Rationale: Fix is entirely inside registry.py (add an include_reuse_hint parameter, pass it only from loop.py); routes/mcp.py and routes/agent_card.py need no change. Core SDK internals; overriding the input's sdkCandidate:false per the file-location rubric.

## Candidate 11: reuse_fields_for_model / reuse_strict_for_model / reuse_raw_override_for_model key their maps on the Python field name, but model_json_schema() and model_validate use the pydantic alias — so any ReuseKind field with an alias silently fails open: the mismatch gate never fires, no $ref hint is advertised, and a $ref:<kind> token passes through to the tool body as a literal string with no error or warning.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/reuse.py:251
- Rationale: Pure agent/reuse.py (plus registry.py's input_schema lookup) fix — key both by alias-or-field-name. Core SDK internals.

## Candidate 12: run_task_worker's two terminal exception handlers (AgentError, bare Exception) set the task FAILED and publish the terminal frame without calling repair_dangling_tool_use, leaving record.messages ending on an unmatched assistant toolUse that Bedrock's Converse API rejects on replay — reproduced via a documented max_interrupted AgentError path. This also falsifies loop.py's own docstring claim that repair_dangling_tool_use covers every current and future caller.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/runner.py:881
- Rationale: Pure agent/runner.py fix (call repair_dangling_tool_use before _set_status(FAILED) in both handlers) plus a docstring correction in loop.py. Core SDK internals.

## Candidate 13: The AuditEvent branch re-serializes record.task.status as-is via _status_frame, so the audit status-update frame re-emits the previous chat sentence (status.message) on the A2A stream instead of carrying an empty message — contradicting AuditEvent's own docstring that audit detail should never appear in status.message, and duplicating agent text to the client.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/runner.py:763
- Rationale: Pure agent/runner.py fix (build the audit frame with a message-free status instead of reusing the record's stale status). Core SDK internals.

## Candidate 14: GH-148 is not actually fixed on AG-UI, the transport the issue's own repro used: routes/ag_ui.py's _fold_history rebuilds resent messages from text-only parts, dropping all toolResult blocks, and every POST /ag-ui/run creates a fresh TaskRecord with no equivalent of context_messages — so scan_resolved() is always empty and the mismatch gate can never fire on AG-UI, despite the todo's Design section and AC explicitly claiming AG-UI parity.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/agent/reuse.py:359 (root cause: agent_sdk/routes/ag_ui.py fold + per-request TaskRecord creation)
- Rationale: Defect and both proposed fixes (server-side per-thread carrier, or a loud warning) live in the AG-UI route's request/history handling, not the shared reuse mechanism. Core SDK protocol-route behavior.

## Candidate 15: AG-UI cross-request reuse carriage survives exactly one run hop, not a conversation: store.context_messages returns only the single most-recent terminal task's messages, and routes/ag_ui.py deliberately does not fold prior into the new record — so after one intervening unrelated run on the same threadId, $ref no longer resolves and a wrong raw id is silently executed, reopening the exact substitution bug GH-148 exists to catch. CHANGELOG/DESIGN.md/reuse.py all overstate this as fixed; the shipped test only covers two consecutive runs and can't see the decay.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/routes/ag_ui.py:525
- Rationale: File and root cause are directly in agent_sdk/routes/ag_ui.py (TaskStore lookup scoped to the newest terminal task only). Core SDK protocol-route behavior.

## Candidate 16: The bounded-recovery (RT-A-008) escape hatch that forces a stuck-reject sequence to pass through after N tries never applies to the ambiguity-rejection branch, because that branch returns before the reject_counts increment/threshold check that only lives in the single-resolution mismatch branch. With two or more resolutions of a kind on record (the common multi-entity case), a genuinely new raw value is rejected forever with no in-band recovery, contradicting the module docstring's claim that the guarantee is unconditional.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/agent/reuse.py:676
- Rationale: Pure agent/reuse.py fix (hoist the reject_counts block to cover every rejection return path, including the ambiguity case). Core SDK internals.

## Candidate 17: The A2UI Standard Profile v1 frozen field contract (`.claude/agents/a2ui-advisor.md` et al., DESIGN.md stable core) documents `TimeSeriesChart.metadata` as a typed sub-shape `{identifier?, metric?, frequency?, source?}`, but no shipped code has ever implemented that shape — `ContentModel.metadata` (agent_sdk/models/content_types.py) has been free-form `dict[str, Any] | None` since its introduction, and GH-63 (v0.5.16) already generalized that free-form shape to all 14 Profile types, treating `TimeSeriesChart` as the pattern's origin rather than a type it widened. RT-004/REVIEWS.md Round 10 reverted a same-wave doc edit that silently dropped the row to match the code (self-authorized, no maintainer sign-off, the exact inverse of GH-149's code-conforms-to-doc resolution) — the row is restored pending this issue. A maintainer needs to decide, as an explicit Profile v1.1 amendment: either (a) drop the typed row and adopt the SDK-wide free-form `metadata` note across all FROZEN types (bump the Profile version, update all three a2ui-advisor copies + `tests/test_rt002_a2ui_wire_shape_mirror_parity.py`'s `ROUND_8_METADATA_ROW_REMOVAL_RATIFIED` to `True` in the same commit), or (b) keep the row and add the typed sub-shape validation to `TimeSeriesChart` that has never existed.
- Severity: medium
- Component: sdk/a2ui
- File: .claude/agents/a2ui-advisor.md:273-291 (TimeSeriesChart field table); agent_sdk/models/content_types.py:228 (ContentModel.metadata base-class field)
- Rationale: A frozen A2UI Standard Profile v1 field-contract question (DESIGN.md stable core) requiring an explicit maintainer ratification, not a same-wave doc edit — see REVIEWS.md Round 8 and Round 10 for the full history and the standing "wave self-signoff needs user ratification" rule.
