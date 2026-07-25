# w038 — GitHub issue 128

Sourced from a Critical finding surfaced during the v0.5.44 /sdk-test Leg 3
static conformance gate (a2a-advisor pass of /agent-stack-check). Single item,
run standalone (group:G).
Target: v0.5.44 (still unreleased/untagged — this fix lands before the tag,
not as a follow-up patch).

---

- [x] `GH-128` a2a: DataPart.data sent as bare array; A2A v0.3.0 requires an object ‖ group:G
  - Creates: (modifies `agent_sdk/models/a2a.py`, `agent_sdk/agent/runner.py`, `agent_sdk/console/static/chat.js`, `agent_sdk/testing/chat.py`, `tests/test_a2a.py`, `tests/test_protocol_fixes_w6.py`, `tests/test_protocol_wire.py`, `CHANGELOG.md`, `~/.claude/agents/a2ui-advisor.md`)
  - RT-002 reconciliation (post-landing, low severity): the same wave's redteam
    passes drove additional in-scope changes not enumerated above when the AC
    was first written. Recorded here so the tracked footprint matches what
    landed:
    - RT-001 (LRN-134 follow-up) — `agent_sdk/a2ui/catalog.py::a2ui_extension()`
      gained a non-normative `dataEncoding: "data.messages"` card hint
      (mirrors `deleteSurfaceSemantics`/GH-113) so a spec-conformant
      third-party A2UI Path-A renderer can discover the object-wrapped shape;
      pinned by new `tests/test_rt001_a2ui_data_encoding_hint.py`. Root cause
      and citation trail recorded in new
      `workspace/learning/LRN-134-a2ui-a2a-datapart-messages-key-not-spec-mandated.md`
      (indexed in `workspace/learning/README.md`).
    - `DESIGN.md` §5.4 updated to document the object-wrapped A2A wire shape,
      the `dataEncoding` hint, and the residual third-party-renderer interop
      caveat LRN-134 records.
    - RT-004 — `agent_sdk/console/static/chat.js`'s `handleA2aArtifact()`
      (already listed above) additionally guards the malformed/legacy-shape
      case (`part.data` null or missing `messages`) with a `systemLine`
      diagnostic instead of silently no-op'ing; pinned by new
      `tests/test_card_console.py::test_handle_a2a_artifact_guards_malformed_a2ui_datapart`.
    - RT-002 (later redteam round of this same wave — group G; NOT a separate
      "w039" wave, which was never planned/run/archived) — consumer read
      tolerance: `handleA2aArtifact()` + the `A2UI_UPDATE` branch of
      `handleCustom()` (`agent_sdk/console/static/chat.js`) and
      `extract_a2ui()` (`agent_sdk/testing/chat.py`) were widened to accept
      EITHER a bare-array `data`/`value` OR the object-wrapped
      `{"messages": [...]}` shape on read, so this SDK's own first-party
      consumers can also render a strictly spec-conformant third-party A2UI
      v0.9.1 producer's bare-array DataPart (which A2UI's own A2A binding
      mandates), matching the tolerant-consumer pattern
      `harness/agents/a2ui-advisor.md` prescribes. This is a READ-side
      widening only — the locked producer decision (object-wrapped emission,
      REVIEWS.md Round 6) is unchanged. Pinned by
      `tests/test_card_console.py::test_handle_a2a_artifact_well_formed_messages_live_behavior`
      / `::test_handle_a2a_artifact_accepts_bare_array_datapart_live_behavior`
      and `tests/test_chat_driver.py::test_rt002_extract_a2ui_accepts_bare_array`;
      DESIGN.md §5.4 and LRN-134 carry the citation trail. All in-tree code
      comments cite this as "w038 group G" — no code, test, or doc references
      a nonexistent "w039" wave.
  - Reads: `agent_sdk/routes/ag_ui.py` (the already-correct sibling convention), `agent_sdk/a2ui/translator.py`
  - Severity: Critical — confirmed against the canonical A2A v0.3.0 spec (`a2a.json`/`types.ts` at the pinned v0.3.0 tag: `DataPart.data` is `{"type":"object", ...}`, required). A schema-validating A2A client (A2A TCK, A2A Inspector, any typed SDK generated from the real spec) rejects every A2UI-carrying artifact this SDK emits.
  - Root cause: `agent_sdk/models/a2a.py:70` deliberately types `DataPart.data` as `dict[str, Any] | list[Any]` to permit a bare-array shape. `agent_sdk/agent/runner.py:177-186` constructs both the "open" and "close" A2UI DataParts with `data=open_messages` / `data=close_messages` (both `list[dict]`) directly, citing "trap #11" in a comment. That justification traces to `~/.claude/agents/a2ui-advisor.md:727` ("`data` MUST be a JSON array (even for one message)") — an advisor knowledge-file claim that contradicts the actual A2A base spec and has no ADR/LRN documenting it as a reviewed, intentional deviation. The AG-UI side of the exact same delivery path (`agent_sdk/routes/ag_ui.py`, `CUSTOM` event `value`) already wraps the same message array as `{"messages": [...]}` — only the A2A DataPart side is wrong. GH: https://github.com/wailuen/a2a-sdk/issues/128
  - AC:
    - `DataPart.data` wraps the A2UI message array in an object, `{"messages": [...]}`, on both the "open" and "close" DataParts in `agent_sdk/agent/runner.py::build_artifact()` — matching the AG-UI CUSTOM `value` convention exactly (same key name, same shape) so the two transports are structurally consistent, not just independently conformant.
    - `agent_sdk/models/a2a.py`'s `DataPart.data` type is tightened from `dict[str, Any] | list[Any]` to `dict[str, Any]` only, so this class of defect fails at construction time (Pydantic validation), not just at spec-review time. Confirm no other caller in `agent_sdk/` constructs a `DataPart` with a bare list (the P6-02 non-A2UI fallback branch at `runner.py:187-197` already passes a `dict` model-dump — must remain unaffected).
    - `agent_sdk/agent/runner.py:177-186`'s comment is rewritten: remove the "trap #11: DataPart.data is always a bare message array, never wrapped" framing; state the corrected object-wrapped convention and reference GH-128.
    - Consumer-side fix, console: `agent_sdk/console/static/chat.js:391` (`renderA2uiMessages(part.data, fallbackText)`) is updated to unwrap `part.data.messages` before rendering — mirroring the existing AG-UI CUSTOM handler at `chat.js:634` (`value.messages || []`).
    - Consumer-side fix, scripted test client: `agent_sdk/testing/chat.py::extract_a2ui()` (~line 396-398) is updated from `isinstance(p.get("data"), list)` / `result.append(p["data"])` to check `isinstance(p.get("data"), dict)` and append `p["data"].get("messages", [])` (guard against a missing/malformed key rather than raising).
    - Test updates — rewrite the three call sites that currently assert the bare-array shape to assert the wrapped-object shape instead, preserving every existing behavioral assertion (open/close split, verb ordering, deleteSurface isolation):
      - `tests/test_a2a.py` (~lines 44-65, the `kinds == ["text","data","data"]` test): `art["parts"][1]["data"]` / `art["parts"][2]["data"]` become `art["parts"][1]["data"]["messages"]` / `art["parts"][2]["data"]["messages"]`.
      - `tests/test_protocol_fixes_w6.py` (~lines 185-204): `isinstance(data_part.data, list)` → `isinstance(data_part.data, dict)` + `isinstance(data_part.data["messages"], list)`; update the `open_part.data` / `close_part.data` indexing accordingly.
      - `tests/test_protocol_wire.py` (~lines 290-315): same pattern — `isinstance(data_part.data, list)` → object-with-`messages`-key assertion; update `len(open_part.data)` → `len(open_part.data["messages"])` etc.
    - `~/.claude/agents/a2ui-advisor.md:727` (the "DataPart wire format" section and the erroneous MUST-be-array rule) is corrected to show the wrapped-object shape (`{"kind": "data", "data": {"messages": [...]}, "metadata": {...}}`) and to state `data` MUST be a JSON object whose `messages` key holds the array — matching both the corrected A2A behavior and the AG-UI convention already documented immediately below it in the same file. This is a knowledge-file correction, not a scope violation — the file's own erroneous claim is the root cause being fixed.
    - `CHANGELOG.md`'s existing `## [0.5.44]` → "🟡 Protocol surface changes" `split_a2ui_delivery()` entry is updated (not duplicated — this fixes a not-yet-tagged, in-flight description) to describe the corrected `{"messages": [...]}`-wrapped DataPart shape, and notes the bare-array shape was caught by `/sdk-test` Leg 3 before release and fixed under GH-128.
    - Full `tests/` suite green, `mypy agent_sdk/` clean, after the change.
  - GH: https://github.com/wailuen/a2a-sdk/issues/128
