"""Agent card (§4.5), console contract assertions (§5.3/§7)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_sdk.routes.agent_card import CUSTOM_EVENTS

CONSOLE_STATIC = Path(__file__).parent.parent / "agent_sdk" / "console" / "static"
AG_UI_SRC = Path(__file__).parent.parent / "agent_sdk" / "routes" / "ag_ui.py"


async def test_card_shape(client):
    r = await client.get("/.well-known/agent-card.json")
    card = r.json()
    assert card["protocolVersion"] == "0.3.0"
    assert card["preferredTransport"] == "HTTP+JSON"
    # HTTP+JSON: clients append /v1/message:send etc. to url; url must be the server root, not the endpoint prefix
    assert not card["url"].endswith("/v1"), f"card url must be server root, not endpoint prefix: {card['url']}"
    assert card["url"].startswith("http"), f"card url must be absolute: {card['url']}"
    assert card["capabilities"]["streaming"] is True
    assert card["capabilities"]["pushNotifications"] is False
    assert card["supportsAuthenticatedExtendedCard"] is False
    exts = [e["uri"] for e in card["capabilities"]["extensions"]]
    assert "https://a2ui.org/a2a-extension/a2ui/v0.9.1" in exts
    assert "https://agent-sdk.dev/extensions/ag-ui-run/v1" in exts
    a2ui_ext = next(e for e in card["capabilities"]["extensions"] if e["uri"] == "https://a2ui.org/a2a-extension/a2ui/v0.9.1")
    params = a2ui_ext["params"]
    assert "urn:a2ui-profile:standard:v1" in params["supportedCatalogIds"]
    assert params["acceptsInlineCatalogs"] is False
    # GH-113 (superseded by the critical split-delivery fix, DESIGN.md
    # §5.4/§7.1): deleteSurface is always delivered as its own,
    # independently-folded message array — wire-discoverable via this hint.
    assert params["deleteSurfaceSemantics"] == "split-delivery"
    # skills carry only spec fields + x-sdk
    for skill in card["skills"]:
        bare = set(skill) - {
            "id", "name", "description", "tags", "examples",
            "inputModes", "outputModes", "security", "x-sdk",
        }
        assert not bare, bare
    assert card["x-agui"]["endpoint"].endswith("/ag-ui/run")
    # P6-01: customEvents are now objects with name + valueSchema (not flat strings)
    custom_event_names = {e["name"] for e in card["x-agui"]["customEvents"]}
    assert custom_event_names == set(CUSTOM_EVENTS)
    # never emit v1.0-only fields
    assert "supportedInterfaces" not in card


async def test_card_etag_and_alias(client):
    r = await client.get("/.well-known/agent-card.json")
    etag = r.headers["etag"]
    r304 = await client.get(
        "/.well-known/agent-card.json", headers={"If-None-Match": etag}
    )
    assert r304.status_code == 304
    alias = await client.get("/.well-known/agent.json")
    assert alias.content == r.content


def test_custom_events_match_console_routing_table():
    """§5.3: card customEvents and the console routing table are equal."""
    chat_js = (CONSOLE_STATIC / "chat.js").read_text()
    # Assert the executable render branch, not a bare name substring: every
    # CUSTOM_EVENTS name is also listed in the chat.js header comment (§5.3),
    # so `name in chat_js` alone passes on the comment even if the real
    # handleCustom() branch is deleted (LRN-102 recurrence). Each custom event
    # is routed by an `if (name === "<NAME>")` / `else if (name === "<NAME>")`
    # branch in handleCustom(), so anchor on that marker.
    for name in CUSTOM_EVENTS:
        assert f'name === "{name}"' in chat_js, (
            f"chat.js handleCustom() has no render branch for CUSTOM event {name} "
            "(header-comment mention does not count)"
        )
    # RT-001: native (non-CUSTOM) tool-call frame handlers must stay guarded
    # too, or their coverage silently disappears alongside the CUSTOM check.
    assert 'case "TOOL_CALL_ARGS"' in chat_js
    assert 'case "TOOL_CALL_END"' in chat_js


def test_custom_events_match_actually_emitted_events():
    """GH-98/RT-003: CUSTOM_EVENTS must equal the event names ag_ui.py actually
    emits, not just be self-consistent with the console — card-vs-emitted
    parity, so a new self._custom(...) call in ag_ui.py can't silently drift
    from the card. Also guards the extraction itself: every _custom( call
    site's name argument must be a bare string literal, so a future
    self._custom(name_var, ...) or f-string call can't escape detection and
    turn this into a false-green pass (the original LRN-102 drift failure
    mode, one level removed)."""
    ag_ui_src = AG_UI_SRC.read_text()
    call_sites = re.findall(r"self\._custom\(\s*([^,]+?),", ag_ui_src, re.DOTALL)
    assert call_sites, "no _custom( call sites found in ag_ui.py — regex or file moved?"

    bare_literal = re.compile(r'^"[A-Z0-9_]+"$')
    non_literal = [c.strip() for c in call_sites if not bare_literal.match(c.strip())]
    assert not non_literal, (
        "every self._custom(...) call site must pass a bare string-literal "
        "name argument so it can be statically verified against "
        f"CUSTOM_EVENTS; found non-literal argument(s): {non_literal}"
    )

    emitted = {c.strip().strip('"') for c in call_sites}
    assert emitted == set(CUSTOM_EVENTS)


def test_agui_assistant_turn_fold_uses_plain_string_content():
    """Per the AG-UI spec, only UserMessage.content is Union[str, List[InputContent]];
    AssistantMessage inherits BaseMessage.content: Optional[str] — a plain string.
    The console's TEXT_MESSAGE_END handler folds the assistant turn back into
    state.aguiMessages and must use a plain string, not the list-of-parts shape
    (which is legitimate only for the user-turn fold).

    RT-003: this is a source-text pin, not a behavioral test — pytest has no JS
    runtime to execute chat.js and assert on the resulting state.aguiMessages
    entry directly. The regex below tolerates whitespace/newline reformatting
    and trailing comments around the `content:` expression so a cosmetic
    reformat doesn't false-fail; it still cannot distinguish `buf.text()` from
    a behavior-preserving wrapper (e.g. a helper that also returns a string),
    which is an accepted gap until a JS test harness exists — at that point
    replace this with a live TEXT_MESSAGE_END drive asserting
    `typeof content === 'string'` on the folded message.
    """
    chat_js = (CONSOLE_STATIC / "chat.js").read_text()

    assistant_fold = re.search(
        r'role:\s*"assistant",\s*content:\s*([\s\S]*?)\s*\}\);',
        chat_js,
    )
    assert assistant_fold, "assistant-turn fold (role: \"assistant\") not found in chat.js"
    content_expr = assistant_fold.group(1).strip()
    content_expr = re.sub(r"/\*.*?\*/", "", content_expr, flags=re.DOTALL)
    content_expr = re.sub(r"//.*", "", content_expr)
    content_expr = re.sub(r"\s+", " ", content_expr).strip()
    assert content_expr == "buf.text()", (
        "assistant-turn fold must use a plain string content (buf.text()), not a "
        f"list-of-parts shape; got: {content_expr!r}"
    )

    user_fold = re.search(
        r'role:\s*"user",\s*content:\s*(\[[^\]]+\])\s*\}\);',
        chat_js,
    )
    assert user_fold, "user-turn fold (role: \"user\") must keep its list-of-parts content shape"


def test_agui_resume_payload_matches_action_gate_contract():
    """The AG-UI resume body's `payload` must be an object carrying `decision`,
    not a bare string. `agent_sdk/contrib/action_gate/gate.py::parse_decision()`
    only reads a decision out of `resume_value["payload"]["decision"]` when
    `payload` is itself a dict (`payload = raw_payload if isinstance(raw_payload,
    dict) else None`); a bare-string payload is silently discarded and the
    resume falls through to Outcome.UNCLEAR regardless of the user's actual
    intent, breaking every action_gate-gated tool confirmation driven from the
    console's AG-UI tab.

    GH-216: the payload is now built by `buildResumePayload()` in
    interrupt.js from the interrupt's responseSchema. With no schema (or the
    action_gate confirm schema, whose sole property is `decision`) it still
    yields `{ decision: text }`; tests/test_gh216_console_interrupt_schema.py
    runs that under node. This pin checks the wiring: chat.js sends the
    builder's (object) payload, and the no-schema fallback stays a
    `decision` object.
    """
    chat_js = (CONSOLE_STATIC / "chat.js").read_text()
    interrupt_js = (CONSOLE_STATIC / "interrupt.js").read_text()

    resume_body = re.search(
        r"resume:\s*\[\{([\s\S]*?)\}\]",
        chat_js,
    )
    assert resume_body, "AG-UI resume body (`resume: [{...}]`) not found in chat.js"
    body_expr = re.sub(r"//.*", "", resume_body.group(1))
    body_expr = re.sub(r"\s+", " ", body_expr).strip()
    assert re.search(r"\bpayload\b", body_expr), (
        f"AG-UI resume body must carry `payload`; got: {body_expr!r}"
    )
    assert re.search(r"buildResumePayload\(\s*responseSchema\s*,\s*text\s*\)", chat_js), (
        "chat.js must build the resume payload via buildResumePayload(responseSchema, text)"
    )
    assert re.search(r"payload:\s*\{\s*decision:\s*text\s*\}", interrupt_js), (
        "interrupt.js buildResumePayload() must fall back to `{ decision: text }` "
        "— gate.py's parse_decision() silently discards non-dict payloads"
    )


def test_handle_a2a_artifact_guards_malformed_a2ui_datapart():
    """RT-004: handleA2aArtifact() must not silently no-op or throw when an
    A2UI DataPart arrives in an unexpected shape (legacy bare-array payload,
    or `part.data` null/undefined). It must emit a systemLine diagnosing the
    shape mismatch before falling back to an empty messages list, so a
    cross-version consumer's silence is debuggable instead of indistinguishable
    from an intentionally-empty A2UI payload.

    RT-003-style source-text pin (no JS runtime available in this test): anchors
    on the guard existing ahead of the render call, not on live DOM output —
    the "── live node cross-check" section below closes that gap for the
    environments that have node.

    RT-003 (redteam): the null/undefined-`part.data` case is deliberately
    NOT pinned here via an exact-spelling regex (e.g.
    `part.data && Array.isArray(part.data.messages)`) — that would couple
    the test to one JS spelling of the guard and false-fail a
    behavior-preserving refactor (optional chaining, a hoisted helper,
    etc.). That case is instead verified behaviorally by the "null-data"
    case of test_handle_a2a_artifact_malformed_datapart_live_behavior
    below, which executes the real function under node.
    """
    chat_js = (CONSOLE_STATIC / "chat.js").read_text()

    handler = re.search(
        r"function handleA2aArtifact\(artifact\) \{([\s\S]*?)\n  \}\n",
        chat_js,
    )
    assert handler, "handleA2aArtifact() not found in chat.js"
    body = handler.group(1)

    assert re.search(r"Array\.isArray\(part\.data\.messages\)", body), (
        "handleA2aArtifact must guard the A2UI DataPart with "
        "Array.isArray(part.data.messages) before indexing into part.data"
    )
    assert "systemLine(" in body and "unexpected shape" in body, (
        "handleA2aArtifact must emit a systemLine diagnosing an A2UI "
        "DataPart shape mismatch, distinguishing it from an intentionally-"
        "empty payload"
    )


def test_handle_a2a_artifact_falls_through_on_empty_messages_array():
    """RT-003 (w038 group G, budget-exhausted): a well-formed-but-empty A2UI
    DataPart (`data: {"messages": []}`) must NOT be treated as rendered.
    `Array.isArray([])` is true, so a guard that only checks
    `Array.isArray(part.data.messages)` sets `renderedA2ui = true` for an
    empty array — `renderA2uiMessages([])` paints nothing, so this silently
    suppresses the TextPart fallback bubble with no visible output and no
    systemLine. This SDK's own outbound path never emits an empty array, but
    a third-party A2A server could. The fix gates `renderedA2ui` on a
    non-empty array and emits a systemLine for the empty case, distinct from
    the "unexpected shape" (malformed) diagnostic.

    Source-text pin (no JS runtime available in this test): anchors on the
    emptiness gate and the distinct diagnostic message, not on live DOM
    output — the "── live node cross-check" section below closes that gap
    for the environments that have node.
    """
    chat_js = (CONSOLE_STATIC / "chat.js").read_text()

    handler = re.search(
        r"function handleA2aArtifact\(artifact\) \{([\s\S]*?)\n  \}\n",
        chat_js,
    )
    assert handler, "handleA2aArtifact() not found in chat.js"
    body = handler.group(1)

    assert re.search(r"msgs\s*&&\s*msgs\.length", body), (
        "handleA2aArtifact must gate renderedA2ui on a non-empty messages "
        "array (e.g. `msgs && msgs.length`), not just Array.isArray(...) — "
        "an empty-but-well-formed messages array must not set renderedA2ui"
    )
    assert "is empty" in body, (
        "handleA2aArtifact must emit a distinct systemLine for a well-formed "
        "but empty messages array, so it isn't indistinguishable from a "
        "malformed-shape DataPart"
    )


# ── RT-004: live node cross-check of handleA2aArtifact ───────────────────────
#
# The two source-text pins above anchor on specific substrings existing in
# chat.js, not on what handleA2aArtifact() actually does at runtime — a
# refactor that kept the matched substrings but broke the branch logic behind
# them would still pass. The tests below close that gap the same way
# test_a2ui_wire.py's live pointerSet cross-check does: extract the real
# function body from the real chat.js and execute it under node at test time
# (with the DOM/render surface it calls out to stubbed to record calls),
# asserting on the actual recorded behavior instead of the source text.

_NODE_BIN = shutil.which("node")

# RT-003 (test_a2ui_wire.py precedent): every live cross-check test below is
# skipif(_NODE_BIN is None), so a CI runner without node on PATH leaves all of
# them silently skipped. CI is expected to always provide node, so the skip
# there must be a loud failure, not a quiet pass — mirrors
# test_live_pointer_set_cross_check_available_in_ci.
_IN_CI = os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}


def test_live_handle_a2a_artifact_cross_check_available_in_ci():
    """RT-004: the live handleA2aArtifact() cross-check tests must not be able
    to silently skip in CI. Locally (not CI), skip when node is absent —
    that's a legitimate dev-machine gap, closed by the source-text pins above.
    In CI, node missing must fail loudly here instead of letting every
    skipif(_NODE_BIN is None) test below quietly disappear."""
    if not _IN_CI:
        pytest.skip("not running in CI; local runs may lack node")
    assert _NODE_BIN is not None, (
        "node is required in CI to run the live handleA2aArtifact() "
        "cross-check (RT-004) — install node in the CI image; do not let "
        "the behavioral guarantee silently skip"
    )


def _extract_handle_a2a_artifact_source(chat_js: str) -> str:
    handler = re.search(
        r"function handleA2aArtifact\(artifact\) \{([\s\S]*?)\n  \}\n",
        chat_js,
    )
    assert handler, "handleA2aArtifact() not found in chat.js"
    return f"function handleA2aArtifact(artifact) {{{handler.group(1)}\n  }}"


def _run_handle_a2a_artifact(chat_js: str, artifact: dict) -> dict:
    """Runs the real handleA2aArtifact() body under node, with the DOM/render
    surface it calls out to (systemLine, renderA2uiMessages, bubble, attach,
    el, fmtJson) stubbed to record calls instead of touching a DOM. Returns
    the recorded call log so callers can assert on actual runtime behavior —
    whether renderA2uiMessages fired, what systemLine said, what bubble was
    called with — not just on source text."""
    assert _NODE_BIN is not None, "caller must skip when node is unavailable"
    fn_src = _extract_handle_a2a_artifact_source(chat_js)
    script = (
        "const calls = { systemLines: [], rendered: false, bubbleCalls: [] };\n"
        "function systemLine(msg) { calls.systemLines.push(msg); }\n"
        "function renderA2uiMessages(msgs, fallback) { calls.rendered = true; }\n"
        "function bubble(role, text) { calls.bubbleCalls.push([role, text]); }\n"
        "function attach(x) {}\n"
        "function el() { return {}; }\n"
        "function fmtJson(x) { return JSON.stringify(x); }\n"
        f"{fn_src}\n"
        f"handleA2aArtifact({json.dumps(artifact)});\n"
        "process.stdout.write(JSON.stringify(calls));\n"
    )
    result = subprocess.run(
        [_NODE_BIN, "-e", script],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed; cannot cross-check against chat.js")
@pytest.mark.parametrize(
    "label,malformed_data",
    [
        ("wrong-shape-object", {"notMessages": []}),
        ("null-data", None),
    ],
)
def test_handle_a2a_artifact_malformed_datapart_live_behavior(label, malformed_data):
    """RT-004 live counterpart of test_handle_a2a_artifact_guards_malformed_a2ui_datapart:
    executes the real handleA2aArtifact() against several malformed A2UI
    DataPart shapes and asserts on the actual recorded behavior —
    renderA2uiMessages never fires, an "unexpected shape" systemLine is
    emitted, and the TextPart fallback bubble actually fires — instead of
    only pattern-matching the source text."""
    chat_js = (CONSOLE_STATIC / "chat.js").read_text()
    artifact = {
        "parts": [
            {"kind": "text", "text": "fallback bubble text"},
            {
                "kind": "data",
                "metadata": {"mimeType": "application/a2ui+json"},
                "data": malformed_data,
            },
        ]
    }
    calls = _run_handle_a2a_artifact(chat_js, artifact)
    assert calls["rendered"] is False, (
        f"{label}: renderA2uiMessages must not fire for malformed data={malformed_data!r}"
    )
    assert any("unexpected shape" in line for line in calls["systemLines"]), (
        f"{label}: expected an 'unexpected shape' systemLine for malformed "
        f"data={malformed_data!r}, got {calls['systemLines']!r}"
    )
    assert calls["bubbleCalls"] == [["agent", "fallback bubble text"]], (
        f"{label}: TextPart fallback must actually fire for malformed "
        f"data={malformed_data!r}, got {calls['bubbleCalls']!r}"
    )


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed; cannot cross-check against chat.js")
def test_handle_a2a_artifact_empty_messages_array_live_behavior():
    """RT-004/RT-003 live counterpart of
    test_handle_a2a_artifact_falls_through_on_empty_messages_array: executes
    the real handleA2aArtifact() against a well-formed-but-empty
    `messages: []` A2UI DataPart and asserts on the actual recorded
    behavior — renderA2uiMessages never fires (renderedA2ui truly stays
    false), an "is empty" systemLine is emitted, and the TextPart fallback
    bubble actually fires — instead of only pattern-matching the source
    text."""
    chat_js = (CONSOLE_STATIC / "chat.js").read_text()
    artifact = {
        "parts": [
            {"kind": "text", "text": "fallback bubble text"},
            {
                "kind": "data",
                "metadata": {"mimeType": "application/a2ui+json"},
                "data": {"messages": []},
            },
        ]
    }
    calls = _run_handle_a2a_artifact(chat_js, artifact)
    assert calls["rendered"] is False, (
        "renderA2uiMessages must not fire for an empty messages array"
    )
    assert any("is empty" in line for line in calls["systemLines"]), (
        f"expected an 'is empty' systemLine for an empty messages array, got {calls['systemLines']!r}"
    )
    assert calls["bubbleCalls"] == [["agent", "fallback bubble text"]], (
        f"TextPart fallback must actually fire when the A2UI messages array is empty, got {calls['bubbleCalls']!r}"
    )


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed; cannot cross-check against chat.js")
def test_handle_a2a_artifact_well_formed_messages_live_behavior():
    """RT-001 (w038 group G): handleA2aArtifact() had no executing happy-path test —
    every live cross-check above only exercises rejection paths (malformed
    shape, empty messages array), all of which assert `rendered is False`.
    Feed a well-formed, non-empty `data: {"messages": [...]}` A2UI DataPart
    alongside a TextPart fallback and assert the actual runtime behavior of
    the success path: renderA2uiMessages fires with the unwrapped array
    (`rendered is True`), no "empty"/"unexpected shape" diagnostic is
    emitted, and — critically — the TextPart fallback bubble is SUPPRESSED
    (`bubbleCalls == []`), not double-rendered alongside the A2UI surface."""
    chat_js = (CONSOLE_STATIC / "chat.js").read_text()
    messages = [{"createSurface": {"surfaceId": "s1", "root": {}}}]
    artifact = {
        "parts": [
            {"kind": "text", "text": "fallback bubble text"},
            {
                "kind": "data",
                "metadata": {"mimeType": "application/a2ui+json"},
                "data": {"messages": messages},
            },
        ]
    }
    calls = _run_handle_a2a_artifact(chat_js, artifact)
    assert calls["rendered"] is True, (
        f"renderA2uiMessages must fire for a well-formed non-empty messages array, got {calls!r}"
    )
    assert not any(
        "empty" in line or "unexpected shape" in line for line in calls["systemLines"]
    ), (
        "no 'empty'/'unexpected shape' diagnostic must be emitted on the "
        f"well-formed happy path, got {calls['systemLines']!r}"
    )
    assert calls["bubbleCalls"] == [], (
        "the TextPart fallback bubble must be SUPPRESSED once A2UI actually "
        f"renders — double-render regression, got {calls['bubbleCalls']!r}"
    )


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed; cannot cross-check against chat.js")
def test_handle_a2a_artifact_accepts_bare_array_datapart_live_behavior():
    """RT-002 (w038 group G): A2UI v0.9.1's own A2A binding says `DataPart.data` MUST
    be a bare array of messages (verified via gh api against the pinned
    v0_9_1 spec tag — see LRN-134); this SDK's own producer emits the
    object-wrapped `{"messages": [...]}` shape instead (GH-128, locked,
    REVIEWS.md Round 6), but a strictly spec-conformant THIRD-PARTY A2UI
    producer emits the bare array. The console consumer must tolerate both
    shapes on read (harness/agents/a2ui-advisor.md:721 prescribes exactly
    this tolerant-consumer pattern) — a bare-array DataPart must render, not
    fall into the 'unexpected shape' rejection path."""
    chat_js = (CONSOLE_STATIC / "chat.js").read_text()
    messages = [{"createSurface": {"surfaceId": "s1", "root": {}}}]
    artifact = {
        "parts": [
            {"kind": "text", "text": "fallback bubble text"},
            {
                "kind": "data",
                "metadata": {"mimeType": "application/a2ui+json"},
                "data": messages,
            },
        ]
    }
    calls = _run_handle_a2a_artifact(chat_js, artifact)
    assert calls["rendered"] is True, (
        f"renderA2uiMessages must fire for a spec-conformant bare-array DataPart, got {calls!r}"
    )
    assert not any(
        "unexpected shape" in line for line in calls["systemLines"]
    ), (
        f"a bare-array DataPart is a valid A2UI v0.9.1 shape, not 'unexpected shape', got {calls['systemLines']!r}"
    )
    assert calls["bubbleCalls"] == [], (
        f"the TextPart fallback bubble must be suppressed once the bare array renders, got {calls['bubbleCalls']!r}"
    )


# ── RT-001: AG-UI A2UI_UPDATE consumer parity with handleA2aArtifact ─────────
#
# handleA2aArtifact (the A2A DataPart delivery path) is pinned above to guard a
# malformed/empty A2UI payload and emit a systemLine diagnostic. The AG-UI
# CUSTOM `A2UI_UPDATE` branch in handleCustom() is the SIBLING A2UI delivery
# path in the same consumer; it was left rendering `value.messages || []` with
# no guard and no diagnostic — an asymmetric silent-failure twin. These tests
# pin the parity so it cannot regress.


def test_handle_custom_a2ui_update_guards_malformed_value():
    """RT-001: the A2UI_UPDATE branch of handleCustom() must not silently
    render nothing for a value that carries no messages array. It must emit a
    systemLine diagnosing the shape, matching handleA2aArtifact's A2A-path
    guard so the two A2UI delivery paths are symmetrically hardened."""
    chat_js = (CONSOLE_STATIC / "chat.js").read_text()
    handler = re.search(r"function handleCustom\(frame\) \{([\s\S]*?)\n  \}\n", chat_js)
    assert handler, "handleCustom() not found in chat.js"
    body = handler.group(1)
    branch = re.search(
        r'name === "A2UI_UPDATE"\) \{([\s\S]*?)\} else if \(name === "AGENT_PROGRESS"',
        body,
    )
    assert branch, "A2UI_UPDATE branch not found in handleCustom()"
    branch_src = branch.group(1)
    assert "systemLine(" in branch_src and "unexpected shape" in branch_src, (
        "A2UI_UPDATE branch must emit a systemLine diagnosing a value with no "
        "renderable messages array, mirroring handleA2aArtifact"
    )
    assert "is empty" in branch_src, (
        "A2UI_UPDATE branch must emit a distinct systemLine for a well-formed "
        "but empty messages array"
    )


def _extract_handle_custom_source(chat_js: str) -> str:
    handler = re.search(r"function handleCustom\(frame\) \{([\s\S]*?)\n  \}\n", chat_js)
    assert handler, "handleCustom() not found in chat.js"
    return f"function handleCustom(frame) {{{handler.group(1)}\n  }}"


def _run_handle_custom(chat_js: str, frame: dict) -> dict:
    """Runs the real handleCustom() body under node with its DOM/render surface
    stubbed to record calls, returning the recorded call log."""
    assert _NODE_BIN is not None, "caller must skip when node is unavailable"
    fn_src = _extract_handle_custom_source(chat_js)
    script = (
        "const calls = { systemLines: [], rendered: false, renderedMsgs: null };\n"
        "function systemLine(msg) { calls.systemLines.push(msg); }\n"
        "function renderA2uiMessages(msgs, fallback) { calls.rendered = true; calls.renderedMsgs = msgs; }\n"
        "function attach(x) {}\n"
        "function el() { return {}; }\n"
        "function fmtJson(x) { return JSON.stringify(x); }\n"
        f"{fn_src}\n"
        f"handleCustom({json.dumps(frame)});\n"
        "process.stdout.write(JSON.stringify(calls));\n"
    )
    result = subprocess.run(
        [_NODE_BIN, "-e", script],
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    return json.loads(result.stdout)


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed; cannot cross-check against chat.js")
@pytest.mark.parametrize(
    "label,value",
    [
        ("wrong-shape-object", {"notMessages": []}),
        ("missing-value", {}),
        ("empty-messages", {"messages": []}),
    ],
)
def test_handle_custom_a2ui_update_malformed_live_behavior(label, value):
    """RT-001 live counterpart: the real A2UI_UPDATE branch must not fire
    renderA2uiMessages for a value with no renderable/non-empty messages array,
    and must emit a diagnostic systemLine — no silent no-op."""
    chat_js = (CONSOLE_STATIC / "chat.js").read_text()
    frame = {"type": "CUSTOM", "name": "A2UI_UPDATE", "value": value}
    calls = _run_handle_custom(chat_js, frame)
    assert calls["rendered"] is False, (
        f"{label}: renderA2uiMessages must not fire for value={value!r}"
    )
    assert any(
        "unexpected shape" in line or "is empty" in line for line in calls["systemLines"]
    ), (
        f"{label}: expected a diagnostic systemLine for value={value!r}, "
        f"got {calls['systemLines']!r}"
    )


@pytest.mark.skipif(_NODE_BIN is None, reason="node is not installed; cannot cross-check against chat.js")
@pytest.mark.parametrize(
    "label,value",
    [
        ("object-wrapped", {"messages": [{"createSurface": {"surfaceId": "s1", "root": {}}}]}),
        ("bare-array", [{"createSurface": {"surfaceId": "s1", "root": {}}}]),
    ],
)
def test_handle_custom_a2ui_update_well_formed_live_behavior(label, value):
    """RT-001 live happy path: a well-formed A2UI_UPDATE value renders. Accepts
    both the canonical object-wrapped {messages:[...]} shape (this SDK's own
    A2UI_UPDATE valueSchema) and a spec-conformant third-party bare array,
    unwrapping to the messages array, with no diagnostic emitted."""
    chat_js = (CONSOLE_STATIC / "chat.js").read_text()
    frame = {"type": "CUSTOM", "name": "A2UI_UPDATE", "value": value}
    calls = _run_handle_custom(chat_js, frame)
    assert calls["rendered"] is True, (
        f"{label}: renderA2uiMessages must fire for a well-formed value={value!r}, got {calls!r}"
    )
    expected = value["messages"] if isinstance(value, dict) else value
    assert calls["renderedMsgs"] == expected, (
        f"{label}: renderA2uiMessages must receive the unwrapped messages array, "
        f"got {calls['renderedMsgs']!r}"
    )
    assert not any(
        "empty" in line or "unexpected shape" in line for line in calls["systemLines"]
    ), (
        f"{label}: no diagnostic must be emitted on the happy path, got {calls['systemLines']!r}"
    )


async def test_console_page_and_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    r = await client.get("/admin")
    assert r.status_code == 200
    csp = r.headers.get("content-security-policy", "")
    assert "script-src 'self'" in csp and "'unsafe-inline'" not in csp
    r = await client.get("/admin/static/console.js")
    assert r.status_code == 200
    # traversal blocked
    r = await client.get("/admin/static/../../config.py")
    assert r.status_code in (400, 404)


async def test_console_credentials_page_renders_oauth_idp_card(client):
    r = await client.get("/admin/static/console.js")
    assert r.status_code == 200
    assert "data.oauth_idp" in r.text
    assert "IdP sign-in (AGENT_SDK_OAUTH_IDP)" in r.text
