# w060 — group G1 — tests RED (round 1)

- Wave: w060
- Scope: unit:G1
- Date: 2026-10-23
- Round: 1
- Reason: test suite RED after the fix attempt; blocking findings below remain unresolved.

## Blocking findings

### RT-001 (high) — docs/tools.md:64
Quote: `model_config = {"json_schema_extra": {"anyOf": [{"required": ["a"]}, {"required": ["b"]}]}}`

The new "ID A or ID B" recipe puts `anyOf` at the top level of the tool input schema. That schema reaches the model unchanged (loop.py:1296 -> bedrock.py:316 `inputSchema.json`, openai_client.py:292 `parameters`) and MCP clients via tools/list. Anthropic's tool API rejects top-level oneOf/allOf/anyOf in `input_schema` (400). Following the doc can break every Claude-on-Bedrock turn and the whole tool list in Claude.ai / Claude Code connectors. tests/test_gh221_tools_list_titles.py::test_any_of_required_reaches_tools_list pins the unsafe shape. The ruling assumed it "already passes through" without checking provider limits.

Fix: escalate to the maintainer before release (changes the ruled doc). Meanwhile rewrite the section: warn that top-level anyOf/oneOf/allOf is rejected by Anthropic models (Bedrock) and Claude MCP clients; recommend both fields optional, the "one of a or b" rule in field descriptions, and an in-tool check (or pydantic model_validator) returning a clear error. Optionally have C-056 `_check_list` and boot validation flag a top-level combinator in any tier-1 inputSchema.

Codify: before documenting a JSON Schema pattern for tool inputs, check it against every model provider and MCP client the SDK targets; the shared input_schema reaches all of them unchanged.

sdkCandidate: true

### RT-002 (high) — agent_sdk/agent/registry.py:770
Quote: `This method backs MCP's tools/list outputSchema only (the agent card`

LRN-413/LRN-443 check fails: registry.py was changed in this group (output_schema() docstring rewritten for GH-219) but is in no G1 Creates/Modifies line (only GH-221 Reads), and is missing from the `[Unreleased]` CHANGELOG.

Fix: add `agent_sdk/agent/registry.py` (output_schema docstring) to the GH-219 todo's Creates/Modifies line and to the GH-219 CHANGELOG bullet's `Changed:` list.

Codify: a docstring edit to a Reads-only file is still a modified production file; list it in the todo scope and the per-GH CHANGELOG Changed list.

sdkCandidate: true

## Instruction
Fix failing tests and remaining findings, then re-run /wave w060.

## Shared working tree rule
Other agents have uncommitted work in this tree. NEVER run `git stash`, `git reset`, `git checkout -- <path>`, `git restore`, `git clean` or `git checkout .`. Edit files in place. Use `git show` / `git diff` to inspect old content.
