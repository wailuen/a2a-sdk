"""AG-UI surface conformance (DESIGN.md §5.3)."""

from __future__ import annotations

from agent_sdk.testing import reply, tool_call

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

    customs = {f["name"]: f["value"] for f in frames if f["type"] == "CUSTOM"}
    assert set(customs) == {"AGENT_ARTIFACT", "A2UI_UPDATE"}
    assert customs["AGENT_ARTIFACT"]["dataType"] == "kpi_card"
    assert customs["AGENT_ARTIFACT"]["toolName"] == "demo_kpis"
    verbs = [next(k for k in m if k != "version") for m in customs["A2UI_UPDATE"]["messages"]]
    assert verbs == ["createSurface", "updateComponents", "updateDataModel", "deleteSurface"]


async def test_interrupt_outcome_and_resume(client, fake_model):
    fake_model.script(tool_call("publish_note", {"note": "n"}), reply("after resume"))
    frames = await run(client, run_body("publish"))
    finished = frames[-1]
    assert finished["type"] == "RUN_FINISHED"
    outcome = finished["outcome"]
    assert outcome["type"] == "interrupt"
    intr = outcome["interrupts"][0]
    assert intr["id"] and intr["toolCallId"] and intr["responseSchema"]

    frames = await run(
        client,
        run_body(resume=[{"interrupt_id": intr["id"], "status": "resolved", "payload": {"decision": "approved"}}]),
    )
    types = [f["type"] for f in frames]
    assert types[-1] == "RUN_FINISHED"
    assert "TOOL_CALL_RESULT" in types  # the resumed tool's confirmed result
    assert "TEXT_MESSAGE_CONTENT" in types


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
    # rejection (those are synthesized before _validate runs, GH-97).
    r = await client.post("/ag-ui/run", json={"runId": "r1"})
    frames = sse_frames(r.text)
    assert [f["type"] for f in frames[:2]] == ["RUN_STARTED", "STATE_SNAPSHOT"]
    assert frames[-1]["type"] == "RUN_ERROR"
    assert frames[-1]["message"] == "no user message in input"

    r = await client.post(
        "/ag-ui/run",
        json=run_body("bad\x07control"),
    )
    frames = sse_frames(r.text)
    assert frames[-1]["type"] == "RUN_ERROR"
    assert "control" in frames[-1]["message"]


async def test_requires_auth(client):
    r = await client.post("/ag-ui/run", json=run_body(), headers={"Authorization": ""})
    assert r.status_code == 401
