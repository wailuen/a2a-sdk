# w061 — phase — deferred medium/low findings

- Wave: w061
- Scope: phase
- Date: 2026-10-23

Non-blocking — these did not block w061's archive. Address opportunistically or fold into a future wave.

## RT-001 (medium) — agent_sdk/routes/mcp.py:823
Quote: `not isinstance(entry.decl.emits, tuple)`
- Issue: A tuple-emits tool returning a BaseModel matching no declared member gets isError:false with no structuredContent, though tools/list advertised an anyOf outputSchema. MCP 2025-06-18 requires conforming structuredContent when outputSchema is declared. Also differs from the raw-dict path, which returns isError 'tool output coercion failed'.
- Fix: In _handle_tools_call, when entry.decl.emits_types is non-empty, artifact is a BaseModel and match_emits(artifact) is None, try coercing artifact.model_dump(mode='json') through the member loop or return isError 'tool output coercion failed' (log only tool name + type name, SI-2). Add a test in tests/test_gh225_multi_type_emits.py for a non-member pydantic model over MCP.
- Codify: Every path that advertises an MCP outputSchema must return conforming structuredContent or isError; never a silent success without structuredContent, including tuple emits.

## RT-002 (medium) — pyproject.toml:36
Quote: `"jsonschema>=4.20",`
- Issue: pyproject.toml (new jsonschema dev dep) and uv.lock (~160 lines) changed but are on no todo's Creates:/Modifies: line in workspace/todos/active/w061-gh-issues.md. The archive-commit gate can miss them (LRN-322).
- Fix: Add `pyproject.toml` and `uv.lock` to GH-225's Creates: (modifies ...) clause so wave.allScope, the commit check and the pre-archive rescan cover them.
- Codify: A new test dependency is a scope change: pyproject.toml and uv.lock must be declared on the todo's Creates:/Modifies: line, not only named in CHANGELOG.

## RT-003 (low) — agent_sdk/agent/loop.py:1841
Quote: `data_type=getattr(matched, "data_type", entry.name),`
- Issue: Ruling says label with the result's own data_type; code uses the matched member's (same in runner.py deferred path). A registered subclass (e.g. CustomKpi(KpiCard)) is labelled 'kpi_card' while the translator renders the subclass component.
- Fix: For tuple tools, label with getattr(type(result), 'data_type', matched.data_type) in loop.py and runner.py; keep member label for single-type tools. Add a subclass test.
- Codify: When a ruling says to label by the result's own type, use type(result), not the declared member matched by isinstance.

## RT-004 (low) — agent_sdk/agent/registry.py:477
Quote: `return (emits,)`
- Issue: normalize_emits wraps any non-tuple without checking, so emits=[A, B] or a non-class passes decoration and crashes at boot with a bare TypeError from issubclass() in _validate_emits, not the ValueError the GH-225 AC requires.
- Fix: Raise ValueError('emits must be a class or a tuple of classes') when a non-tuple value is not a type (lists included); add a decoration test for emits=[A, B].
- Codify: Normalization helpers for public decorator arguments should reject every malformed shape with a clear ValueError.

## RT-005 (low) — agent_sdk/agent/runner.py:393
Quote: `text = payload.to_plain_text() if isinstance(payload, ContentModel) else str(payload)`
- Issue: Deferred text-only artifact renders dict/BaseModel with Python repr and None as 'None'; MCP folds None to '' and models to JSON.
- Fix: Render like _tool_text / fold_result_content: '' for None, model_dump_json(exclude_none=True) for BaseModel, JSON for dict/list with str() fallback.

## RT-006 (low) — harness/workflows/wave-cycle.js:1309
Quote: `log('final scope re-scan returned no trustworthy result — archive BLOCKED (scan:scope:' + name + ')')`
- Issue: A failed final re-scan sets only protocolBlocked, so the cause summary hits the generic branch pointing at /agent-verify. A per-round unowned path logs 'wave BLOCKED' (line 1284) but only marks the round unknown; after maxRounds the summary blames redteam null verdicts. Same in .claude/workflows/sdk-wave.js:1304 and .claude/template copies.
- Fix: Add a scopeRescanBlocked flag, set in finalScopeRescan and the unowned/mismatch branches of rescanScope, with its own cause line in the `if (protocolBlocked)` summary (e.g. 'Archive SKIPPED — scope re-scan untrustworthy or a declared path has no owning todo; fix the wave file'). Apply to all four runner copies.

## RT-007 (low) — docs/tools.md:141
Quote: `- No empty tuple, no duplicates, every member a registered content type`
- Issue: _validate_emits also accepts plain pydantic BaseModel members (tests/test_gh225_multi_type_emits.py::_raw_toolset uses emits=(PA, PB)); docs disagree with code.
- Fix: Say every member must be a pydantic BaseModel, and a ContentModel member must be registered and inside a2ui_allowed_components.

## RT-008 (low) — harness/workflows/wave-cycle.js:1254
Quote: `async function rescanScope(base, round, group, phaseName) {`
- Issue: `group` is unused but both callers pass it and finalScopeRescan passes null, implying the calling group decides the owner (the bug GH-228 fixed). Same in .claude/workflows/sdk-wave.js:1249.
- Fix: Remove `group` from rescanScope and its three call sites in all four runner copies, keeping them byte-identical.
