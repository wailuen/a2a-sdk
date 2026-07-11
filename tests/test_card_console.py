"""Agent card (§4.5), console contract assertions (§5.3/§7)."""

from __future__ import annotations

import re
from pathlib import Path

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

    RT-003 (source-text pin, no JS runtime available — see the assistant-turn
    fold test above for the same caveat): tolerates whitespace/comment
    reformatting but cannot distinguish `{ decision: text }` from a
    behavior-preserving wrapper.
    """
    chat_js = (CONSOLE_STATIC / "chat.js").read_text()

    resume_body = re.search(
        r"resume:\s*\[\{([\s\S]*?)\}\]",
        chat_js,
    )
    assert resume_body, "AG-UI resume body (`resume: [{...}]`) not found in chat.js"
    body_expr = re.sub(r"//.*", "", resume_body.group(1))
    body_expr = re.sub(r"\s+", " ", body_expr).strip()
    assert re.search(r"payload:\s*\{\s*decision:\s*text\s*\}", body_expr), (
        "AG-UI resume payload must be an object carrying `decision` (e.g. "
        "`payload: { decision: text }`), not a bare string — gate.py's "
        f"parse_decision() silently discards non-dict payloads; got: {body_expr!r}"
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
