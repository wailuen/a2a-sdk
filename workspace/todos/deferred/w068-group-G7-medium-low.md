# w068 — unit:G7 — deferred medium/low findings

- Wave: w068
- Scope: unit:G7
- Date: 2026-10-25

Non-blocking — these did not block w068's archive. Address opportunistically or fold into a future wave.

## Medium

### 1. CHANGELOG.md:45 — v0.24.0 GH-267 correction is itself false (sdkCandidate)
- Quote: "...so it was rejected for that reason, not for depth (corrected in GH-274 ...); the header-too-deep test used a non-object source value that failed the shape check first (GH-274 now spies on `NestingTooDeep`)..."
- Problem: `_parse_send` (routes/a2a.py:513-515) runs `loads_strict` + depth check before `MessageSendParams.model_validate`; `parse_header` (forwarding.py:76) checks depth before shape. So the old requests WERE rejected by the depth check. The real defect: the metadata body was otherwise invalid, and the header body would still be refused by the shape check with the depth cap removed.
- Fix: Reword: "the deep-metadata test body had no `kind: message` or part `kind`, so it was not otherwise valid as claimed (GH-274: the body is now valid and a shallow-metadata control succeeds); the header-too-deep test's list source value would still fail the shape check with the depth cap removed, so it could not fail (GH-274 now spies on `NestingTooDeep`)."

### 2. tests/test_gh235_nested_json_and_resume.py:406 — AG-UI cancelled+approved test guards nothing new (sdkCandidate)
- Quote: `async def test_agui_cancelled_resume_with_approved_decision_does_not_publish(client, fake_model):`
- Problem: pre-GH-274 handler already refused it (status 'cancelled' not in (None, 'resolved')). Mutation back to old logic left it passing. No docstring naming how it fails (G7 AC). CHANGELOG.md:15 still presents it as GH-274 behavior ("reject-wins").
- Fix: Drop the reject-wins claim from the GH-274 CHANGELOG line, or replace the test with one only `parse_decision` passes (e.g. A2A text resume "true" must not publish; or resolved status with payload `{'decision': 'approved', 'status': 'rejected'}`). Add a docstring naming the mutation caught.
- Codify: A test listed as guarding a behavior change must fail against the code from before the change; mutation-check it against the old handler.

## Low

### 3. CHANGELOG.md:15 — GH-274 line omits text-resume word change (sdkCandidate)
- Problem: publish_note used to approve only 'approved'/'yes'/'confirm'/'true'. Via `parse_decision` it now approves the whole action_gate list ('ok', 'okay', 'y', 'go', 'proceed', 'accept', 'yep', 'yeah', ...) and trims trailing punctuation; 'true' now declines. Adopters copy the example.
- Fix: Add: "an A2A text resume is now classified by the action_gate word list ('true' no longer approves; 'ok', 'y', 'go', 'proceed' and similar now do)."

### 4. CHANGELOG.md:15 — `referencing>=0.28.4` presented as new (sdkCandidate)
- Problem: listed under [Unreleased], but `git show v0.24.0:pyproject.toml` already declares it; pyproject.toml unchanged.
- Fix: "`referencing>=0.28.4` has been a declared dependency since v0.24.0 (pyproject.toml); that release's CHANGELOG left it out. It was already pulled in by jsonschema."

### 5. tests/test_gh235_nested_json_and_resume.py:347 — docstring scenario relies on exhausted fake-model script (sdkCandidate)
- Quote: "would then be accepted (200) instead of answering -32700. The shallow"
- Problem: Confirmed (with `_MAX_DEPTH` = 10**6 both cases get 200 and fail), but shallow control and deep request share one `reply("ok")` script; with the cap removed the second turn runs on an empty script — unstated dependency.
- Fix: `fake_model.script(reply("ok"), reply("ok"))`, or assert only status != 400 in the docstring scenario.

### 6. tests/test_gh235_nested_json_and_resume.py:384 — `_resume_with_data` silent on never-completed task (merged: RT-003 second half + RT-004)
- Quote: `if (await client.get(f"/v1/tasks/{task_id}")).json()["status"]["state"] == "completed":`
- Problem: loop breaks/ends silently when the task never completes, then reads `fake_model.calls[-1]` → confusing KeyError/IndexError or stale-call assertion.
- Fix: Match `_park_publish_note`: `else: raise AssertionError("task never completed")` on the for-loop.

### 7. agent_sdk/example/agent.py:86 — hand-written confirm schema duplicates action_gate (sdkCandidate)
- Quote: `"properties": {"decision": {"enum": ["approved", "denied"]}},`
- Problem: example imports contrib.action_gate yet keeps its own schema with 'approved'/'denied', differing from `action_gate.DEFAULT_CONFIRM_SCHEMA` and docs/protocols.md wording ('approved'/'rejected'). Second copy of a registered capability.
- Fix: Import and pass `DEFAULT_CONFIRM_SCHEMA` as response_schema, or change enum to ['approved', 'rejected']; note in the GH-274 CHANGELOG line.
