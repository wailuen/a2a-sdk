# w061 — group G1 — deferred medium/low findings

- Wave: w061
- Scope: unit:G1
- Date: 2026-10-23

Non-blocking — these did not block w061's archive. Address opportunistically or fold into a future wave.

Deduped by file + description. Findings raised in more than one round are merged; their round IDs are listed.

## Medium

### D1 — Tuple-emits tool returning a non-member BaseModel is a silent success (RT-001 / RT-002 r1)
- File: `agent_sdk/routes/mcp.py:824`
- Quote: `or entry.decl.match_emits(artifact) is not None`
- Problem: A tuple-emits tool that returns a BaseModel matching no member gets `isError: false` and no `structuredContent`, although tools/list advertises an anyOf `outputSchema`. MCP 2025-06-18 requires conforming structured results. A raw dict that matches no member already returns `isError: true` ("tool output coercion failed"), so dict and model get different answers. Probe: `@tool(emits=(PA, PB))` returning `Other(z=1)` gave `{'content':[{'type':'text','text':'{"z":1}'}],'isError':False}`. No test covers it.
- Fix: In `_handle_tools_call`, when emits is a tuple, the artifact is a BaseModel and `match_emits(artifact) is None`, try coercion through the members on `artifact.model_dump(mode='json')` in declaration order (log type names only). If none validates, return the fixed `{'content':[{'type':'text','text':'tool output coercion failed'}],'isError':True}`. Add a test with a tuple tool returning a non-member BaseModel.
- Codify: When an MCP tool advertises outputSchema, every non-None success path must either send conforming structuredContent or become isError (the documented void deviation excepted).
- sdkCandidate: true

### D2 — pyproject.toml changed but not declared in wave scope (RT-003 r1)
- File: `pyproject.toml:36`
- Quote: `"jsonschema>=4.20",`
- Problem: G1 added a dev dependency, but no Creates:/Modifies: line in `workspace/todos/active/w061-gh-issues.md` lists `pyproject.toml`. LRN-322 / the GH-208 archive gate require every changed file to be declared.
- Fix: Add `pyproject.toml` to GH-225's Creates/Modifies clause, or drop the dependency.
- Codify: A test-only dependency added during implementation still widens wave scope; declare pyproject.toml in the todo.
- sdkCandidate: true

## Low

### D3 — `build_text_only_artifact` uses `str()` (RT-004, both rounds)
- File: `agent_sdk/agent/runner.py:393`
- Quote: `text = payload.to_plain_text() if isinstance(payload, ContentModel) else str(payload)`
- Problem: None becomes the literal text "None" (MCP and inline fold give ""). A plain BaseModel gives pydantic repr ("a=1"), while `build_artifact` uses `str(model_dump(mode='json'))`. Dicts give Python repr. A2A text then differs from the folded toolResult text for the same call.
- Fix: Reuse the fold helper (`fold_result_content(payload)`, or the mcp.py `_tool_text` rule): None gives "", models/dicts give JSON. At minimum mirror `build_artifact` for BaseModel. Add a None-result case to the deferred tests.
- sdkCandidate: true

### D4 — `normalize_emits` accepts non-class, non-tuple values (RT-005 r1 / RT-003 r2)
- File: `agent_sdk/agent/registry.py:476`
- Quote: `if not isinstance(emits, tuple):`
- Problem: `emits=KpiCard | TimeSeriesChart` (UnionType) or `emits=[A, B]` (list) is wrapped as a one-member tuple at decoration, then boot fails with an unclear `TypeError: issubclass() arg 1 must be a class` from `_validate_emits` (`output_schema()` raises the same). Verified by probe.
- Fix: In `normalize_emits`, raise `ValueError` when emits is not a tuple and not a class. For Union/UnionType, list, set, frozenset, point the author to `emits=(A, B)`. Add a decoration-time test.
- sdkCandidate: true

### D5 — Subclass result labelled with the member's data_type (RT-002 r2)
- File: `agent_sdk/agent/loop.py:1841`
- Quote: `data_type=getattr(matched, "data_type", entry.name),`
- Problem: A registered subclass result, e.g. `ExtKpi(KpiCard)` with data_type `ext_kpi`, gets metadata data_type `kpi_card`, while `translate()` renders ExtKpi's own component. The deferred path in runner.py does the same via `match_emits_type`.
- Fix: Use `getattr(type(result), 'data_type', None) or getattr(matched, 'data_type', entry.name)`. Apply the same in runner.py `_run_deferred_background`. Add a subclass-result test.
- sdkCandidate: true

### D6 — docs/tools.md says every tuple member must be a registered content type (RT-006 r1)
- File: `docs/tools.md:141`
- Quote: `- No empty tuple, no duplicates, every member a registered content type`
- Problem: Code accepts plain pydantic BaseModel members (`elif` branch in app.py `_validate_emits`; docs/content-types.md:192; GH-225 tests use PA/PB).
- Fix: Reword to "every member a registered content type or a plain pydantic BaseModel (ContentModel members must be registered and inside a2ui_allowed_components)".
- sdkCandidate: true

### D7 — DESIGN.md / protocols.md miss the list form of `x-sdk.emits` (RT-007 r1 / RT-005 r2)
- File: `DESIGN.md:252` (also `DESIGN.md:385`, `docs/protocols.md:161`)
- Problem: `x-sdk.emits` on the agent card is now a string for one type and a list of data_type strings for a tuple tool; the §4.5 card bullet and docs/protocols.md still imply a single string. Also, DESIGN never mentions the new deferred rule: a declared tool whose result matches no member gets a text-only artifact (CHANGELOG lists it under Changed; only docs/tools.md covers it).
- Fix: In the §4.5 AgentSkill/x-sdk bullet and docs/protocols.md, state `x-sdk.emits` is a data_type string, or a list of data_type strings for a tuple-emits tool (GH-225). Add one sentence to the GH-225 paragraph (line 385) or the deferred-task section on the deferred no-match text-only artifact.
- sdkCandidate: true

### D8 — Stale `DeferredEvent.emits` comment; output schema rebuilt per call (RT-008 r1)
- File: `agent_sdk/agent/deferred.py:57`
- Quote: `emits: type | tuple[type, ...] | None  # ToolDecl.emits — used to decide ArtifactEvent wrapping`
- Problem: The runner now decides wrapping and labels from `emits_types`; `DeferredEvent.emits` is no longer read for that. mcp.py and the loop also call `entry.output_schema()` on every tools/call, rebuilding the merged anyOf/$defs for tuple tools each time.
- Fix: Update the comment (kept for compatibility; `emits_types` drives wrapping). Optionally cache the tuple output schema on the ToolEntry (already built once at boot).
- sdkCandidate: true

### D9 — Widened `emits` typing not called out for consumers (RT-006 r2)
- File: `agent_sdk/agent/registry.py:397`
- Quote: `emits: type | tuple[type, ...] | None`
- Problem: `ToolDecl.emits` (reachable via `ToolSet.decls`) and `DeferredEvent.emits` widened from `type | None`. Downstream reads like `decl.emits.data_type` or `issubclass(decl.emits, X)` now fail mypy, though single-type runtime behaviour is unchanged. CHANGELOG does not mention it.
- Fix: Add a CHANGELOG note under Changed: these fields may now be a tuple; consumers should read the always-a-tuple `ToolDecl.emits_types`.
- sdkCandidate: true
