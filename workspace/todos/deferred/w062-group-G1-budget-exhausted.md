# w062 — group G1 — redteam budget exhausted

- Wave: w062
- Scope: unit:G1
- Date: 2026-10-23
- Rounds run: 5
- Status: DEFERRED — budget exhausted with open findings

**Instruction: Fix remaining findings, then re-run /wave w062**

## Open findings

### RT-001 (high) — tests/test_gh205_mcp_skills.py:243
Quote: `    assert MARKER not in caplog.text`
- Description: [SDK] The SI-2 no-log-leak assertions for prompts/get and tools/call load_skill (lines 243 and 253) pass without checking anything when the file runs alone, or when it is the first test to build an app. build_app() calls configure_logging(), which sets propagate=False on the agent_sdk logger after the autouse conftest fixture has already switched it back on, so root caplog never sees agent_sdk.routes.mcp records. Probe: in the same setup, logging.getLogger('agent_sdk.routes.mcp').warning('leak %s', MARKER) left MARKER out of caplog.text (CAPTURED: False). This is the LRN-106 failure mode.
- Fix: Use the conftest `sdk_caplog` fixture, which attaches a handler straight to the agent_sdk logger, or set logging.getLogger('agent_sdk').propagate = True after build_app() and restore it afterwards. Then add a self-check that a known agent_sdk.routes.mcp log line is captured, so the test can never be empty.
- Codify: A caplog no-leak assertion must capture from the agent_sdk logger after build_app() runs, because configure_logging() turns propagation off on first build and makes root caplog read empty in isolation.
- sdkCandidate: true

### RT-002 (medium) — agent_sdk/common/schema.py:91
Quote: `                    if _nullable_inner(pval) is not None:`
- Description: [SDK] In strict mode, a nullable property reached through a $ref is not seen as nullable. Example: a pydantic TypeAliasType such as MaybeInt = TypeAliasType('MaybeInt', Optional[int]) emits {'$ref': '#/$defs/MaybeInt'}. _nullable_inner() runs on the raw property before the $ref is resolved, so the field stays in `required` and is then collapsed to {'type': 'integer'}. Probe: for `class O(BaseModel): b: MaybeInt`, the strict outputSchema is required:['b'], but O(b=None) dumped with exclude_none gives {}, and jsonschema reports "'b' is a required property". structuredContent then fails its own advertised outputSchema.
- Fix: Decide nullability on the resolved node. Walk or inline the property's $ref chain first (with the same recursion guard), then run _nullable_inner and the required/keep_null logic on the inlined schema. Add a TypeAliasType Optional regression test that validates structuredContent against the strict outputSchema.
- Codify: Strict-schema rewrites that change `required` must decide nullability after $ref inlining, not on the raw property, or aliased Optional fields break the output contract.
- sdkCandidate: true

### RT-003 (medium) — agent_sdk/common/schema.py:108
Quote: `                out[key] = value`
- Description: [SDK] Strict mode deletes every $defs entry but copies unknown keywords through unchanged. A pydantic discriminated union (Annotated[Union[A, B], Field(discriminator='kind')]) keeps `discriminator.mapping: {'a': '#/$defs/A', 'b': '#/$defs/B'}` in strict output, and those references now point at nothing. Probe output: {"discriminator": {"mapping": {"a": "#/$defs/A", ...}}, "oneOf": [...inlined...]}. This breaks the AC 'strict output has no $ref/$defs' in spirit. Copilot Studio (the target client, per the GH-206 evidence comment) reads OpenAPI-style schemas, where discriminator.mapping is meaningful.
- Fix: In strict mode, drop `discriminator.mapping`, or the whole `discriminator` keyword, once its targets are inlined. Keep `propertyName` only if no mapping is left. Add a discriminated-union test asserting that no '#/$defs/' string remains anywhere in the strict schema, except the kept recursive $defs.
- Codify: When inlining $defs, scan for every reference to '#/$defs/', including OpenAPI `discriminator.mapping` strings, not only `$ref` keys.
- sdkCandidate: true

### RT-004 (medium) — agent_sdk/common/schema.py:97
Quote: `                        keep = not self.keep_required and pname in required_names and "default" not in pval`
- Description: [SDK] The implementation differs from the GH-206 maintainer ruling with no recorded ratification. The ruling (issuecomment-6359827730) says to turn anyOf[X, null] into X 'and drop it from required' for inputSchema and outputSchema. The code keeps required-nullable fields required in inputSchema (keep_required=True from _tool_schema is_input) and emits `type: [X, "null"]` or a kept anyOf-null for required-nullable output fields with no default. Both are reasonable engineering calls, but neither is approved on the issue. CHANGELOG.md also contradicts itself ('the field leaves required' ... 'in inputSchema a required-nullable field stays required').
- Fix: Post the deviation (input keeps required; output keeps null for a required field with no default) on GH-206 and get the maintainer to ratify it before archiving, or implement the ruling literally. Reword the CHANGELOG GH-206 entry so it does not first state the opposite of what the code does.
- Codify: A wave that departs from a maintainer ruling, even to stay correct, must record the deviation on the issue for ratification and must not describe the ruling's wording as shipped behaviour.
- sdkCandidate: true

### RT-005 (low) — docs/protocols.md:135
- Description: [SDK] The strict-mode bullet says the output has 'no `anyOf` with null'. In fact list items and dict values keep anyOf-null by design (list[Optional[str]] gives items.anyOf [string, null]), and a required-nullable output field whose X has no single type (enum/const) keeps its anyOf. docs/deployment.md states this correctly, so the two docs disagree.
- Fix: Align docs/protocols.md with docs/deployment.md: anyOf-null collapses only at property positions; list items, dict values, and required-nullable enum/const output fields keep null.
- sdkCandidate: true

### RT-006 (low) — agent_sdk/routes/mcp.py:593
Quote: `    catalog = "; ".join(f"{s.name}: {s.description}" for s in skills)`
- Description: [SDK] The load_skill tool description joins every catalog skill with no length limit. mcp_description is capped at 2048 characters (_MAX_DESCRIPTION_LEN), but this built-in tool description grows without bound with skill count and can exceed client tool-description limits.
- Fix: Cap the joined catalog text (reuse _MAX_DESCRIPTION_LEN, end with an ellipsis or a 'see prompts' note), or fail at boot when mcp_skills='tool' and the description would pass the cap.
- sdkCandidate: true

### RT-007 (low) — agent_sdk/routes/mcp.py:576
Quote: `_LOAD_SKILL = "load_skill"`
- Description: [SDK] The reserved name is now defined three times: loop.py LOAD_SKILL_TOOL, mcp.py _LOAD_SKILL, and the literal "load_skill" in the app.py reserved-name check. mcp.py already imports from ..agent.loop. If the names drift, the MCP tool, the loop tool and the boot guard would disagree.
- Fix: Import LOAD_SKILL_TOOL from agent_sdk.agent.loop in routes/mcp.py and app.py, and delete the local constant and the literal.
- sdkCandidate: true

### RT-008 (low) — agent_sdk/agent/registry.py:515
Quote: `            if not mcp_description.strip():`
- Description: [SDK] The mcp_description check assumes a str. A non-str value (for example mcp_description=123) raises AttributeError instead of the documented ValueError at registration.
- Fix: Add `if not isinstance(mcp_description, str): raise ValueError("mcp_description must be a string")` before the strip and length checks, and extend the bad-value parametrize in tests/test_gh207_mcp_description.py.
- sdkCandidate: true

### RT-009 (low) — agent_sdk/app.py:117
Quote: `        mcp_skills: str | None = None,`
- Description: [SDK] The new public parameter is typed as plain `str | None`, so type checkers accept invalid values such as 'both' that fail only at build_app(). The valid set is closed (None/'tool'/'prompts').
- Fix: Type it as `Literal["tool", "prompts"] | None` and keep the runtime check for untyped callers.
- sdkCandidate: true

### RT-010 (low) — tests/test_gh207_mcp_description.py:61
Quote: `    assert entry.description == "Docstring description."`
- Description: [SDK] The GH-207 AC says 'the agent loop keeps the docstring', but the test checks the registry field entry.description, not the tool spec the loop sends to the model (loop.py tool_specs). A later change that makes the loop prefer decl.mcp_description would not be caught.
- Fix: Drive one loop turn with FakeModelClient and assert that the tool spec given to the model for gh207_tool_x has description 'Docstring description.', not the MCP override.
- sdkCandidate: true

> Resolved 2026-10-24: RT-001 fixed in the phase redteam; RT-002, RT-003, RT-004 (ratified on GH-206), RT-005, RT-006, RT-007, RT-008, RT-009 fixed. RT-010 stays open as a low.
