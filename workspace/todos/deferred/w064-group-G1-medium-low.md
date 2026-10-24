# w064 — group G1 — deferred medium/low findings

- Wave: w064
- Scope: unit:G1
- Date: 2026-10-24

Non-blocking — these did not block w064's archive. Address opportunistically or fold into a future wave.

Findings from every redteam round, deduped by file + description. IDs restart per round, so the round is noted. Merged duplicates are listed together.

## Medium

### D1 (R1 RT-005 + R2 RT-001) — load_skill missing/non-str `name` reported as "unknown argument"
- File: agent_sdk/routes/mcp.py:808 — `bad_keys.append("name")`
- Problem: a missing or non-string `name` goes through `_unknown_argument_error`, so the client sees `tool 'load_skill' input invalid: name — unknown argument (not in the tool's input schema)`. False: `name` is the only declared, required argument. A model will drop it and retry in a loop. tests/test_gh205_mcp_skills.py:326 (`({}, "name")`) locks the wrong text in.
- Fix: validate with a private model (`class _LoadSkillArgs(BaseModel): name: str`, extra='forbid' or combined with `_unknown_argument_error` details for extra keys only); render once via `safe_validation_message` (GH-196 shape, no value echo). Test: `{}` expects `required field is missing`, `{"name": 5}` expects `expected a string`. AC text names `_unknown_argument_error` for all three cases, so record the ruling on the issue.
- Codify: the registry's `unknown argument` error is only for keys not in the schema; a missing or wrongly-typed declared key must use pydantic's `missing` or `*_type` detail.
- sdkCandidate: true

### D2 (R1 RT-002) — GH-235 tests never run the real JSON parser
- File: tests/test_gh235_nested_json_and_resume.py:39 — `if text.startswith("[" * 1000):`
- Problem: autouse fixture swaps json.loads for a shim raising RecursionError. CI (.venv Python 3.14) never raises, so tests prove only the mapping, not the shipped path (real POST /mcp gives -32600; real GET /v1/tasks after deep metadata gives 500).
- Fix: after the depth cap lands, delete the shim and drive the real parser past the cap on every surface. Add a case nested between 255 and 1000 levels.
- sdkCandidate: true

### D3 (R2 RT-002) — SI-2 no-echo tests can never fail
- File: tests/test_gh235_nested_json_and_resume.py:40 — `raise RecursionError(f"maximum recursion depth exceeded {text[-30:]}")`
- Problem: `nested()` puts the marker mid-body, so `text[-30:]` is all `]` (`MARKER in text[-30:]` is False at depth 50000 and 2000). A `str(exc)` leak in `loads_strict` would still pass all five surfaces.
- Fix: put the marker in the shim's exception text; add a direct unit check that `loads_strict` does not pass RecursionError text through.
- Codify: a no-echo test only proves something if the hostile marker is really inside what the code could leak; assert first that the planted text contains it.
- sdkCandidate: true

### D4 (R2 RT-003) — new 64-level ingress cap shipped as a Fix, not a Breaking change
- File: agent_sdk/common/json_strict.py:53 — `_MAX_DEPTH = 64`
- Problem: GH-235 asked only to map RecursionError. The code adds a hard 64-level cap on MCP, A2A, AG-UI, OAuth. Bodies 65 to ~1000 deep used to be accepted. CHANGELOG lists it under `### Fixed`, no Breaking entry, no Migration line. Missing from docs/protocols.md, C-040 row/detail, `loads_strict` docstring. No setting. Same gap class as LRN-472.
- Fix: add a `### 🔴 Breaking changes` bullet under [Unreleased] with `**Migration:**` and a ruling URL, or get a ruling and pick the limit. Document the cap in docs/protocols.md (ingress), the docstring, and C-040.
- Codify: a new ingress limit that rejects previously accepted requests is a wire breaking change even inside a crash fix.
- sdkCandidate: true

### D5 (R2 RT-004) — Graph webhook parses with bare json.loads
- File: agent_sdk/contrib/webhooks/graph.py:106 — `payload = json.loads(raw) if raw else None`
- Problem: unauthenticated ingress; catches only ValueError/UnicodeDecodeError. Deep body gives RecursionError -> HTTP 500 on Python <=3.13 (Graph retry storm risk); on 3.14 the deep payload reaches the dispatcher. Second ingress parser not using C-040.
- Fix: use `loads_strict`; catch `json.JSONDecodeError`, `ValueError`, `UnicodeDecodeError` in the drop-and-202 branch. Add a nested-body webhook test.
- Codify: every request-body JSON parse in agent_sdk, contrib included, must go through C-040 `loads_strict`.
- sdkCandidate: true

## Low

### D6 (R1 RT-007 + R2 RT-009) — boot raises after credential store opens still leak it
- File: agent_sdk/app.py:670 — `skills = SkillsRegistry(self.skills_dir)`
- Problem: GH-236 moved only the `mcp_skills` and reserved-name checks ahead of `_build_credential_store()`. Still after it: SkillsRegistry parse errors, `exclude_from_catalog` unknown-name ValueError (~671-676), mcp_instructions double-source ValueError, secret-in-mcp_instructions ValueError. `test_boot_checks_run_before_credential_store` also misses the `mcp_skills=... requires skills_dir` branch.
- Fix: move SkillsRegistry load and `exclude_from_catalog` check above the store (neither needs it), or wrap post-store code in try/except BaseException that closes the store and re-raises. Extend the parametrized test with an `exclude_from_catalog` case and a `mcp_skills="tool", skills_dir=None` case.
- sdkCandidate: true

### D7 (R1 RT-006) — C-040 registry table row not updated
- File: workspace/components/README.md:37
- Problem: AC says the C-040 row must state ingress maps RecursionError to the fixed-message JSONDecodeError. Only the long-form section (~line 242) was edited.
- Fix: edit the row, e.g. "...ingress pair; also maps RecursionError from deep nesting to a fixed-message JSONDecodeError (GH-235); scrub_unencodable store-side helper". Mention the depth cap too (see D4).
- sdkCandidate: true

### D8 (R1 RT-008) — A2A nested-body test checks only HTTP 400
- File: tests/test_gh235_nested_json_and_resume.py:88 — `assert r.status_code == 400, r.text`
- Problem: -32602 invalid-params also returns 400; a regression routing JSONDecodeError to the ValueError branch would pass.
- Fix: assert `r.json()['error']['code'] == -32700` and the message `request body is not valid JSON`.
- sdkCandidate: true

### D9 (R1 RT-009) — C-070 row location and description stale
- File: workspace/components/README.md:63
- Problem: `_decode_cursor`/`_encode_cursor` now ~581-597; slices in `_handle_prompts_list` (~663) and `_handle_tools_list` (~711). Row says "shared cursor page helper" but only `_decode_cursor` is shared.
- Fix: update line ranges and wording ("shared _decode_cursor; each list slices inline"), or extract a real `_paginate(items, cursor)` helper and point the row at it.
- sdkCandidate: true

### D10 (R2 RT-005) — AG-UI pre-admission resume lookup ignores the one-entry rule
- File: agent_sdk/routes/ag_ui.py:522 — `entry = resume_raw[0]`
- Problem: the more-than-one-entry check lives only in `_run`. `_resume_interrupt_id` (used by `_resume_target_task_id` and `_admit`, documented never to disagree with `_run`) still resolves entry 0 and counts it against the subscriber cap, so an invalid two-entry body can get HTTP 429 instead of RUN_ERROR `invalid resume entry`.
- Fix: return "" when `len(resume_raw) != 1`, or share one validity helper between pre-admission and `_run`.
- sdkCandidate: true

### D11 (R2 RT-006) — GH-242 weak test left in place; `_sample` skips optional fields
- File: tests/test_rt001_strict_required_nullable_output.py:52 — `def test_every_builtin_content_type_sample_wire_validates() -> None:`
- Problem: old test (fails only on messages containing `null`, skips models whose construct fails) kept beside the new one. New `_sample` (line 130, `if k in required and depth < 6`) fills required fields only, so optional 3+-member nullable unions are never validated.
- Fix: delete/replace the old test; extend `_sample` to fill optional properties (at least one all-optional sample).
- sdkCandidate: true

### D12 (R2 RT-007) — rewritten test file not in GH-236 plan or CHANGELOG
- File: tests/test_mcp_security_rt001_005.py:67 — `def test_decode_cursor_negative_rejected_by_unit() -> None:`
- Problem: rewritten because the cursor clamp was removed, but absent from GH-236's `Creates:` list and the CHANGELOG `Tests:` list. Scope drift; archive gate per-file checks miss it.
- Fix: add it to the GH-236 Creates line in the wave file and the GH-236 CHANGELOG `Tests:` list.
- sdkCandidate: true

### D13 (R2 RT-008) — docs do not state AG-UI resume takes exactly one entry
- File: docs/protocols.md:102
- Problem: more than one entry now ends with RUN_ERROR `invalid resume entry` (code `validation`); docs are silent.
- Fix: state `resume` must hold exactly one entry, and what more than one returns.
- sdkCandidate: true
