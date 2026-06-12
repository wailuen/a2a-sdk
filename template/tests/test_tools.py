"""Domain tool tests — script the model, stub the adapter, assert artifacts."""

from __future__ import annotations

import uuid

from agent_sdk.testing import reply, tool_call

from src.sources.sample_api import SampleApiAdapter

from .conftest import wait_for_state


def send_body(text: str) -> dict:
    return {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            "messageId": uuid.uuid4().hex,
        }
    }


async def fake_get_widget(self, widget_id: str) -> dict:
    return {"id": widget_id, "status": "active", "score": 87}


async def test_widget_kpis_emits_card(client, fake_model, monkeypatch):
    monkeypatch.setattr(SampleApiAdapter, "get_widget", fake_get_widget)
    fake_model.script(
        tool_call("widget_kpis", {"widget_id": "w-1"}),
        reply("Widget w-1 is active."),
    )
    r = await client.post("/v1/message:send", json=send_body("brief me on w-1"))
    assert r.status_code == 200, r.text
    done = await wait_for_state(client, r.json()["id"])
    assert done["status"]["state"] == "completed"
    art = done["artifacts"][0]
    assert art["metadata"]["data_type"] == "kpi_card"


async def test_get_widget_tool(client, fake_model, monkeypatch):
    monkeypatch.setattr(SampleApiAdapter, "get_widget", fake_get_widget)
    fake_model.script(
        tool_call("get_widget", {"widget_id": "w-2"}),
        reply("Found it."),
    )
    r = await client.post("/v1/message:send", json=send_body("get widget w-2"))
    done = await wait_for_state(client, r.json()["id"])
    assert done["status"]["state"] == "completed"
