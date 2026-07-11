# SDK issue candidates — w031 (2026-07-11)

Run `/sdk-issue-scan` to review and file as GitHub issues on `wailuen/a2a-sdk`.

Candidates 5-8 below were surfaced by the full 4-advisor `/sdk-test` Leg 3
re-audit run before tagging v0.5.40 (2026-07-11), not by w031 itself. All are
Medium/Low, non-blocking, and out of this release's approved scope
(GH-104/GH-105 + AGUI-1/AGUI-2/AGUI-3) — deferred per `/sdk-test`'s rule that
Medium/Low findings must be "acknowledged... either fixed or recorded as
deferred with a rationale" before tagging, not silently bundled into an
already-scoped release.

## Candidate 1: RT-001: ag_ui.py serializes InterruptEvent.expires_at via datetime.fromtimestamp() as if it were a Unix epoch, but the value originates from a time.monotonic()-based deadline (runner.py <- memory.py interrupt_deadline, clock never overridden at app.py wiring), so the wire-emitted expiresAt lands around 1970 instead of the real wall-clock expiry, which a spec-strict AG-UI consumer would treat as already-expired.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/routes/ag_ui.py
- Rationale: SDK-level: this is a protocol route (agent_sdk/routes/ag_ui.py) serializing the AG-UI wire format's Interrupt.expiresAt field per DESIGN.md §5.3 — squarely inside 'protocol routes' scope. VERIFICATION: the current uncommitted working tree already fixes this exact bug — event.expires_at is redefined as a relative TTL-remaining value (via TaskStore.interrupt_ttl_remaining) and the route computes `wall_deadline = time.time() + event.expires_at` before calling iso_utc(), matching the finding's recommended fix. This candidate should be checked against the working-tree diff before filing/re-filing — it may already be resolved pending commit.

## Candidate 2: RT-001: w031's in-wave hardening added a list-content text join in _validate()/_fold_history that could raise TypeError on a non-string/null 'text' field in a multimodal message part; if invoked outside the terminal-frame try/except, this would abort the SSE stream after RUN_STARTED/STATE_SNAPSHOT with no terminal RUN_FINISHED/RUN_ERROR frame, violating the AG-UI 'exactly one terminal frame' invariant.
- Severity: high
- Component: protocol/ag-ui
- File: agent_sdk/routes/ag_ui.py
- Rationale: SDK-level: protocol route enforcing the AG-UI SSE terminal-event contract (RUN_STARTED -> ... -> exactly one of RUN_FINISHED|RUN_ERROR per this module's own docstring). VERIFICATION: current uncommitted working tree already has the total/safe join `str(p.get('text') or '')` in _fold_history, exactly matching the finding's suggested fix, and _validate() only checks `messages must be a list` (no raising join left in it). Confirm against the working-tree diff before filing — likely already resolved pending commit; if filed, verify against the committed HEAD (pre-fix) state, not the working tree.

## Candidate 3: RT-001: AGUI-1's clock-agnostic fix added a new @abc.abstractmethod interrupt_ttl_remaining to the public/exported TaskStore ABC (a documented extension point per docs/deployment.md and DESIGN.md), which would break every external TaskStore subclass at instantiation (TypeError) on upgrade, a backward-incompatible change if shipped in a patch release without a default or deprecation path.
- Severity: high
- Component: sdk/loop
- File: agent_sdk/tasks/store.py
- Rationale: SDK-level: TaskStore is core SDK internals (task/interrupt lifecycle underlying the agent execution loop, used by both A2A and AG-UI routes for interrupt/resume) — matches the 'SDK internals' inclusion criterion; mapped to sdk/loop since it is protocol-agnostic runtime-loop machinery, not a protocol-specific route. VERIFICATION: current uncommitted working tree already defines interrupt_ttl_remaining as a concrete method with a safe `return None` default (not @abc.abstractmethod), exactly matching the finding's recommended fix, with a docstring explicitly noting the default exists so 'pre-existing TaskStore subclasses that predate this hook keep instantiating'. Confirm against the working-tree diff before filing — this is likely already resolved pending commit.

## Candidate 4: RT-004 pattern gap: agent_sdk/routes/ag_ui.py's POST /ag-ui/run lacks the defense-in-depth Origin allow-list check that agent_sdk/routes/mcp.py enforces on every browser-reachable streaming surface (5 call sites, RT-004). agent_sdk/routes/a2a.py has the identical gap.
- Severity: medium
- Component: protocol/ag-ui (+ protocol/a2a, same gap)
- File: agent_sdk/routes/ag_ui.py, agent_sdk/routes/a2a.py
- Rationale: SDK-level: protocol route hardening, uniform-surface consistency (RT-004's own stated intent: "every browser-reachable streaming surface", not just MCP). Deliberately NOT bundled into w031/v0.5.40: fixing only ag_ui.py's half would leave a2a.py's identical gap open, an inconsistent partial hardening; a2a.py was out of w031's audited scope entirely (AGUI-1/AGUI-2 only). Fix both routes together in one wave using the exact 3-line pattern already established at agent_sdk/routes/mcp.py:446-448 (mirrors mcp_post/mcp_get/etc. — `origin = request.headers.get("origin"); if origin is not None and origin not in request.app.state.cors_origins: raise HTTPException(403, "origin not allowed")`). Re-confirmed still present and still correctly Medium (not exploitable via classic CSRF given header-only Bearer auth) by the v0.5.40 Leg 3 re-audit.

## Candidate 5: mcp_get and mcp_delete (agent_sdk/routes/mcp.py) never call the existing `_negotiated_version()` helper, so a present-but-unrecognized `MCP-Protocol-Version` header value is silently accepted on GET/DELETE instead of the 400 that mcp_post already returns for the same invalid-value case.
- Severity: medium
- Component: protocol/mcp
- File: agent_sdk/routes/mcp.py:576 (mcp_get), agent_sdk/routes/mcp.py:604 (mcp_delete)
- Rationale: SDK-level: MCP Streamable HTTP transport, spec §10 header-validation rule. Cheap, mechanical fix (reuse `_negotiated_version()`, already defined at mcp.py:174, mirroring the invalid branch already in mcp_post at lines 486-500). No test currently covers this (`tests/test_http_protocol.py:137-141` only checks 401/WWW-Authenticate on GET). Does not affect Claude.ai connector flow (only exercises POST-based JSON-RPC dispatch); deferred rather than bundled into v0.5.40 because it's unrelated to this release's AG-UI-wire-fidelity scope.

## Candidate 6: agent_sdk/testing/chat.py's ChatDriver (D7.2) parses the agent card and computes a transport/URL selection (incl. walking additionalInterfaces for a fallback) but never acts on the result — every request unconditionally goes to POST /v1/message:send against the pre-bound httpx.AsyncClient, regardless of what transport was selected.
- Severity: medium
- Component: protocol/a2a (consumer/ChatDriver)
- File: agent_sdk/testing/chat.py:234-336
- Rationale: SDK-level: A2A consumer role, §5.6.3/§11.2.1 transport-selection MUST. Harmless today (every agent this SDK generates serves HTTP+JSON at the pre-configured base URL) but a real functional-correctness gap if ChatDriver (reachable via `python -m agent_sdk test-chat --url <any-agent>`) is pointed at a third-party agent declaring a different preferredTransport or additionalInterfaces URL. Fix: either wire the selection into the actual request, or narrow the docstring/CLI help to state HTTP+JSON-only and delete the dead selection code. Deferred — unrelated to this release's AG-UI-wire-fidelity scope.

## Candidate 7: A2UI's translate() (agent_sdk/a2ui/translator.py:118-139) always bundles createSurface+updateComponents+updateDataModel+deleteSurface as one atomic 4-message array per artifact. Under a literal reading of the spec's own reference client algorithm (fold the whole array, including the deleteSurface unmount, before a single post-fold paint), this renders nothing — every artifact this agent emits would appear blank to a third-party Path-A renderer built strictly from the public A2UI spec, not this project's DESIGN.md.
- Severity: medium
- Component: protocol/a2ui
- File: agent_sdk/a2ui/translator.py:118-139
- Rationale: SDK-level: A2UI emit-side wire contract (createSurface/updateComponents/updateDataModel/deleteSurface message ordering). This project's own console renderer (agent_sdk/console/static/a2ui.js) works correctly only because of a project-local, DESIGN.md §7.1-documented "show-then-close" convention (deferring deleteSurface to a post-paint step) that is NOT part of the public A2UI wire contract — a silent interop trap for any third-party renderer. Two possible fixes (not applied): (a) advertise `deleteSurfaceSemantics: "post-paint"` in the A2UI extension params (agent_sdk/a2ui/catalog.py:a2ui_extension()), or (b) stop bundling deleteSurface in the same atomic array, letting surfaces persist until an explicit later cleanup. Deferred — this is a documentation/interop-hardening decision requiring product judgment on whether third-party A2UI consumers are actually expected, not a mechanical fix; unrelated to this release's AG-UI-wire-fidelity scope.

## Candidate 8: GH-74's intentional fail-closed default (AG-UI-side A2uiCapabilities defaults to tier="none" when forwardedProps.a2uiClientCapabilities is entirely absent, diverging from the spec's stated tier="core" default and from this project's own A2A-side default) has no workspace/learning/LRN-*.md doc memorializing it as deliberate, unlike the sibling LRN-049 decision in the same function family.
- Severity: low
- Component: protocol/a2ui, docs
- File: agent_sdk/routes/ag_ui.py:370-374 (A2uiCapabilities tier default), workspace/learning/
- Rationale: Process-hardening, not a code fix: `grep -ril "GH-74" workspace/learning/` returns nothing. Write an LRN doc analogous to LRN-049 so a future wave doesn't "fix" this toward literal spec-default alignment without knowing the fail-closed choice is deliberate and tested (tests/test_gh74_ag_ui_capabilities_fail_open.py) — the exact failure mode LRN-049 itself exists to prevent, one wave earlier, for a sibling decision. Near-zero cost; deferred only because it's documentation debt, not a release gate.
