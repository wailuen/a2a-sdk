# w062 — unit:G1 — deferred medium/low findings

- Wave: w062
- Scope: unit:G1
- Date: 2026-10-23

Non-blocking — these did not block w062's archive. Address opportunistically or fold into a future wave.

Findings are deduped by file + description across all redteam rounds. Round IDs repeat across rounds, so each item lists every source ID it merges. All items are `sdkCandidate: true`.

## agent_sdk/common/schema.py (GH-206 strict mode)

### S1 [medium] Required Optional field without default dropped from `required` (RT-005 r1)
- Line 96: `if collapsed and isinstance(out.get("required"), list):`
- Strict mode drops `x: Optional[int]` (no default) from `required`, but pydantic still rejects omitting it. The advertised inputSchema accepts calls the server refuses.
- Fix: only drop a collapsed property from `required` when the source node had a default. Test `Optional[int]` with no default.
- Codify: a strict-client schema rewrite must never advertise as optional a field the validator still requires.

### S2 [medium] anyOf-null collapsed inside items/additionalProperties (RT-006 r1)
- Line 102: `inner = _nullable_inner(out)`
- `list[Optional[str]]` / `dict[str, Optional[int]]` output emits None values that fail the strict outputSchema (exclude_none only strips model fields).
- Fix: collapse only directly under `properties`; keep nullable anyOf for items, additionalProperties, prefixItems. jsonschema test with `list[Optional[str]]` output.
- Codify: collapsing nullability in outputSchema is only sound where serialization drops the None.
- Note: a later round (RT-003/RT-005 docs items) says the code already keeps null on items/values; verify before fixing.

### S3 [medium] discriminator.mapping left pointing at removed `$defs` (RT-007 r1, RT-003 r4)
- Lines 77 / 108.
- `Annotated[Union[A,B], Field(discriminator='kind')]` ships `mapping: {'a': '#/$defs/A'}` with no `$defs`. Copilot Studio reads OpenAPI-style discriminator.
- Fix: in strict mode drop `discriminator` (or its `mapping`) once targets are inlined, or keep referenced `$defs`. Test asserts no `#/$defs/` string remains except kept recursive defs.
- Codify: when inlining `$defs`, rewrite or remove every string pointer into `$defs`, not only `$ref` keys.

### S4 [medium] Nullability decided before `$ref` resolution (RT-002 r4)
- Line 91: `if _nullable_inner(pval) is not None:`
- `MaybeInt = TypeAliasType('MaybeInt', Optional[int])` stays required and collapses to `integer`; `O(b=None)` dumps `{}` and fails `'b' is a required property`.
- Fix: resolve/inline the `$ref` chain first (same recursion guard), then apply nullable/required logic. Regression test validating structuredContent.
- Codify: strict rewrites that change `required` must decide nullability after `$ref` inlining.

### S5 [medium] Implementation deviates from GH-206 ruling without ratification (RT-004 r4)
- Line 97: `keep = not self.keep_required and pname in required_names and "default" not in pval`
- Ruling (issuecomment-6359827730) says collapse and drop from `required` for input and output. Code keeps input required, keeps null for required output fields with no default.
- Fix: post the deviation on GH-206 for maintainer ratification, or implement the ruling literally. Fix the self-contradicting CHANGELOG entry.
- Codify: a wave that departs from a maintainer ruling must record the deviation on the issue for ratification.

### S6 [low] Multi-member `Optional[Union[A, B]]` keeps `{type: null}` (RT-005[SDK], RT-010 r1)
- Line 43: `if not isinstance(options, list) or len(options) != 2:`
- Strict output still holds anyOf-with-null, the shape strict clients reject. No fixture covers it.
- Fix: remove the null member from anyOf with >2 members; apply the same `required` rule as S1. Add fixture `u: Optional[Union[int, str]] = None`. Or narrow the docs (see D1).

## agent_sdk/routes/mcp.py (GH-205 load_skill / prompts)

### M1 [medium] load_skill omits openWorldHint (RT-008 r1)
- Line 605: `"annotations": {"readOnlyHint": True},`
- Spec default openWorldHint is true; contradicts LRN-043.
- Fix: `{"readOnlyHint": True, "openWorldHint": False}`; assert in `tests/test_gh205_mcp_skills.py::test_tool_mode_lists_and_calls`.
- Codify: every tool the SDK lists on MCP must state openWorldHint explicitly.

### M2 [low] tools/call load_skill served when unlisted; argument checks missing (RT-011 r1, RT-004[SDK], RT-005 r3)
- Line 716: `if name == _LOAD_SKILL and _skills_mode(app) == "tool":`
- With an empty catalog, tools/list omits load_skill (line 647) but tools/call returns isError "skill not found" instead of -32602 "tool not found". Extra keys and non-string/missing `name` are accepted despite `additionalProperties: false` (GH-196 rejects unknown args elsewhere).
- Fix: serve only when `_mcp_skills(app)` is non-empty, else `__jrpc_unknown_tool__` path. Reject non-dict, missing/non-string `name`, or extra keys with the registry tools' argument-error shape.

### M3 [low] load_skill description has no length cap (RT-008[SDK], RT-005 r2, RT-006 r4)
- Lines 593/596: `catalog = "; ".join(f"{s.name}: {s.description}" for s in skills)`
- Unbounded size; mcp_description is capped at 2048 (`_MAX_DESCRIPTION_LEN`). Affects acceptance size_budget and client limits.
- Fix: cap each description (e.g. sanitize_text(max_len=200)) and the joined text at `_MAX_DESCRIPTION_LEN` with an "...and N more" marker, or fail at boot. Add a test.

### M4 [low] Module docstring out of date (RT-009[SDK], RT-004 r2)
- Line 44: `Methods: ``initialize`` ...`
- Missing prompts/list, prompts/get (-32601 unless `mcp_skills="prompts"`), conditional `capabilities.prompts`, load_skill built-in, `AGENT_SDK_MCP_SCHEMA_MODE=strict`. `_handle_tools_list` docstring (line 638) still says "Tier 1 only (§5.6)".
- Fix: update both docstrings.

### M5 [low] Reserved name `load_skill` defined three times (RT-013 r1, RT-007 r4; part of RT-007 r2)
- Line 576: `_LOAD_SKILL = "load_skill"`; also literal in app.py:665 and `agent/loop.py` LOAD_SKILL_TOOL.
- Fix: import `LOAD_SKILL_TOOL` from `agent_sdk.agent.loop` in mcp.py and app.py; delete the copies.

## agent_sdk/testing/mcp.py + acceptance skill

### T1 [medium] run_gate count fails with `mcp_skills="tool"` (RT-009 r1, RT-003[SDK], RT-002 r2)
- Line 174: `out.append(f"tools/list count {len(tools)} != registered tier-1 tools {expected_count}")`
- tools/list holds N+1 (load_skill). `harness/skills/acceptance/SKILL.md:200` and `.claude/skills/acceptance/SKILL.md:200` say `--expected-count <N tier-1 tools>`, so the C-056 gate fails on every such agent.
- Fix: exclude built-in `load_skill` from the count in `_check_list`/run_gate (or document N+1 in docs/testing.md and both SKILL.md copies). Add a run_gate test against an `mcp_skills="tool"` app with `expected_count=len(registry.tier1())`.
- Codify: adding a non-registry tool to tools/list must update every count-based consumer in the same change.

## agent_sdk/agent/registry.py (GH-207 mcp_description)

### R1 [low] mcp_description not type-checked, not stripped, allowed on tier 2 (RT-014 r1, RT-006[SDK], RT-006 r2, RT-004 r3, RT-008 r4)
- Lines 514-515: `if not mcp_description.strip():`
- Non-str raises AttributeError, not the documented ValueError. Value is sent unstripped (docstring path strips). Tier-2 value silently ignored. docs/tools.md:111 says "at boot" but the check runs at decoration time.
- Fix: `isinstance(..., str)` check raising ValueError; store `.strip()`; reject when tier == 2; fix docs/tools.md wording. Extend the bad-value parametrize in `tests/test_gh207_mcp_description.py`.

## agent_sdk/app.py

### A1 [low] `mcp_skills` typed `str | None`; validated late; strict flatten uncached (RT-015 r1, RT-007[SDK], RT-007 r2, RT-006 r3, RT-009 r4)
- Line 117: `mcp_skills: str | None = None,`
- Type checkers miss typos. Validation (line 661) runs after `_build_credential_store()`, leaving the store open on failed boot. Strict flatten runs on every tools/list request and re-inlines each `$ref` per use.
- Fix: `Literal["tool", "prompts"] | None`, keep runtime check; validate in `Agent.__init__` or before credential-store construction; cache flattened schemas on ToolEntry or app state at build.

## agent_sdk/agent/skills.py

### K1 [low] `listed()` duplicates `catalog_text()` filter (RT-010[SDK], part of RT-013 r1)
- Line 84: `return [s for s in self.skills.values() if s.name not in excluded]`
- Fix: `catalog_text()` builds from `self.listed(exclude)`.

## Docs / CHANGELOG

### D1 [medium/low] Strict-mode docs disagree with code and each other (RT-010 r1, RT-003 r2 [medium], RT-003 r3, RT-005 r4)
- `docs/protocols.md:135` promises "no anyOf with null". `CHANGELOG.md:16` says the collapsed field "leaves `required`". In code: list items/dict values keep anyOf-null, inputSchema keeps required (keep_required=True), required-nullable output fields with no default (or enum/const X) keep null, and multi-member unions keep null (S6). `docs/deployment.md:110` is the most accurate.
- Fix: align protocols.md and the GH-206 CHANGELOG [Unreleased] entry with deployment.md and the final behaviour after S1/S2/S4/S5/S6.

## Tests

### X1 [medium] Built-in sweep test filters out the error it should catch (RT-002 r3)
- `tests/test_rt001_strict_required_nullable_output.py:62`: `if err.validator in ("required", "type") and "null" in str(err.message):`
- Missing-required errors have no "null" in the message; models whose `model_construct()`/`wire()` raise are skipped; only TimeSeriesDataPoint (custom serializer) is covered.
- Fix: fail on any `required`/`type` error; add a ContentModel with required `X | None` and no custom serializer, checked via real MCP tools/call.
- Codify: a schema-conformance test must not filter validator errors by message text.

### X2 [low] GH-205 tests too weak (RT-012 r1)
- `tests/test_gh205_mcp_skills.py:131`: `with pytest.raises(McpError):`
- Default-mode prompts/* not asserted -32601; excluded prompts/get not asserted -32602; probes `skill1x`, not exact `skill1`; no SI-5 cross-identity / unauthenticated test for tools/call load_skill.
- Fix: use `_raw()` and assert codes; add cross-identity session test.

### X3 [low] GH-207 loop-keeps-docstring AC not tested end to end (RT-010 r4)
- `tests/test_gh207_mcp_description.py:61`: `assert entry.description == "Docstring description."`
- Checks the registry field, not the spec the loop sends to the model.
- Fix: drive one loop turn with FakeModelClient and assert the tool spec description for `gh207_tool_x` is the docstring.
