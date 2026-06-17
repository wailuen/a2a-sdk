"""GH-50: A2UI DataParts only emitted when X-A2A-Extensions opt-in header is present."""

from __future__ import annotations

import uuid

import pytest

from agent_sdk.models.content_types import A2UI_EXTENSION_URI
from agent_sdk.testing import reply, tool_call

from .conftest import wait_for_state


def send_body(text: str) -> dict:
    return {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            "messageId": uuid.uuid4().hex,
        }
    }


async def test_no_a2ui_without_extension_header(client, fake_model):
    """Without X-A2A-Extensions, artifacts must not carry A2UI DataParts."""
    fake_model.script(tool_call("demo_kpis", {"title": "Q2"}), reply("done"))
    r = await client.post("/v1/message:send", json=send_body("kpis"))
    assert r.status_code == 200
    task = r.json()

    done = await wait_for_state(client, task["id"])
    assert done["status"]["state"] == "completed"
    art = done["artifacts"][0]
    # Without opt-in, no A2UI MIME DataPart should be present
    mime_types = [
        p.get("metadata", {}).get("mimeType") for p in art["parts"] if p.get("kind") == "data"
    ]
    assert "application/a2ui+json" not in mime_types, (
        f"A2UI DataPart emitted without opt-in header: mimeTypes={mime_types}"
    )


async def test_a2ui_present_with_extension_header(client, fake_model):
    """With X-A2A-Extensions containing A2UI_EXTENSION_URI, A2UI DataPart is emitted."""
    fake_model.script(tool_call("demo_kpis", {"title": "Q2"}), reply("done"))
    r = await client.post(
        "/v1/message:send",
        json=send_body("kpis"),
        headers={"X-A2A-Extensions": A2UI_EXTENSION_URI},
    )
    assert r.status_code == 200
    task = r.json()

    done = await wait_for_state(client, task["id"])
    assert done["status"]["state"] == "completed"
    art = done["artifacts"][0]
    mime_types = [
        p.get("metadata", {}).get("mimeType") for p in art["parts"] if p.get("kind") == "data"
    ]
    assert "application/a2ui+json" in mime_types, (
        f"A2UI DataPart missing despite opt-in header: mimeTypes={mime_types}"
    )


async def test_a2ui_present_with_multi_extension_header(client, fake_model):
    """X-A2A-Extensions with multiple URIs (including A2UI) still gates correctly."""
    fake_model.script(tool_call("demo_kpis", {"title": "Q2"}), reply("done"))
    r = await client.post(
        "/v1/message:send",
        json=send_body("kpis"),
        headers={"X-A2A-Extensions": f"https://other.example/ext, {A2UI_EXTENSION_URI}"},
    )
    assert r.status_code == 200
    task = r.json()

    done = await wait_for_state(client, task["id"])
    assert done["status"]["state"] == "completed"
    art = done["artifacts"][0]
    mime_types = [
        p.get("metadata", {}).get("mimeType") for p in art["parts"] if p.get("kind") == "data"
    ]
    assert "application/a2ui+json" in mime_types, (
        f"A2UI DataPart missing when header has multiple URIs: mimeTypes={mime_types}"
    )
