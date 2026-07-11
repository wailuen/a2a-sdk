"""GH-97: threadId/runId synthesis must not be undone by _validate (DESIGN.md §5.3).

RUN_STARTED is always the first frame, carrying the synthesized ids when the
client omitted threadId/runId. _validate must not immediately reject the
still-raw body for the very fields the route already synthesized — that
would emit RUN_ERROR: "threadId is required"/"runId is required" right after
a RUN_STARTED that just claimed a valid id.
"""

from __future__ import annotations

from agent_sdk.testing import reply

from .conftest import sse_frames


def user_message(text: str = "hello") -> dict:
    return {"id": "m1", "role": "user", "content": text}


async def run(client, body) -> list[dict]:
    r = await client.post("/ag-ui/run", json=body)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    return sse_frames(r.text)


async def test_omitted_thread_and_run_id_are_synthesized_not_rejected(client, fake_model):
    fake_model.script(reply("hi there"))
    frames = await run(client, {"messages": [user_message()]})

    started = frames[0]
    assert started["type"] == "RUN_STARTED"
    assert isinstance(started["threadId"], str) and started["threadId"]
    assert isinstance(started["runId"], str) and started["runId"]

    assert frames[1]["type"] == "STATE_SNAPSHOT"

    types = [f["type"] for f in frames]
    assert "RUN_ERROR" not in types
    assert types[-1] == "RUN_FINISHED"
    finished = frames[-1]
    assert finished["threadId"] == started["threadId"]
    assert finished["runId"] == started["runId"]


async def test_empty_string_and_non_string_ids_are_synthesized_not_rejected(client, fake_model):
    fake_model.script(reply("hi there"))
    frames = await run(
        client, {"threadId": "", "runId": 12345, "messages": [user_message()]}
    )

    started = frames[0]
    assert started["type"] == "RUN_STARTED"
    assert isinstance(started["threadId"], str) and started["threadId"]
    assert isinstance(started["runId"], str) and started["runId"]

    types = [f["type"] for f in frames]
    assert "RUN_ERROR" not in types
    assert types[-1] == "RUN_FINISHED"


async def test_messages_must_still_be_a_list(client):
    r = await client.post("/ag-ui/run", json={"messages": "not-a-list"})
    frames = sse_frames(r.text)
    assert frames[-1]["type"] == "RUN_ERROR"
    assert frames[-1]["message"] == "messages must be a list"


async def test_control_characters_in_message_content_are_stripped_not_rejected(client, fake_model):
    # RT-001: content control chars must be SANITIZED, never hard-rejected.
    # The client re-submits the full history every turn (its own user turns +
    # the model's folded-back assistant turns), so a single control char that
    # rejected the run would permanently brick the session on replay. The run
    # must succeed with the char stripped from the model input.
    fake_model.script(reply("ok"))
    frames = await run(client, {"messages": [user_message("bad\x07control")]})
    types = [f["type"] for f in frames]
    assert "RUN_ERROR" not in types
    assert types[-1] == "RUN_FINISHED"
