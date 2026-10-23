# w060 — group G1 deferred medium/low findings

- wave: w060
- scope: unit:G1
- date: 2026-10-23

Non-blocking — these did not block w060's archive. Address opportunistically or fold into a future wave.

## RT-003 (medium) — agent_sdk/routes/mcp.py:574
- quote: `if key == "title" and isinstance(value, str):`
- description: `_strip_titles` removes every string `title` keyword, including titles the author set on purpose (`Field(title='Ticker symbol (e.g. AAPL)')` and `model_config['title']`; verified, both disappear from tools/list). The ruling, the AC, the function docstring, docs/tools.md:71-72 and the GH-221 CHANGELOG bullet all say only pydantic's AUTO-GENERATED titles are removed. MCP clients that show a form label from `title` lose the author's text without warning.
- fix: Either drop only the titles pydantic generates (a property title equal to `name.replace('_', ' ').title()` and a model/$defs title equal to the class or def name) and keep the rest, with a test for an explicit `Field(title=...)` surviving. Or keep the blanket strip and fix the docstring, docs/tools.md, the CHANGELOG bullet and DESIGN.md §5.5 to say every `title` keyword is dropped on tools/list, telling authors to put user-facing text in `description`.
- sdkCandidate: true

## RT-004 (medium) — tests/test_gh219_card_remainders.py:61
- quote: `async def test_card_bytes_no_longer_carry_output_schemas(client):`
- description: The GH-219 AC requires a test that the example agent's card byte size shrank. This test never compares a before size with an after size. It computes `dropped` from `registry.all()` (which includes Tier 2 tools that are not on the card), asserts `dropped > 0` and `card_bytes > 0`, and repeats the substring check. It would still pass if the card grew. The AC is not met.
- fix: Build the old card size from the same card with each tier-1 skill's `x-sdk.outputSchema` put back from `entry.output_schema()` (plus the MarketBriefing wire note where it applies). Assert `len(current_card_bytes) < len(reconstructed_old_bytes)`, iterate `registry.tier1()` only, and drop the trivial `card_bytes > 0` assertion.
- sdkCandidate: true

## RT-005 (medium) — workspace/todos/deferred/w050-group-G4-medium-low.md:15
- quote: `- status: card half closed by GH-219 (the agent card no longer carries `x-sdk.outputSchema`, so it cannot drift); the MCP `tools/list` outputSchema half stays open.`
- description: The 'card half closed' status line is under RT-001, which is about DocumentItem's model-wide `@model_serializer` in content_types.py and has nothing to do with card outputSchema. The card/MCP outputSchema drift item is RT-002 (registry.py, 'both MCP tools/list outputSchema and the agent card x-sdk.outputSchema'). The AC said to touch RT-001 only if it is about card outputSchema drift, and it is not. RT-001 now looks partly closed when nothing about it changed, and RT-002 still claims the card carries outputSchema.
- fix: Move the status line from RT-001 to RT-002, the item that is about card outputSchema drift, and leave RT-001 unchanged.
- sdkCandidate: true

## RT-006 (low) — tests/test_gh221_tools_list_titles.py:35
- quote: `return len(json.dumps(tools, separators=(",", ":")).encode())`
- description: The todo's Reuses C-056 note says 'Do not write a second size measurer'. The test copies `_check_list`'s size formula into its own `_size` helper, so a change to the gate's measure would not be reflected here. The 'before' figure also comes from rebuilt registry dicts that leave out `title` and `annotations`, so it is not the real pre-change tools/list payload.
- fix: Measure through C-056: call `_check_list(tools, None, size_budget=N)` and read the size from its failure text, or factor a public `tools_list_size(tools)` helper out of `_check_list` in agent_sdk/testing/mcp.py and use it on both sides. Build 'before' by applying the real `_handle_tools_list` output minus stripping (for example, by patching `_strip_titles` to identity).
- sdkCandidate: true

## RT-007 (low) — docs/tools.md:181
- quote: `@tools.tool(tier=1)`
- description: The GH-219 AC says the `@tools.tool` examples in docs/tools.md show `tags=`. Only the first example (line 11) was updated. The Reusable example at line 181 still has no tags. The new test only checks the text before 'Rules the decorator enforces', so it misses this.
- fix: Add `tags=[...]` to the line-181 example, or change the test to check every `@tools.tool(` example in docs/tools.md.
- sdkCandidate: true

## RT-008 (low) — docs/protocols.md:161
- quote: `` `x-sdk` per-skill metadata (tier, schemas, emits), and the `x-agui` block ``
- description: After GH-219 the card's `x-sdk` carries only `inputSchema` (no `outputSchema`), but the protocol doc still says 'schemas' in the plural, implying both are there.
- fix: Change to '(tier, inputSchema, emits)' and note that outputSchema is only on MCP tools/list (GH-219).
- sdkCandidate: true

## RT-009 (low) — tests/test_gh219_card_remainders.py:49
- quote: `assert card["description"]`
- description: `test_blank_description_still_falls_back_to_display_name` only checks that the description is non-empty. It does not check that it equals the display name, and it does not confirm that the `client` fixture's AGENT_DESCRIPTION is blank. So it does not pin the fallback the ruling says must stay.
- fix: Build the app with `AGENT_DESCRIPTION='   '` (as `_build` does) and assert `card['description'] == settings.display_name`.
- sdkCandidate: true
