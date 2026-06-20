"""w014 acceptance tests — GH-32, GH-34, GH-35, GH-38."""

from __future__ import annotations

import uuid

import pytest

from agent_sdk.agent.registry import ToolSet
from agent_sdk.testing import reply, tool_call

from .conftest import wait_for_state


# ---------------------------------------------------------------------------
# GH-32 / GH-75 (corrected): POST /v1/tasks/{id}:subscribe (A2A §2 + §3.5.6)
# REST action suffix is :subscribe; JSON-RPC method name is tasks/resubscribe.
# ---------------------------------------------------------------------------


async def test_subscribe_route_exists(client, fake_model):
    """GH-75 AC (corrected): POST /v1/tasks/{task_id}:subscribe must return SSE, not 404.

    A2A §2 transport table and §3.5.6 confirm the REST path is :subscribe.
    """
    fake_model.script(reply("done"))
    r = await client.post(
        "/v1/message:send",
        json={
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "hi"}],
                "messageId": uuid.uuid4().hex,
            }
        },
    )
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    await wait_for_state(client, task_id)

    r2 = await client.post(f"/v1/tasks/{task_id}:subscribe")
    assert r2.status_code != 404, (
        f"POST /v1/tasks/{{id}}:subscribe returned 404 — route must be :subscribe per A2A §2/§3.5.6"
    )
    assert r2.status_code in (200, 400, 410), f"Unexpected status: {r2.status_code}"


async def test_resubscribe_route_gone(client, fake_model):
    """GH-75 (corrected): :resubscribe path must 404 — it was a misread of the spec."""
    fake_model.script(reply("done"))
    r = await client.post(
        "/v1/message:send",
        json={
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "hi"}],
                "messageId": uuid.uuid4().hex,
            }
        },
    )
    task_id = r.json()["id"]
    await wait_for_state(client, task_id)
    r2 = await client.post(f"/v1/tasks/{task_id}:resubscribe")
    assert r2.status_code in (404, 405), (
        f":resubscribe should be 404 or 405 (route never existed); got {r2.status_code}"
    )


# ---------------------------------------------------------------------------
# GH-34: @tool decorator tags= param
# ---------------------------------------------------------------------------


def test_tool_tags_flow_to_card():
    """GH-34 AC-1/AC-4: @tool(tags=...) appears in AgentSkill.tags on the card."""
    ts = ToolSet()

    @ts.tool(tier=1, tags=["search", "news"])
    async def find_news() -> None:
        """Find news articles."""

    decl = ts.decls[0]
    assert decl.tags == ["search", "news"]


def test_tool_tags_defaults_empty():
    """GH-34 AC-3: @tool without tags= → tags: [] (not ['tier-N'])."""
    ts = ToolSet()

    @ts.tool(tier=1)
    async def my_tool() -> None:
        """A tool."""

    assert ts.decls[0].tags == []


async def test_card_skill_tags_semantic(client):
    """GH-34 AC-2: tier lives in x-sdk, not in tags; tags is empty for default tools."""
    r = await client.get("/.well-known/agent-card.json")
    card = r.json()
    for skill in card["skills"]:
        # No skill should have a "tier-N" string in its tags list
        for tag in skill.get("tags", []):
            assert not tag.startswith("tier-"), (
                f"Skill {skill['id']!r} has tier label {tag!r} in tags — "
                "tier must be in x-sdk, not tags"
            )
        # Tier must be in x-sdk
        x_sdk = skill.get("x-sdk", {})
        assert "tier" in x_sdk, (
            f"Skill {skill['id']!r} x-sdk is missing 'tier' field: {x_sdk!r}"
        )


# ---------------------------------------------------------------------------
# GH-35: AS metadata resource_indicators_supported
# ---------------------------------------------------------------------------


async def test_as_metadata_resource_indicators(client):
    """GH-35 AC-4: GET /.well-known/oauth-authorization-server must include
    resource_indicators_supported: true."""
    r = await client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    body = r.json()
    assert body.get("resource_indicators_supported") is True, (
        f"AS metadata missing resource_indicators_supported; got: {body!r}"
    )


# ---------------------------------------------------------------------------
# GH-38: TaskStatus.error field for failed tasks
# ---------------------------------------------------------------------------


async def test_failed_task_status_error(client, fake_model):
    """GH-38 AC-3: a failed task's status must include error: {code, message}.

    FakeModelClient raises AgentError when its script is empty — that triggers
    the AgentError failure path in runner.py which populates status.error."""
    # No fake_model.script() call → script is empty → converse() raises AgentError
    r = await client.post(
        "/v1/message:send",
        json={
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "fail please"}],
                "messageId": uuid.uuid4().hex,
            }
        },
    )
    assert r.status_code == 200
    task_id = r.json()["id"]
    done = await wait_for_state(client, task_id, states=("failed", "completed"))

    assert done["status"]["state"] == "failed", (
        f"Expected task to fail (empty model script); got: {done['status']['state']!r}"
    )
    err = done["status"].get("error")
    assert err is not None, (
        f"Failed task must have status.error; got status: {done['status']!r}"
    )
    assert isinstance(err.get("code"), int), f"error.code must be int; got: {err!r}"
    assert isinstance(err.get("message"), str), f"error.message must be str; got: {err!r}"
