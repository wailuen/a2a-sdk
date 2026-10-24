"""GH-195 — ChatDriver.agui_resume() resumes an AG-UI interrupt."""

from __future__ import annotations

import uuid

from agent_sdk.testing import reply, tool_call
from agent_sdk.testing.chat import ChatDriver


async def test_agui_resume_completes_interrupted_tool(client, fake_model):
    fake_model.script(tool_call("publish_note", {"note": "test"}), reply("after resume"))
    driver = ChatDriver(client)
    thread_id = uuid.uuid4().hex
    messages: list[dict] = []
    interrupts: list[dict] = []

    await driver.agui_turn(
        "publish something", thread_id, messages,
        emit={"interrupt": interrupts.append},
    )
    assert len(interrupts) == 1
    interrupt_id = interrupts[0]["id"]
    assert interrupt_id

    before = list(messages)
    tool_done: list[int] = []
    errors: list[str] = []
    text = await driver.agui_resume(
        interrupt_id, thread_id, messages,
        status="resolved", payload={"decision": "approved"},
        emit={"tool_done": lambda: tool_done.append(1), "error": errors.append},
    )

    assert errors == []
    assert tool_done == [1]
    assert text == "after resume"
    tool_result = fake_model.calls[-1]["messages"][-1]["content"][0]["toolResult"]
    assert tool_result["content"] == [{"json": {"published": True, "note": "test"}}]
    assert [m for m in messages if m["role"] == "user"] == [
        m for m in before if m["role"] == "user"
    ]
    assert {k: v for k, v in messages[-1].items() if k != "id"} == {"role": "assistant", "content": "after resume"}
    assert messages[-1]["id"]


async def test_agui_resume_unknown_id_fires_error(client, fake_model):
    driver = ChatDriver(client)
    errors: list[str] = []
    messages: list[dict] = []
    await driver.agui_resume(
        "no-such-interrupt", uuid.uuid4().hex, messages,
        payload={"decision": "approved"},
        emit={"error": errors.append},
    )
    assert errors and "interrupt" in errors[0]
    assert messages == []
