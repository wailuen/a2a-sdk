# w031 — AG-UI wire-fidelity fixes (pre-v0.5.40 release gate)

Sourced from `/sdk-test` Leg 3 (`/agent-stack-check . --static-only`), AG-UI advisor
audit, 2026-07-11. Both items independent. Run in parallel (group:G).
Target: 0.5.40 (bundled with GH-104, GH-105).

---

- [ ] `AGUI-1` Interrupt.expiresAt emitted as int, upstream spec types it Optional[str] ‖ group:G
  - Creates: `agent_sdk/common/iso8601.py`, `tests/test_iso8601.py`,
    `tests/test_task_memory_store.py`
    (modifies `agent_sdk/routes/ag_ui.py`, `agent_sdk/agent/events.py`,
    `agent_sdk/agent/runner.py`, `agent_sdk/tasks/memory.py`, `agent_sdk/tasks/store.py`)
    - RT-002 scope-union: the wave extracted the ISO-8601 `strftime` idiom into the
      shared `agent_sdk/common/iso8601.py` helper (imported by the in-scope `ag_ui.py`)
      and added its unit tests plus `tests/test_task_memory_store.py` for the new
      `interrupt_ttl_remaining` hook; these are unioned here so any scope-derived
      review/archive guard covers every path the wave actually touched.
  - Reads: `agent_sdk/routes/ag_ui.py:308`
  - Severity: high
  - Root cause: `interrupt["expiresAt"] = int(event.expires_at * 1000)` emits an integer epoch-ms.
    The upstream `ag-ui-protocol` Python SDK's `Interrupt.expires_at` is `Optional[str]`
    (confirmed live against `ag-ui-protocol/ag-ui` main, `sdks/python/ag_ui/core/types.py`).
    A consumer parsing `RunFinishedEvent.outcome` through the reference Pydantic model fails
    validation. Invisible in this repo's own tests because the server hand-builds dicts and
    the console never reads `expiresAt`.
  - AC: `expiresAt` is emitted as a string (confirm ISO-8601 vs stringified epoch-ms convention
    against docs.ag-ui.com or the upstream SDK's own serialization before choosing the format).
    - Resolved (RT-002): direct package inspection of installed `ag-ui-protocol==0.1.19`
      confirms `Interrupt.expires_at: Optional[str]` (`ag_ui/core/types.py:270`) — rules out
      epoch-ms as int/float — but the package does not further constrain the string encoding.
      ISO-8601 UTC is this SDK's own interoperable-default choice, not an upstream mandate.
      Full citation + verification method: `workspace/learning/LRN-111-agui-interrupt-expires-at-wire-format-citation.md`.
      Also cited inline at `agent_sdk/routes/ag_ui.py:327-341`.
  - AC: add/extend a regression test asserting `expiresAt` is a `str` on the wire for an
    interrupt outcome (auth-required or input-required).
  - AC: existing AG-UI interrupt tests still pass.
  - Note (scope, RT-002): converting to a wall-clock ISO-8601 string correctly requires
    `event.expires_at` to carry a clock-agnostic *relative* duration (seconds remaining)
    rather than a raw `TaskStore`-internal deadline reading (the in-memory store uses
    `time.monotonic`; a durable store may use `time.time`) — `ag_ui.py` cannot safely do
    `now + deadline` otherwise. That forces a small `TaskStore` contract addition, not just
    an `ag_ui.py`-local change:
    - `agent_sdk/tasks/store.py`: `TaskStore` gains `interrupt_ttl_remaining(task_id) -> float | None`,
      default `None` (safe no-op for pre-existing external `TaskStore` subclasses).
    - `agent_sdk/tasks/memory.py`: `InMemoryTaskStore` overrides it, computing
      `record.interrupt_deadline - self._clock()`.
    - `agent_sdk/agent/runner.py`: sets `event.expires_at = store.interrupt_ttl_remaining(task.id)`
      instead of the raw `record.interrupt_deadline`.
    - `agent_sdk/agent/events.py`: `InterruptEvent.expires_at` docstring/comment updated to state
      the relative-seconds contract.
  - AC: `TaskStore.interrupt_ttl_remaining` default (`None`) does not break any existing
    external/test `TaskStore` subclass that predates this hook.

- [ ] `AGUI-2` Console folds assistant-turn history using UserMessage's multimodal content shape ‖ group:G
  - Creates: (modifies `agent_sdk/console/static/chat.js`)
  - Reads: `agent_sdk/console/static/chat.js:482`
  - Severity: high
  - Root cause: on `TEXT_MESSAGE_END` the console folds the assistant turn into
    `state.aguiMessages` as `{id, role:"assistant", content:[{type:"text", text: buf.text()}]}`.
    Per the upstream spec, only `UserMessage.content` is `Union[str, List[InputContent]]`;
    `AssistantMessage` inherits `BaseMessage.content: Optional[str]` — a plain string. Every
    later `RunAgentInput` in the session replays the malformed assistant message. Invisible
    against this SDK's own server (`_fold_history` in `ag_ui.py` flattens any list-of-parts
    regardless of role) but a spec-strict third-party AG-UI server will 422 on turn two, since
    the console's `baseInput` field lets it target any AG-UI server.
  - AC: `chat.js:482` assistant-turn fold uses `content: buf.text()` (plain string), not the
    list-of-parts shape.
  - AC: user-turn fold (chat.js:422) is unchanged (it legitimately uses the list shape).
  - AC: existing console/chat tests (`tests/test_card_console.py` and any chat.js-covering
    tests) still pass.

## Post-wave addendum (applied outside the wave cycle, same release gate)

- `AGUI-3` (found by w031's own final protocol-audit recheck, not fixed by the wave —
  exhausted its phase-redteam budget with this still open; not captured in any
  LRN/deferred-note/SDK-candidate by the wave itself): AG-UI resume payload shape
  incompatible with `agent_sdk/contrib/action_gate/gate.py::parse_decision()` — a
  bare-string `payload` is silently discarded (`payload = raw_payload if
  isinstance(raw_payload, dict) else None`), so every action_gate-gated tool
  confirmation driven from the console's AG-UI tab landed on `Outcome.UNCLEAR`
  regardless of the user's actual approve/reject intent. Severity: high (hard
  release blocker per `/sdk-test`'s "any HIGH/CRITICAL is a release blocker" rule).
  - Fix: `agent_sdk/console/static/chat.js` — `resume: [{ interruptId, status:
    "resolved", payload: { decision: text } }]` (was a bare `payload: text`).
  - Regression test: `tests/test_card_console.py::test_agui_resume_payload_matches_action_gate_contract`
    (source-text pin, matching this file's existing style for JS-runtime-less checks).
  - Applied directly (single well-diagnosed one-line fix, root-caused against
    `gate.py` and cross-referenced with already-correct server-side tests
    `tests/test_ag_ui_resume.py`, `tests/test_ag_ui.py`,
    `tests/test_contrib_action_gate.py`) rather than spinning up another full
    wave cycle for it.
- Medium AG-UI Origin-check gap (`agent_sdk/routes/ag_ui.py`'s `POST /ag-ui/run`
  lacks the RT-004 defense-in-depth Origin allow-list check `agent_sdk/routes/mcp.py`
  enforces) — explicitly deferred, not fixed in this release. See
  `workspace/sdk-candidates.md` Candidate 4 for rationale (bundles with the
  identical `agent_sdk/routes/a2a.py` gap, out of this wave's scope).

## Non-goals (explicitly out of scope for this wave)

- The AG-UI/A2UI tier-gating asymmetry noted by the A2UI advisor (Finding #1, MEDIUM,
  already ratified via `workspace/learning/LRN-049-agui-custom-emit-freely-catalog-gate-wrong.md`
  and pinned by `tests/test_rt001_ag_ui_custom_extended_gate.py`) — do not touch.
- The A2A agent-card `outputSchemaWireNote` accuracy finding (MEDIUM) — separate concern,
  not release-blocking, defer to a future wave.
- Adopting the real `ag-ui-protocol` Python package for serialization, or a CI schema-validation
  gate against it (MEDIUM, root-cause-class fix) — out of scope, too large for this gate-clearing wave.
