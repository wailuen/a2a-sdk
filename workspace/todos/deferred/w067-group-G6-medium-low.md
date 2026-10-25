# w067 — group G6 — deferred medium/low findings

- Wave: w067
- Scope: unit:G6
- Date: 2026-10-25

Non-blocking — these did not block w067's archive. Address opportunistically or fold into a future wave.

Findings were collected across every redteam round. Repeats of the same file and issue are merged into one entry.

## Medium

### D-1 — tests/test_gh235_nested_json_and_resume.py:340 (sdkCandidate)
- Quote: `'{"message":{"role":"user","messageId":"m1","parts":[{"text":"hi"}],"metadata":'`
- Issue: The GH-267 AC says the deep-metadata test sends an "otherwise valid" message. It does not. The part has no `kind`. With shallow metadata the same body gets 400 `-32602 invalid message params (check: message.parts.0)` (live probe). So the main check (`GET /v1/tasks != 500`) can never fail for the right reason. CHANGELOG.md:28 (GH-267) wrongly says the message is otherwise valid.
- Fix: Use `'{"message":{"role":"user","messageId":"m1","kind":"message","parts":[{"kind":"text","text":"hi"}],"metadata":'`. Add a control case: same body with shallow metadata (e.g. `{"a":1}`) is accepted (200), proving only the nesting causes the refusal.
- Codify: An ingress test that claims an "otherwise valid" body needs a control request proving that body is accepted without the defect.

### D-2 — agent_sdk/example/agent.py:80 (sdkCandidate)
- Quote: `status = payload.get("decision") or payload.get("status")`
- Issue: GH-267 item 8 named :80 and :92; only the :92 schema changed. The resume handler still treats `payload.status` as a decision. `{"status":"resolved","payload":{"status":"approved"}}` on AG-UI, or a DataPart resume `{"status":None,"payload":{"status":"approved"}}` on A2A, publishes the note. This is the nested-status injection `parse_decision` says it NEVER reads, pinned as UNCLEAR by tests/test_contrib_action_gate.py:74 and tests/test_gh193_data_part_resume.py:204. The CHANGELOG says the example now teaches `payload.decision`.
- Fix: Drop the `or payload.get("status")` fallback (no test depends on it), or use `agent_sdk.contrib.action_gate.parse_decision(value)` and approve only on `Outcome.APPROVED`. Add a test that `payload.status="approved"` does not publish.
- Codify: Example resume handlers must follow contrib.action_gate decision-field rules; when a response schema field is renamed, the handler must drop the old field too.

### D-3 — tests/test_gh251_ingress.py:219 (sdkCandidate)
- Quote: `raw = b'{"src":' + b"[" * 100 + b"1" + b"]" * 100 + b"}"`
- Issue: `test_header_too_deep_fails_closed` cannot fail. The `src` value is a list, so `parse_header`'s shape check (`not isinstance(fields, dict)`) returns `{}` whether or not `loads_strict` refuses the depth. Probe with `json_strict._check_depth` patched to a no-op still passes. SI-6 AC asks for coverage of the NestingTooDeep path. Its log check looks only for the key `src`, not a value.
- Fix: Spy on `forwarding.loads_strict` and assert it raised NestingTooDeep, or nest the depth inside a value that passes the shape check. Put a unique marker value in the header and assert it is absent from `caplog.text`.
- Codify: A fail-closed test must prove the targeted branch fired when a later check returns the same fail-closed value.

### D-4 — workspace/components/README.md:78 (sdkCandidate)
- Quote: `| C-085 | scrub_non_finite | agent_sdk/common/json_strict.py (beside scrub_unencodable, C-040) | present |`
- Issue: No symbol `scrub_non_finite` exists in agent_sdk/ or git history. A future `Reuses: C-085` points at nothing.
- Fix: Set C-085 to planned (or remove it) with a description. If it is meant to be scrub_unencodable, mark it duplicate-of-C-040 like C-013.
- Codify: Registry rows marked present must name a symbol grep can find; check neighbouring rows when a wave edits a component's module.

## Low

### D-5 — workspace/components/README.md:72 (C-079 row) (sdkCandidate)
- Quote: `MCP Content-Type compare GH-246; the JSON Content-Type checks use C-087, not this;`
- Issue: The row contradicts itself and the code. The MCP compare is a JSON Content-Type check (routes/mcp.py:1116 calls `is_json_content_type`); routes/mcp.py no longer imports media.py; C-087 is itself built on `normalize_media_type` (common/body.py:13/:41), so "not this" is wrong too.
- Fix: Replace both clauses with: "C-087 `is_json_content_type` (the JSON Content-Type check on MCP, A2A and AG-UI) is built on `normalize_media_type`; no route compares Content-Type with it directly."

### D-6 — workspace/components/README.md:260 (C-040 detail) (sdkCandidate)
- Quote: `` `loads_strict(raw, *, reject_duplicate_keys=False)` is the ingress pair; `reject_duplicate_keys=True` raises ... (GH-267, SI-2) (rejects NaN/Infinity tokens ``
- Issue: The duplicate-key clause was inserted before the existing parenthetical, so "(rejects NaN/Infinity tokens and unencodable strings; ... 64 levels ...)" now reads as describing `reject_duplicate_keys`, not `loads_strict`.
- Fix: Restore "is the ingress pair (rejects NaN/Infinity ...)" as one unit, then a separate sentence: "With reject_duplicate_keys=True it also raises json.JSONDecodeError("duplicate key") for a repeated key at any depth, never naming the key or a value (GH-267, SI-2)."

### D-7 — workspace/components/README.md:10 (C-006 row) (sdkCandidate)
- Quote: `GH-261 makes it keyword-only, default False`
- Issue: Both `_capabilities` functions were already keyword-only at HEAD (`*, a2ui_enabled: bool = True` at a2a.py:429-430, ag_ui.py:538). GH-261 only changed the default. The row also omits the GH-261 runner build sites that call `A2uiCapabilities.gated(False, None)`.
- Fix: "keyword-only since GH-257; GH-261 changes the default to False and adds the per-artifact gated(False, None) fallback in agent/runner.py".

### D-8 — agent_sdk/contrib/action_gate/gate.py:126 (sdkCandidate)
- Quote: `- **A2A** → the resume value is a plain string (the user's message text;`
- Issue: The bullet opens by saying the value "is a plain string", then says a DataPart resume arrives as a dict — it contradicts itself (the stale claim item 6 asked to fix). It also says other part kinds are refused, but a text+data mix is refused too (a2a.py:426-427).
- Fix: "**A2A** → a text resume is the message text (str); exactly one DataPart and nothing else arrives as {"status": None, "payload": data}; any other mix is refused by the route." Then the exact-match rule for strings.

### D-9 — tests/test_gh251_ingress.py:188 (sdkCandidate)
- Quote: `def test_loads_strict_duplicate_keys_option(caplog) -> None:`
- Issue: `caplog` is requested but never used. The test never pins the fixed text `duplicate key` promised by the docstring, registry and CHANGELOG. SI-6 log checks look only for key names (`api_key`, `src` at :222), never a value; the duplicate-key values `a`/`b` cannot be searched for in logs, so "asserts no header value in captured logs" is not really tested.
- Fix: Drop or use `caplog`. Assert `ei.value.msg == "duplicate key"`. In `test_header_nan_or_duplicate_key_fails_closed` and `test_header_too_deep_fails_closed`, use a distinctive value (e.g. `SECRET-VAL-9x`) and assert it is not in `caplog.text`.

---

Autoloop cycle 3 (2026-10-25): mediums verified at v0.24.0; still-present ones filed as #268–#274 (testing #268, AG-UI/console #269, A2UI #270, A2A #271, auth #272, MCP #273, example/tests/registry #274). P-022 not filed (conflicts with #246 ruling). Lows not filed.
