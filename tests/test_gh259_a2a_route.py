"""GH-259: failed status.message, acceptedOutputModes filtering, media helper,
store hook route test, over-cap body.

Ruling: https://github.com/wailuen/a2a-sdk/issues/259#issuecomment-6393088522
"""

from __future__ import annotations

import gc
import uuid

import httpx
import pytest

from agent_sdk import BaseAgentSettings
from agent_sdk.common.media import media_type_match, normalize_media_type
from agent_sdk.example.agent import make_agent
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, reply, tool_call

from .conftest import wait_for_state


def _body(text: str = "hi", **extra) -> dict:
    return {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            "messageId": uuid.uuid4().hex,
        },
        **extra,
    }


# ── item 1: failed status.message ──


async def test_failed_task_has_status_message_matching_error(client, fake_model) -> None:
    # empty script: the model call raises, the task fails
    r = await client.post("/v1/message:send", json=_body())
    assert r.status_code == 200
    done = await wait_for_state(client, r.json()["id"])
    status = done["status"]
    assert status["state"] == "failed"
    msg = status["message"]
    assert msg["role"] == "agent"
    assert len(msg["parts"]) == 1 and msg["parts"][0]["kind"] == "text"
    assert msg["parts"][0]["text"] == status["error"]["message"]


# ── item 2b: media helpers ──


def test_normalize_media_type() -> None:
    assert normalize_media_type(" Text/Plain; charset=UTF-8 ") == "text/plain"
    assert normalize_media_type("text") == "text/plain"


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("*/*", True),
        ("text/*", True),
        ("Application/JSON", True),
        ("text/plain; charset=utf-8", True),
        ("text", True),
        ("image/png", False),
        ("image/*", False),
        ("textual/plain", False),
    ],
)
def test_media_type_match(mode, expected) -> None:
    assert media_type_match(mode, {"text/plain", "application/json"}) is expected


def test_media_type_match_uses_supplied_set() -> None:
    assert media_type_match("application/json", {"text/plain"}) is False
    assert media_type_match("text/*", {"text/plain"}) is True


# ── item 2: acceptedOutputModes applied to artifacts ──


async def _kpi_artifact(client, fake_model, modes):
    fake_model.script(tool_call("demo_kpis", {"title": "Q2"}), reply("done"))
    r = await client.post(
        "/v1/message:send", json=_body(configuration={"acceptedOutputModes": modes})
    )
    assert r.status_code == 200, r.text
    return await wait_for_state(client, r.json()["id"])


async def test_modes_text_plain_keeps_only_text(client, fake_model) -> None:
    done = await _kpi_artifact(client, fake_model, ["text/plain"])
    assert done["status"]["state"] == "completed"
    assert [p["kind"] for p in done["artifacts"][0]["parts"]] == ["text"]


async def test_modes_json_keeps_only_data(client, fake_model) -> None:
    done = await _kpi_artifact(client, fake_model, ["application/json"])
    assert done["status"]["state"] == "completed"
    assert [p["kind"] for p in done["artifacts"][0]["parts"]] == ["data"]


async def test_modes_both_keeps_all(client, fake_model) -> None:
    done = await _kpi_artifact(client, fake_model, ["text/plain", "application/json"])
    assert [p["kind"] for p in done["artifacts"][0]["parts"]] == ["text", "data"]


async def test_modes_none_remain_text_accepted_gives_text_fallback(client, fake_model) -> None:
    # A2UI DataPart (application/a2ui+json) filtered out; text accepted
    from agent_sdk.models.content_types import A2UI_EXTENSION_URI

    fake_model.script(tool_call("demo_kpis", {"title": "Q2"}), reply("done"))
    r = await client.post(
        "/v1/message:send",
        json=_body(configuration={"acceptedOutputModes": ["text/plain"]}),
        headers={"X-A2A-Extensions": A2UI_EXTENSION_URI},
    )
    done = await wait_for_state(client, r.json()["id"])
    assert [p["kind"] for p in done["artifacts"][0]["parts"]] == ["text"]


async def test_modes_none_remain_and_text_not_accepted_is_32005(client, fake_model) -> None:
    from agent_sdk.models.content_types import A2UI_EXTENSION_URI

    fake_model.script(tool_call("demo_kpis", {"title": "Q2"}), reply("done"))
    r = await client.post(
        "/v1/message:send",
        json=_body(configuration={"acceptedOutputModes": ["application/json"]}),
        headers={"X-A2A-Extensions": A2UI_EXTENSION_URI},
    )
    done = await wait_for_state(client, r.json()["id"])
    assert done["status"]["state"] == "failed"
    assert done["status"]["error"]["code"] == -32005
    assert not done.get("artifacts")


# ── item 3: store hook route test (SI-5) ──


class _PagingStore(InMemoryTaskStore):
    def __init__(self, *a, **k) -> None:
        super().__init__(*a, **k)
        self.listed: list[str | None] = []
        self.validated: list[str] = []

    def list_tasks_for_identity(self, identity, page_size=50, page_token=None):
        self.listed.append(page_token)
        return super().list_tasks_for_identity(identity, page_size, page_token)

    def is_valid_page_token(self, page_token: str) -> bool:
        self.validated.append(page_token)
        return page_token.startswith("tok-") or super().is_valid_page_token(page_token)


async def test_custom_store_hooks_drive_task_list(tmp_path) -> None:
    store = _PagingStore()
    model = FakeModelClient()
    settings = BaseAgentSettings(
        DEV_MODE=True, DATA_DIR=str(tmp_path / "d"), AGENT_NAME="t"
    )
    app = make_agent(settings, model_client=model, task_store=store).build_app()
    try:
        async with app.router.lifespan_context(app):
            _, tok1 = app.state.auth.api_keys.mint("one", admin=True)
            _, tok2 = app.state.auth.api_keys.mint("two", admin=True)
            transport = httpx.ASGITransport(app=app)

            def mk(tok):
                return httpx.AsyncClient(
                    transport=transport,
                    base_url="http://test",
                    headers={"Authorization": f"Bearer {tok}"},
                )

            async with mk(tok1) as c1, mk(tok2) as c2:
                ids = []
                for _ in range(2):
                    model.script(reply("ok"))
                    r = await c1.post("/v1/message:send", json=_body())
                    ids.append(r.json()["id"])
                    await wait_for_state(c1, ids[-1])

                r = await c1.get("/v1/tasks?pageSize=1")
                assert r.status_code == 200 and r.json()["totalSize"] == 2
                nxt = r.json()["nextPageToken"]
                assert nxt

                # custom validator is consulted, custom token shape accepted
                store.validated.clear()
                assert (await c1.get("/v1/tasks?pageToken=tok-abc")).status_code == 200
                assert store.validated == ["tok-abc"]
                assert store.listed[-1] == "tok-abc"
                # and still rejects what it rejects
                assert (await c1.get("/v1/tasks?pageToken=nope")).status_code == 400

                # SI-5: a second identity cannot see or page into identity one
                other = await c2.get("/v1/tasks")
                assert other.json()["tasks"] == [] and other.json()["totalSize"] == 0
                paged = await c2.get(f"/v1/tasks?pageToken={nxt}")
                assert paged.status_code == 200
                assert paged.json()["tasks"] == []
                assert ids[0] not in paged.text and ids[1] not in paged.text
    finally:
        app.state.credential_store.close()
        gc.collect()


# ── item 4: over-cap body ──


async def test_over_cap_body_is_400_invalid_params(client) -> None:
    big = _body("x" * (1024 * 1024 + 10))
    r = await client.post("/v1/message:send", json=big)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32602


# ── unit: single build point and data-only fallback ──


def test_set_task_status_failed_message_mirrors_error() -> None:
    from agent_sdk.agent.runner import new_task, set_task_status
    from agent_sdk.auth.identity import Identity  # noqa: F401
    from agent_sdk.models.a2a import Message, TaskState, TextPart
    from agent_sdk.models.errors import WireError
    from agent_sdk.tasks.store import TaskRecord

    record = TaskRecord(task=new_task(), identity=("api_key", "x"), created_at=0.0, updated_at=0.0)
    other = Message(role="agent", parts=[TextPart(text="different")], messageId="m")
    set_task_status(
        record, TaskState.FAILED, other, error=WireError(code=-32603, message="safe text")
    )
    msg = record.task.status.message
    assert msg is not None and msg.role == "agent"
    assert [p.text for p in msg.parts] == ["safe text"]  # type: ignore[union-attr]


def test_apply_output_modes_text_fallback_for_data_only_artifact() -> None:
    from agent_sdk.agent.runner import apply_output_modes
    from agent_sdk.models.a2a import Artifact, DataPart
    from agent_sdk.models.errors import AgentError

    art = Artifact(artifactId="a", parts=[DataPart(data={"k": 1})])
    out = apply_output_modes(art, ["text/plain"])
    assert [p.kind for p in out.parts] == ["text"]
    with pytest.raises(AgentError) as ei:
        apply_output_modes(art, ["image/png"])
    assert ei.value.a2a_code == -32005


def test_memory_store_page_token_shape() -> None:
    s = InMemoryTaskStore.__new__(InMemoryTaskStore)
    assert s.is_valid_page_token("a" * 32)
    assert not s.is_valid_page_token("nope")
