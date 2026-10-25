# w067 — deferred phase medium/low findings

- Wave: w067
- Scope: phase
- Date: 2026-10-25

Non-blocking — these did not block w067's archive. Address opportunistically or fold into a future wave.

## Medium

### RT-001 — agent_sdk/auth/middleware.py:9 [sdkCandidate]
- Quote: `unauthenticated/failed attempt, per-identity after auth. 401s on the MCP`
- Description: [SDK] GH-265 item 2 names the stale middleware docstrings (middleware.py:8-9 and the unauth_rate_limit docstring at :182) as defects to fix, but both are unchanged: the module docstring still says one per-IP layer covers 'every unauthenticated/failed attempt' (a missing bearer is uncounted since GH-260, and failed bearers now use a separate bearer_limiter), and unauth_rate_limit's docstring lists only /oauth/register, /oauth/token and the consent POST, while the limiter guards all seven /oauth/ routes. The todo AC requires every numbered item to be fixed.
- Fix: Rewrite middleware.py:8-9 to describe the three per-IP facts: missing bearer is uncounted, failed bearers count in bearer_limiter, /oauth/* counts in unauth_limiter (both sized by AGENT_SDK_UNAUTH_RATE_LIMIT). Change the unauth_rate_limit docstring (:182-183) to name the OAuth endpoint bucket and all seven /oauth/ routes it guards.
- Codify: When an issue lists stale docstrings by file:line, the wave's diff must touch each listed line; grep the cited lines after implementing.

### RT-002 — DESIGN.md:447 [sdkCandidate]
- Quote: `- **Rate limiting — three layers:** ... (2) **per-IP windows on all unauthenticated paths** (failed bearers in their own window, separate from /oauth/register, /oauth/token, consent; both sized by AGENT_SDK_UNAUTH_RATE_LIMIT, GH-260) ...`
- Description: [SDK] DESIGN §6 still states in bold the claim GH-265 item 2 calls stale ('per-IP windows on all unauthenticated paths'). A missing bearer is never counted (GH-260), and the new failed-bearer window is credited to GH-260 instead of GH-265. The sentence also leaves out /oauth/revoke, the browser authorize/callback/consent routes, and the branded HTML 429 split.
- Fix: Replace the bold claim with: per-IP windows on failed bearers (own bucket, GH-265) and on the /oauth/* endpoints (separate bucket); a request with no bearer is never counted (GH-260). Cite GH-265 and its ruling URL, and mention the browser-route HTML 429.
- Codify: A doc sentence named stale by an issue must lose the stale claim itself; adding a parenthetical next to it does not fix it.

### RT-003 — agent_sdk/models/content_types.py:784 [sdkCandidate]
- Quote: `    x_key: Literal["date"] = "date"`
- Description: [SDK] GH-262 item 4's stated failure is that assignment after construction bypasses the x_key/y_key guard. Typing the fields as Literal does not change that at runtime, because _Wire has no validate_assignment. Verified: after `c.x_key = 'ts'`, `c.wire()['x_key']` returns 'ts', so a chart the console cannot render still goes out on the wire.
- Fix: Make the keys immune to assignment: set `model_config = ConfigDict(..., validate_assignment=True)` on TimeSeriesChart, or mark x_key/y_key frozen (Field(frozen=True)), or have the TimeSeriesChart serializer always write the fixed values. Add a test that assigns `x_key='ts'` and asserts it raises, or that wire() still writes 'date'.
- Codify: A Literal annotation on a pydantic field is only a static-typing guard; runtime immutability needs validate_assignment or frozen.

### RT-004 — tests/test_gh257_single_a2ui_gate.py:130 [sdkCandidate]
- Quote: `json=_msg(configuration={"acceptedOutputModes": ["application/a2ui+json"]}),`
- Description: [SDK] After GH-261, test_modes_with_a2ui_off can no longer fail if the app gate is removed. It sends application/a2ui+json without the X-A2A-Extensions header, and since GH-261 an A2UI-enabled app returns -32005 for that request too. The assertion is therefore true with the gate on or off, which is the 'A2UI-off tests cannot fail' defect GH-261 item 5 says must be fixed.
- Fix: Send the A2UI header on this request (headers={'X-A2A-Extensions': A2UI_EXTENSION_URI}), so -32005 can only come from app.state.a2ui_enabled being False. Add a control assertion that the same header plus mode succeeds on the emitting app.
- Codify: When a ruling changes when a rejection fires, re-check every test that asserts the rejection, so it still isolates the condition it was written for.

### RT-005 — pyproject.toml:25 [sdkCandidate]
- Quote: `    "referencing>=0.28.4",`
- Description: [SDK] A new direct runtime dependency (`referencing`, used by agent_sdk/testing/mcp.py's `except Unresolvable`) was added to core `dependencies`, and uv.lock changed. No w067 todo lists pyproject.toml or uv.lock, and CHANGELOG [Unreleased] does not mention the new dependency, though every install of the stable core now pulls it in directly.
- Fix: Add a CHANGELOG [Unreleased] entry (Changed or Added) naming the new `referencing>=0.28.4` core dependency and why. Record pyproject.toml/uv.lock in the GH-264 todo's Creates list, or move the import behind the provisional testing extra.
- Codify: Any change to pyproject.toml dependencies gets its own CHANGELOG line and a todo Creates entry, even when it only declares a dependency that was already transitive.

## Low

### RT-006 — tests/test_gh257_single_a2ui_gate.py:108 [sdkCandidate]
- Quote: `if not emitting:`
- Description: [SDK] test_card_state_and_runtime_agree now returns early for emitting=False, so the off case checks only the card and never the runtime. The test name promises that the card and runtime agree in both states.
- Fix: For emitting=False, drive a ContentModel-returning tool on an app whose computed gate is False (for example allowed_components that removes every type), send the A2UI header, and assert no A2UI part, so the runtime half is covered for both states.

### RT-007 — agent_sdk/auth/middleware.py:50 [sdkCandidate]
- Quote: `# GH-260: failed-bearer 401s count here, never in the OAuth-endpoint bucket.`
- Description: [SDK] The bearer_limiter comment credits the change to GH-260, but the separate failed-bearer bucket is GH-265 (GH-260 only stopped counting missing bearers). This misleads readers tracing the ruling.
- Fix: Change the comment to cite GH-265 and its ruling URL.

### RT-008 — agent_sdk/routes/mcp.py:990 [sdkCandidate]
- Quote: `# never reached to raise), which is spec-consistent: MCP §4 only requires`
- Description: [SDK] The mcp.py comment still calls the void-result fold 'spec-consistent', while docs/protocols.md now records it as a known deviation from the outputSchema MUST (GH-266 item 1). Code and docs contradict each other on whether this is a deviation.
- Fix: Reword the comment as a documented deviation (GH-266, parity with A2A/AG-UI) and point to docs/protocols.md. This is a comment-only change, so the 'no code change in mcp.py' AC still holds.

### RT-009 — agent_sdk/routes/a2a.py:626 [sdkCandidate]
- Quote: `ResumeEnvelope(value, identity, list(resume_modes) if resume_modes else None),`
- Description: [SDK] The GH-261 todo AC says `_resume_or_error` sets record.accepted_output_modes before deliver_resume. The landed code instead carries the new modes in ResumeEnvelope and the worker applies them (runner.py:1349), and a test pins that design. It may be the better design (no losing-resumer overwrite), but the active todo AC was not amended, so the plan and the code disagree.
- Fix: Amend the GH-261 AC in workspace/todos/active/w067-gh-issues.md, and post a ruling note on GH-261, to record the envelope design; or change the code to match the AC as written.

### RT-010 — agent_sdk/agent/runner.py:461 [sdkCandidate]
- Quote: `update["metadata"] = {k: v for k, v in meta.items() if k != "mimeType"}`
- Description: [SDK] The GH-261 ruling says artifact metadata.mimeType is 'rewritten to match the kept parts'. apply_output_modes only deletes the key when no kept part carries that mimeType; it never writes the kept parts' type (for example application/json or text/plain).
- Fix: Set metadata.mimeType to the single media type of the kept parts when they share one, and drop it only when they are mixed. Add a unit test for that branch.

### RT-011 — tests/test_gh258_catalog.py:279 [sdkCandidate]
- Quote: `missing = required - emitted_paths(inst.wire())`
- Description: [SDK] The GH-262 round-trip test checks one direction only: the summary's required keys must appear in wire(). A key that wire() always writes but the summary marks optional (a wrong `?`) is never caught, although the ruling asks to compare each key against the summary.
- Fix: Also assert the reverse for each instance: every always-written top-level key (present in wire() with all optional fields unset) is in required_paths. Or compare against a second instance with every optional field filled.

### RT-012 — tests/test_gh259_a2a_route.py:554 [sdkCandidate]
- Quote: `assert a2a._INVALID_RESPONSE_TEXT == "invalid agent response"`
- Description: [SDK] GH-261 low 'FAILED tail message is built by hand with a duplicated literal' is only half fixed. The literal became a constant, but a2a.py:960-972 still builds the failed TaskStatus/Message/WireError by hand instead of going through set_task_status (which builds status.message once). The pinning test only asserts the constant's value, so it cannot catch the two sites drifting apart.
- Fix: Build the tail frame from the shared failed-status builder used by set_task_status, or test that the frame's status.message text equals status.error.message, instead of testing the constant's value.

---

Autoloop cycle 3 (2026-10-25): mediums verified at v0.24.0; still-present ones filed as #268–#274 (testing #268, AG-UI/console #269, A2UI #270, A2A #271, auth #272, MCP #273, example/tests/registry #274). P-022 not filed (conflicts with #246 ruling). Lows not filed.
