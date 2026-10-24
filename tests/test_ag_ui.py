"""AG-UI surface conformance (DESIGN.md §5.3)."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

from agent_sdk import BaseAgentSettings
from agent_sdk.example.agent import make_agent
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.tasks.store import TaskStore
from agent_sdk.testing import FakeModelClient, reply, tool_call

from .conftest import sse_frames


def run_body(text: str = "hello", **extra) -> dict:
    return {
        "threadId": "t1",
        "runId": "r1",
        "messages": [{"id": "m1", "role": "user", "content": text}],
        "state": {},
        "tools": [],
        "context": [],
        "forwardedProps": {},
        **extra,
    }


async def run(client, body) -> list[dict]:
    r = await client.post("/ag-ui/run", json=body)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    return sse_frames(r.text)


async def test_frame_order_and_steps(client, fake_model):
    fake_model.script(reply("hi there"))
    frames = await run(client, run_body())
    types = [f["type"] for f in frames]
    assert types[:2] == ["RUN_STARTED", "STATE_SNAPSHOT"]
    assert types[-1] == "RUN_FINISHED"
    assert types.count("RUN_FINISHED") + types.count("RUN_ERROR") == 1
    # every STEP_STARTED is closed
    assert types.count("STEP_STARTED") == types.count("STEP_FINISHED") == 1
    started = next(f for f in frames if f["type"] == "STEP_STARTED")
    assert started["stepName"] == "turn-1"
    # text triplet with one messageId
    triplet = [f for f in frames if f["type"].startswith("TEXT_MESSAGE")]
    assert [f["type"] for f in triplet] == [
        "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END",
    ]
    assert len({f["messageId"] for f in triplet}) == 1


async def test_tool_and_custom_events(client, fake_model):
    fake_model.script(tool_call("demo_kpis", {"title": "Q2"}), reply("done"))
    body = run_body("kpis", forwardedProps={"a2uiClientCapabilities": {"tier": "core"}})
    frames = await run(client, body)
    types = [f["type"] for f in frames]
    for t in ("TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_END", "TOOL_CALL_RESULT"):
        assert t in types, types
    result = next(f for f in frames if f["type"] == "TOOL_CALL_RESULT")
    start = next(f for f in frames if f["type"] == "TOOL_CALL_START")
    assert result["toolCallId"] == start["toolCallId"]
    assert result["messageId"] != result["toolCallId"]  # fresh UUID rule

    custom_frames = [f for f in frames if f["type"] == "CUSTOM"]
    names = [f["name"] for f in custom_frames]
    assert set(names) == {"AGENT_ARTIFACT", "A2UI_UPDATE"}
    agent_artifact = next(f["value"] for f in custom_frames if f["name"] == "AGENT_ARTIFACT")
    assert agent_artifact["dataType"] == "kpi_card"
    assert agent_artifact["toolName"] == "demo_kpis"

    # GH-214 ruling (https://github.com/wailuen/a2a-sdk/issues/214#issuecomment-6359828762):
    # exactly one A2UI_UPDATE per emission, no deleteSurface.
    a2ui_updates = [f["value"]["messages"] for f in custom_frames if f["name"] == "A2UI_UPDATE"]
    assert len(a2ui_updates) == 1, "no second A2UI_UPDATE close event (GH-214)"
    verbs = [next(k for k in m if k != "version") for m in a2ui_updates[0]]
    assert verbs == ["createSurface", "updateComponents", "updateDataModel"]
    assert names.index("AGENT_ARTIFACT") < names.index("A2UI_UPDATE")


async def test_interrupt_outcome_and_resume(client, fake_model):
    fake_model.script(tool_call("publish_note", {"note": "n"}), reply("after resume"))
    frames = await run(client, run_body("publish"))
    finished = frames[-1]
    assert finished["type"] == "RUN_FINISHED"
    outcome = finished["outcome"]
    assert outcome["type"] == "interrupt"
    intr = outcome["interrupts"][0]
    assert intr["id"] and intr["toolCallId"] and intr["responseSchema"]
    # ag-ui-protocol's Interrupt.expires_at is Optional[str] (ISO-8601), not
    # an epoch-ms int — a consumer parsing this through the reference
    # Pydantic model would fail validation on a non-string value.
    assert isinstance(intr["expiresAt"], str)
    assert intr["expiresAt"].endswith("Z")
    # interrupt_deadline is a time.monotonic() reading (arbitrary reference
    # point, often near process/system boot), not a Unix epoch offset — it
    # must be rebased to wall-clock before serialization, or a spec-strict
    # consumer parses a ~1970 timestamp and treats the interrupt as already
    # expired (RT-001).
    parsed = datetime.strptime(intr["expiresAt"], "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    now = datetime.now(tz=timezone.utc)
    # Assert on the epoch-timestamp window only. A calendar-field check like
    # `parsed.year == now.year` is fragile: `parsed` is now + interrupt_ttl
    # (~1800s), so an interrupt fired within the TTL of the UTC New Year rolls
    # `parsed` into the next year while `now.year` is still the old one — a
    # flake. The window below is the real, year-boundary-safe correctness check
    # (matches test_interrupt_expiry_is_clock_agnostic) (RT-001).
    assert now.timestamp() < parsed.timestamp() < now.timestamp() + 3600

    frames = await run(
        client,
        run_body(resume=[{"interrupt_id": intr["id"], "status": "resolved", "payload": {"decision": "approved"}}]),
    )
    types = [f["type"] for f in frames]
    assert types[-1] == "RUN_FINISHED"
    assert "TOOL_CALL_RESULT" in types  # the resumed tool's confirmed result
    assert "TEXT_MESSAGE_CONTENT" in types


async def test_interrupt_expiry_is_clock_agnostic(tmp_path):
    """RT-001: TaskStore.clock is injectable (a durable cross-process store
    would use time.time, not time.monotonic — memory.py:27). The route must
    not assume it read a monotonic value; expiresAt must land in the TTL
    window regardless of which clock the store uses internally."""
    settings = BaseAgentSettings(
        DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="test-agent"
    )
    fake_model = FakeModelClient()
    fake_model.script(tool_call("publish_note", {"note": "n"}))
    store = InMemoryTaskStore(clock=time.time)  # wall-clock, not monotonic
    app = make_agent(settings, model_client=fake_model, task_store=store).build_app()
    try:
        async with app.router.lifespan_context(app):
            _, token = app.state.auth.api_keys.mint("test-admin", admin=True)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers={"Authorization": f"Bearer {token}"},
            ) as client:
                r = await client.post("/ag-ui/run", json=run_body("publish"))
                assert r.status_code == 200, r.text
                intr = sse_frames(r.text)[-1]["outcome"]["interrupts"][0]
                parsed = datetime.strptime(
                    intr["expiresAt"], "%Y-%m-%dT%H:%M:%SZ"
                ).replace(tzinfo=timezone.utc)
                now = datetime.now(tz=timezone.utc)
                assert now.timestamp() < parsed.timestamp() < now.timestamp() + 3600
    finally:
        app.state.credential_store.close()


async def test_interrupt_omits_expires_at_for_pre_hook_task_store(tmp_path):
    """RT-002: TaskStore.interrupt_ttl_remaining is a new hook defaulting to
    None. An external TaskStore subclass written before this hook existed
    must still boot and serve interrupts — just without expiresAt on the
    wire, never a stale or fabricated value."""

    class _PreHookTaskStore(InMemoryTaskStore):
        interrupt_ttl_remaining = TaskStore.interrupt_ttl_remaining

    settings = BaseAgentSettings(
        DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="test-agent"
    )
    fake_model = FakeModelClient()
    fake_model.script(tool_call("publish_note", {"note": "n"}))
    store = _PreHookTaskStore()
    app = make_agent(settings, model_client=fake_model, task_store=store).build_app()
    try:
        async with app.router.lifespan_context(app):
            _, token = app.state.auth.api_keys.mint("test-admin", admin=True)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers={"Authorization": f"Bearer {token}"},
            ) as client:
                r = await client.post("/ag-ui/run", json=run_body("publish"))
                assert r.status_code == 200, r.text
                intr = sse_frames(r.text)[-1]["outcome"]["interrupts"][0]
                assert intr["id"]
                assert "expiresAt" not in intr
    finally:
        app.state.credential_store.close()


async def test_resume_identity_bound(client, fake_model):
    fake_model.script(tool_call("publish_note", {"note": "n"}))
    frames = await run(client, run_body("publish"))
    intr = frames[-1]["outcome"]["interrupts"][0]

    _, other = client.app.state.auth.api_keys.mint("other", admin=False)
    r = await client.post(
        "/ag-ui/run",
        json=run_body(resume=[{"interrupt_id": intr["id"], "status": "resolved", "payload": {"decision": "approved"}}]),
        headers={"Authorization": f"Bearer {other}"},
    )
    frames = sse_frames(r.text)
    assert frames[-1]["type"] == "RUN_ERROR"
    assert "interrupt" in frames[-1]["message"]


async def test_validation_inside_generator(client):
    # no "messages" key at all -> folds to no user message, not a threadId/runId
    # rejection (those are synthesized before _validate runs, GH-97). The point:
    # even a validation failure emits RUN_STARTED + STATE_SNAPSHOT first, then
    # the terminal RUN_ERROR — validation runs inside the generator.
    r = await client.post("/ag-ui/run", json={"runId": "r1"})
    frames = sse_frames(r.text)
    assert [f["type"] for f in frames[:2]] == ["RUN_STARTED", "STATE_SNAPSHOT"]
    assert frames[-1]["type"] == "RUN_ERROR"
    assert frames[-1]["message"] == "no user message in input"


async def test_control_chars_in_string_content_are_stripped(client, fake_model):
    # RT-001: content control chars are SANITIZED, never hard-rejected — a
    # rejection would brick the session once the poisoned turn is replayed.
    fake_model.script(reply("ok"))
    frames = await run(client, run_body("bad\x07control"))
    types = [f["type"] for f in frames]
    assert "RUN_ERROR" not in types
    assert types[-1] == "RUN_FINISHED"


async def test_control_chars_in_list_content_are_stripped(client, fake_model):
    # console's own user-turn fold (chat.js) sends multimodal list content
    # ([{type: "text", text}]); the sanitizer must cover it too, stripping
    # (not rejecting) any control char before it reaches the model (RT-001).
    fake_model.script(reply("ok"))
    body = run_body()
    body["messages"] = [
        {"id": "m1", "role": "user", "content": [{"type": "text", "text": "bad\x07control"}]}
    ]
    frames = await run(client, body)
    types = [f["type"] for f in frames]
    assert "RUN_ERROR" not in types
    assert types[-1] == "RUN_FINISHED"


async def test_dict_shaped_user_content_is_rejected_not_coerced(client, fake_model):
    # GH-159 (supersedes the old RT-001 "str()-coerce any shape" contract): a
    # user message whose content is a bare object, not a string or list of
    # parts, is rejected with RUN_ERROR. str()-coercing it would hand the
    # whole object — binary payload included — to the model as text. The
    # bundled console (chat.js) always sends user content as a list of text
    # parts, so this can never brick a replayed session.
    body = run_body()
    body["messages"] = [{"id": "m1", "role": "user", "content": {"text": "bad\x07control"}}]
    frames = await run(client, body)
    types = [f["type"] for f in frames]
    assert types[-1] == "RUN_ERROR"
    assert "RUN_FINISHED" not in types


async def test_dict_shaped_assistant_content_is_dropped_not_errored(client, fake_model):
    # A replayed assistant turn in an unexpected shape must not brick the
    # session (RT-001), and must not be str()-ed into model input either: it
    # folds to empty and is skipped as a blank assistant turn.
    fake_model.script(reply("ok"))
    body = run_body("again")
    body["messages"] = [
        {"id": "m1", "role": "user", "content": "hello"},
        {"id": "a1", "role": "assistant", "content": {"text": "bad\x07control"}},
        {"id": "m2", "role": "user", "content": "again"},
    ]
    frames = await run(client, body)
    types = [f["type"] for f in frames]
    assert "RUN_ERROR" not in types
    assert types[-1] == "RUN_FINISHED"


async def test_control_char_in_replayed_assistant_history_does_not_brick(client, fake_model):
    # RT-001 regression (the brick the prior fix rounds never closed): the
    # model legitimately emits an ANSI ESC; chat.js folds that assistant turn
    # back into history as plain-string content and re-submits the full history
    # on the NEXT turn. That replayed control char must not RUN_ERROR — else
    # every subsequent turn errors and the session is permanently bricked until
    # a manual Reset.
    fake_model.script(reply("second-turn ok"))
    body = run_body("continue")
    body["messages"] = [
        {"id": "m1", "role": "user", "content": [{"type": "text", "text": "hello"}]},
        {"id": "a1", "role": "assistant", "content": "answer \x1b[0m done"},
        {"id": "m2", "role": "user", "content": [{"type": "text", "text": "continue"}]},
    ]
    frames = await run(client, body)
    types = [f["type"] for f in frames]
    assert "RUN_ERROR" not in types, frames
    assert types[-1] == "RUN_FINISHED"


async def test_validation_handles_non_string_text_in_list_content(client, fake_model):
    # RT-001: a malformed multimodal part (null or non-string `text`) must
    # not crash the generator after RUN_STARTED — the text-extraction join
    # must be total, and the run must still end with exactly one terminal
    # frame rather than truncating the SSE stream.
    for bad_text in (None, 5):
        fake_model.script(reply("ok"))
        body = run_body()
        body["messages"] = [
            {"id": "m1", "role": "user", "content": [{"type": "text", "text": bad_text}]}
        ]
        r = await client.post("/ag-ui/run", json=body)
        assert r.status_code == 200, r.text
        frames = sse_frames(r.text)
        assert frames[0]["type"] == "RUN_STARTED"
        assert frames[1]["type"] == "STATE_SNAPSHOT"
        terminal_types = [f["type"] for f in frames if f["type"] in ("RUN_FINISHED", "RUN_ERROR")]
        assert len(terminal_types) == 1, frames
        assert frames[-1]["type"] in ("RUN_FINISHED", "RUN_ERROR")


async def test_requires_auth(client):
    r = await client.post("/ag-ui/run", json=run_body(), headers={"Authorization": ""})
    assert r.status_code == 401
