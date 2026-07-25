wave: w038
group: G
date: 2026-07-25
round_count: 5
status: resolved/archived

## Findings

### RT-001
- severity: medium
- file: agent_sdk/testing/chat.py
- description: extract_a2ui() was changed to unwrap data.get("messages", []) (was p["data"]) but has zero test coverage — test_chat_driver.py never exercises it, and no other test constructs a task dict with a wrapped A2UI DataPart to pin the new unwrap. The parallel console consumer handleA2aArtifact() DID get a dedicated pin (tests/test_card_console.py::test_handle_a2a_artifact_guards_malformed_a2ui_datapart), so consumer-side coverage is asymmetric.
- fix: Add a unit test in tests/test_chat_driver.py that builds a task dict with an A2UI DataPart {"kind":"data","metadata":{"mimeType":"application/a2ui+json"},"data":{"messages":[...]}} and asserts extract_a2ui() returns [[...]] (the unwrapped array), plus a malformed case ({"data":{}} → [[ ]] i.e. []) to lock the guard. This makes a revert of data.get("messages") → p["data"] fail the suite.
- codify: When a wire-shape change touches two consumers (console + scripted client), both consumers need a regression pin — an untested consumer silently reverts.
- sdkCandidate: false
- status: RESOLVED (fixed same day, pre-rerun) — added `test_rt001_extract_a2ui_unwraps_messages_object` (well-formed `{"messages": [...]}` unwrap) and `test_rt001_extract_a2ui_guards_malformed_data_dict` (missing-key → `[[]]`) to `tests/test_chat_driver.py`. Full suite green (1289 passed, 1 skipped), `mypy agent_sdk/` clean.

### RT-002
- severity: medium
- file: agent_sdk/agent/runner.py
- description: The GH-128 fix resolves a genuine two-spec conflict (A2A v0.3.0 DataPart.data=object vs A2UI v0.9.1 A2A binding=bare array, both verified in LRN-134) by wrapping as {"messages":[...]}, which knowingly makes every A2UI artifact this SDK emits over A2A non-renderable by a strictly spec-conformant third-party A2UI Path-A renderer. The GH-128 "Critical" premise (A2A base type unconditionally governs) is contestable — an activated A2A extension may refine its own mimeType payload shape, under which the original bare array was conformant. This permanent, contested protocol deviation with a real interop cost is recorded only as a low-severity LRN-134 + inline comments; the dataEncoding card hint is non-normative (third parties need not read it), so it does not actually restore interop.
- fix: Promote the base-vs-extension conflict decision to an ADR (matching the project's ADR-for-locked-protocol-decisions convention, e.g. ADR-0001/a001), stating the decision, the rejected alternative (keep bare array under extension refinement), and the accepted third-party-renderer interop cost. Consider filing an A2UI spec clarification issue upstream so the resolution can eventually be canonical rather than SDK-private, and re-evaluate whether an activated-extension DataPart should keep the spec's bare array.
- codify: Resolving a base-protocol vs activated-extension binding conflict is an ADR-level decision, not a low LRN — the rejected side and its residual interop cost must be durably recorded and the direction re-justified.
- sdkCandidate: true
- status: RESOLVED (fixed same day, pre-rerun) — this SDK's own workspace has no per-repo `workspace/adr/` (that convention is for agent repos generated from the SDK via `template/CLAUDE.md`; see `template/workspace/adr/a001-credential-model.md`). The SDK's own equivalent — an explicit owned-decision sign-off round, per the precedent already set by REVIEWS.md Round 5 (GH-115 MCP void-result parity) — was added as **REVIEWS.md Round 6**: states the decision (KEEP the object wrapper), the rejected alternative (bare array under extension-refinement reading), and the accepted residual interop cost, with citations back to LRN-134 and DESIGN.md §5.4. Filing an upstream google/A2UI spec-clarification issue was considered and explicitly left to the maintainer's discretion (an automated agent opening a public issue on an unrelated third-party repo is out of scope for this fix) — this sign-off does not depend on it.

### RT-003
- severity: low
- file: agent_sdk/console/static/chat.js
- description: The new guard hasMessages = part.data && Array.isArray(part.data.messages) treats a well-formed-but-empty A2UI DataPart ({"messages":[]}) as rendered: it calls renderA2uiMessages([]) (paints nothing) and sets renderedA2ui=true, which suppresses the outer `if (!renderedA2ui && fallbackText)` TextPart fallback. A third-party A2A server emitting an empty messages wrapper would show neither A2UI output nor the fallback text, and no systemLine (silent). This SDK's own outbound path never emits an empty array so it is latent, but the guard's empty-array branch is a blind spot.
- fix: Gate rendered-state on non-empty content: e.g. const msgs = part.data && Array.isArray(part.data.messages) ? part.data.messages : null; if (msgs && msgs.length) { renderA2uiMessages(msgs, fallbackText); renderedA2ui = true; } else { systemLine(...); } — so an empty/absent messages array falls through to the TextPart fallback instead of swallowing it.
- sdkCandidate: false
- status: RESOLVED (fixed same day, pre-rerun) — `handleA2aArtifact()` in `agent_sdk/console/static/chat.js` now computes `msgs` once and only sets `renderedA2ui = true` when `msgs && msgs.length`; a well-formed-but-empty array now emits a distinct `systemLine("a2ui: DataPart.data.messages is empty — nothing to render")` instead of silently swallowing the TextPart fallback. Pinned by new `tests/test_card_console.py::test_handle_a2a_artifact_falls_through_on_empty_messages_array`.

## Instruction

All findings resolved and test-covered (full `tests/` suite green, 1311
passed, 2 skipped; `mypy agent_sdk/` clean); no re-run of /wave w038 needed.
`GH-128` ticked in `workspace/todos/completed/w038-gh128-datapart-object-wrap.md`.
Relocated from `workspace/todos/deferred/` to `workspace/todos/completed/`
per LRN-100 (a budget-exhausted deferred marker must be removed or
relocated the moment its findings land, or it falsely reports the wave as
incomplete).
