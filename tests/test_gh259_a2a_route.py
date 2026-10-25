"""GH-259: failed status.message, acceptedOutputModes filtering, media helper,
store hook route test, over-cap body.

Ruling: https://github.com/wailuen/a2a-sdk/issues/259#issuecomment-6393088522
"""

from __future__ import annotations

import asyncio
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


async def test_header_optin_with_json_mode_completes_with_json_datapart(client, fake_model) -> None:
    from agent_sdk.models.content_types import A2UI_EXTENSION_URI

    fake_model.script(tool_call("demo_kpis", {"title": "Q2"}), reply("done"))
    r = await client.post(
        "/v1/message:send",
        json=_body(configuration={"acceptedOutputModes": ["application/json"]}),
        headers={"X-A2A-Extensions": A2UI_EXTENSION_URI},
    )
    done = await wait_for_state(client, r.json()["id"])
    assert done["status"]["state"] == "completed"
    parts = done["artifacts"][0]["parts"]
    assert [p["kind"] for p in parts] == ["data"]
    assert (parts[0].get("metadata") or {}).get("mimeType") != "application/a2ui+json"
    assert "mimeType" not in (done["artifacts"][0].get("metadata") or {})


async def test_header_optin_with_a2ui_mode_gets_a2ui_part(client, fake_model) -> None:
    from agent_sdk.models.content_types import A2UI_EXTENSION_URI

    fake_model.script(tool_call("demo_kpis", {"title": "Q2"}), reply("done"))
    r = await client.post(
        "/v1/message:send",
        json=_body(configuration={"acceptedOutputModes": ["application/a2ui+json"]}),
        headers={"X-A2A-Extensions": A2UI_EXTENSION_URI},
    )
    done = await wait_for_state(client, r.json()["id"])
    art = done["artifacts"][0]
    assert [p["kind"] for p in art["parts"]] == ["data"]
    assert art["parts"][0]["metadata"]["mimeType"] == "application/a2ui+json"
    assert art["metadata"]["mimeType"] == "application/a2ui+json"


async def test_modes_none_remain_and_text_not_accepted_is_32005(client, fake_model) -> None:
    # runtime path: A2UI accepted, but the client's declared catalog leaves no
    # A2UI translation for this result, so its text + JSON parts are both filtered out
    from agent_sdk.models.content_types import A2UI_EXTENSION_URI

    fake_model.script(tool_call("demo_kpis", {"title": "Q2"}), reply("done"))
    body = _body(configuration={"acceptedOutputModes": ["application/a2ui+json"]})
    body["message"]["metadata"] = {"a2uiClientCapabilities": {"catalogs": ["urn:other:catalog:v1"]}}
    r = await client.post(
        "/v1/message:send",
        json=body,
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


# ── GH-261: per-task A2UI decision, ingress and resume ──

from agent_sdk.agent.deferred import DeferredResult  # noqa: E402
from agent_sdk.agent.registry import ToolSet  # noqa: E402
from agent_sdk.app import Agent  # noqa: E402
from agent_sdk.example.agent import tools as _example_tools  # noqa: E402
from agent_sdk.models.content_types import (  # noqa: E402
    A2UI_EXTENSION_URI as _A2UI,
    KpiCard,
    MetricItem,
)

_HDR = {"X-A2A-Extensions": _A2UI}
_A2UI_MIME = "application/a2ui+json"


async def _deferred_kpi() -> KpiCard:
    return KpiCard(title="d", metrics=[MetricItem(label="A", value=1)])


_deferred_tools = ToolSet()


@_deferred_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def deferred_kpi() -> DeferredResult:
    """Deferred job resolving to a card."""
    return DeferredResult(handle=_deferred_kpi(), estimated_seconds=1.0)


@pytest.fixture
async def gh261(settings):
    model = FakeModelClient()
    app = Agent(
        settings=settings, persona="t", toolsets=[_example_tools, _deferred_tools], model_client=model
    ).build_app()
    async with app.router.lifespan_context(app):
        _, token = app.state.auth.api_keys.mint("t", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            yield app, model, c
    app.state.credential_store.close()
    gc.collect()


def _has_a2ui_part(task: dict) -> bool:
    return any(
        (p.get("metadata") or {}).get("mimeType") == _A2UI_MIME
        for a in task.get("artifacts") or []
        for p in a["parts"]
    )


def _send(modes=None, task_id=None, text="go") -> dict:
    body = _body(text)
    if task_id:
        body["message"]["taskId"] = task_id
    if modes is not None:
        body["configuration"] = {"acceptedOutputModes": modes}
    return body


async def _post(c, route, body, headers=None):
    r = await c.post(f"/v1/message:{route}", json=body, headers=headers or {})
    if route == "send":
        return r, r.json()
    return r, None


async def _start_to_interrupt(c, model, route, modes=None, headers=None, tail=()):
    model.script(tool_call("publish_note", {"note": "x"}), *tail)
    r, data = await _post(c, route, _send(modes), headers)
    assert r.status_code == 200, r.text
    if route == "send":
        task_id = data["id"]
    else:
        task_id = next(
            f["taskId"] if "taskId" in f else f["id"]
            for f in (__import__("tests.conftest", fromlist=["x"]).sse_frames(r.text))
            if "taskId" in f or "id" in f
        )
    await wait_for_state(c, task_id, states=("input-required",))
    return task_id


async def test_ingress_a2ui_mode_without_header_is_415(gh261) -> None:
    app, model, c = gh261
    before = len(app.state.task_store._records)
    r = await c.post("/v1/message:send", json=_send([_A2UI_MIME]))
    assert r.status_code == 415
    body = r.json()
    assert body["error"]["code"] == -32005
    assert _A2UI_MIME not in body["error"]["message"].split("supported:")[1]
    assert len(app.state.task_store._records) == before


async def test_ingress_a2ui_mode_with_header_accepted(gh261) -> None:
    _, model, c = gh261
    model.script(reply("ok"))
    r = await c.post("/v1/message:send", json=_send([_A2UI_MIME]), headers=_HDR)
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("route", ["send", "stream"])
async def test_resume_without_header_uses_task_start_optin(gh261, route) -> None:
    app, model, c = gh261
    task_id = await _start_to_interrupt(
        c, model, route, headers=_HDR, tail=(tool_call("demo_kpis", {"title": "k"}), reply("done"))
    )
    r = await c.post(
        f"/v1/message:{route}", json=_send([_A2UI_MIME], task_id=task_id, text="approved")
    )
    assert r.status_code == 200, r.text
    done = await wait_for_state(c, task_id)
    assert done["status"]["state"] == "completed"
    assert _has_a2ui_part(done)


@pytest.mark.parametrize("route", ["send", "stream"])
async def test_resume_cannot_newly_opt_in(gh261, route) -> None:
    app, model, c = gh261
    task_id = await _start_to_interrupt(c, model, route)
    record = app.state.task_store._records[task_id]
    before = record.accepted_output_modes
    r = await c.post(
        f"/v1/message:{route}",
        json=_send([_A2UI_MIME], task_id=task_id, text="approved"),
        headers=_HDR,
    )
    assert r.status_code == 415
    assert r.json()["error"]["code"] == -32005
    got = (await c.get(f"/v1/tasks/{task_id}")).json()
    assert got["status"]["state"] == "input-required"
    assert record.accepted_output_modes == before


async def test_resume_modes_replace_for_post_resume_artifact(gh261) -> None:
    app, model, c = gh261
    task_id = await _start_to_interrupt(
        c, model, "send", headers=_HDR,
        tail=(tool_call("demo_kpis", {"title": "k"}), reply("done")),
    )
    r = await c.post(
        "/v1/message:send", json=_send(["application/json"], task_id=task_id, text="approved")
    )
    assert r.status_code == 200, r.text
    done = await wait_for_state(c, task_id)
    assert done["status"]["state"] == "completed", done["status"]
    assert not _has_a2ui_part(done)
    assert [p["kind"] for a in done["artifacts"] for p in a["parts"]] == ["data"]


async def test_resume_without_modes_keeps_stored_value(gh261) -> None:
    app, model, c = gh261
    task_id = await _start_to_interrupt(
        c, model, "send", modes=["application/json"], headers=_HDR,
        tail=(tool_call("demo_kpis", {"title": "k"}), reply("done")),
    )
    r = await c.post("/v1/message:send", json=_send(task_id=task_id, text="approved"))
    assert r.status_code == 200, r.text
    done = await wait_for_state(c, task_id)
    assert done["status"]["state"] == "completed", done["status"]
    assert not _has_a2ui_part(done)
    assert [p["kind"] for a in done["artifacts"] for p in a["parts"]] == ["data"]


async def test_deferred_site_honours_resume_modes(gh261) -> None:
    app, model, c = gh261
    task_id = await _start_to_interrupt(
        c, model, "send", headers=_HDR, tail=(tool_call("deferred_kpi", {}), reply("done"))
    )
    r = await c.post(
        "/v1/message:send", json=_send(["application/json"], task_id=task_id, text="approved")
    )
    assert r.status_code == 200, r.text
    done = await wait_for_state(c, task_id)
    assert done["status"]["state"] == "completed", done["status"]
    assert not _has_a2ui_part(done)
    assert [p["kind"] for a in done["artifacts"] for p in a["parts"]] == ["data"]


async def test_deferred_site_control_gets_a2ui(gh261) -> None:
    app, model, c = gh261
    task_id = await _start_to_interrupt(
        c, model, "send", headers=_HDR, tail=(tool_call("deferred_kpi", {}), reply("done"))
    )
    r = await c.post("/v1/message:send", json=_send(task_id=task_id, text="approved"))
    assert r.status_code == 200, r.text
    done = await wait_for_state(c, task_id)
    assert done["status"]["state"] == "completed", done["status"]
    assert _has_a2ui_part(done)


async def test_resume_modes_travel_in_envelope_not_record(gh261, monkeypatch) -> None:
    app, model, c = gh261
    task_id = await _start_to_interrupt(
        c, model, "send", headers=_HDR,
        tail=(tool_call("demo_kpis", {"title": "k"}), reply("done")),
    )
    store = app.state.task_store
    record = store._records[task_id]
    seen: list = []
    real = store.deliver_resume

    def spy(tid, value):
        seen.append(value)
        return real(tid, value)

    monkeypatch.setattr(store, "deliver_resume", spy)
    before = record.accepted_output_modes
    r = await c.post(
        "/v1/message:send", json=_send([_A2UI_MIME], task_id=task_id, text="approved"),
        headers=_HDR,
    )
    assert r.status_code == 200, r.text
    assert seen[0].accepted_output_modes == [_A2UI_MIME]
    done = await wait_for_state(c, task_id)
    assert done["status"]["state"] == "completed"
    assert record.accepted_output_modes == [_A2UI_MIME]


async def test_losing_resume_does_not_apply_its_modes(gh261) -> None:
    app, model, c = gh261
    task_id = await _start_to_interrupt(
        c, model, "send", headers=_HDR,
        tail=(tool_call("demo_kpis", {"title": "k"}), reply("done")),
    )
    r1, r2 = await asyncio.gather(
        c.post("/v1/message:send", json=_send([_A2UI_MIME], task_id=task_id, text="approved"), headers=_HDR),
        c.post("/v1/message:send", json=_send(["application/json"], task_id=task_id, text="approved"), headers=_HDR),
    )
    assert sorted([r1.status_code, r2.status_code])[0] == 200
    done = await wait_for_state(c, task_id)
    winner_modes = [_A2UI_MIME] if r1.status_code == 200 else ["application/json"]
    assert app.state.task_store._records[task_id].accepted_output_modes == winner_modes
    assert done["status"]["state"] == "completed"


def test_apply_output_modes_filepart_only_is_32005() -> None:
    from agent_sdk.agent.runner import apply_output_modes
    from agent_sdk.models.a2a import Artifact, FilePart
    from agent_sdk.models.errors import AgentError

    art = Artifact(
        artifactId="a",
        parts=[FilePart(file={"uri": "https://example.com/a.png", "mimeType": "image/png"})],
    )
    with pytest.raises(AgentError) as ei:
        apply_output_modes(art, ["text/plain"])
    assert ei.value.a2a_code == -32005


def test_unserializable_tail_text_is_one_constant() -> None:
    from agent_sdk.routes import a2a

    assert a2a._INVALID_RESPONSE_TEXT == "invalid agent response"


def test_changelog_gh259_filtering_is_under_breaking() -> None:
    from pathlib import Path

    text = (Path(__file__).parent.parent / "CHANGELOG.md").read_text()
    section = text.split("## [0.23.0]")[1].split("## [0.22.0]")[0]
    breaking, rest = section.split("### Added")[0], section.split("### Added")[1]
    assert "GH-259: `acceptedOutputModes` is now applied" in breaking
    assert "GH-259: `acceptedOutputModes` is now applied" not in rest
    assert "_mode_accepted" not in breaking


def test_protocols_doc_mcp_void_deviation_names_condition() -> None:
    from pathlib import Path

    text = (Path(__file__).parent.parent / "docs" / "protocols.md").read_text()
    i = text.rindex("Deviation (GH-266)")
    para = text[i : i + 600]
    for word in ("`emits`", "`outputSchema`", "`structuredContent`"):
        assert word in para


_empty_deferred_tools = ToolSet()


@_empty_deferred_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def deferred_kpi_filtered() -> DeferredResult:
    """Deferred job resolving to a card."""
    return DeferredResult(handle=_deferred_kpi(), estimated_seconds=1.0)


async def test_deferred_site_no_acceptable_mode_is_32005(settings) -> None:
    model = FakeModelClient()
    app = Agent(
        settings=settings, persona="t", toolsets=[_example_tools, _empty_deferred_tools], model_client=model
    ).build_app()
    async with app.router.lifespan_context(app):
        _, token = app.state.auth.api_keys.mint("t", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            model.script(tool_call("deferred_kpi_filtered", {}), reply("done"))
            body = _send([_A2UI_MIME])
            body["message"]["metadata"] = {
                "a2uiClientCapabilities": {"catalogs": ["urn:other:catalog:v1"]}
            }
            r = await c.post("/v1/message:send", json=body, headers=_HDR)
            assert r.status_code == 200, r.text
            done = await wait_for_state(c, r.json()["id"])
            assert done["status"]["state"] == "failed", done["status"]
            assert done["status"]["error"]["code"] == -32005
            assert not done.get("artifacts")
    app.state.credential_store.close()
    gc.collect()


# ── GH-271: per-request A2UI decision drives the echo; mimeType rewritten ──


def test_accepts_a2ui_mode() -> None:
    from agent_sdk.common.media import accepts_a2ui_mode

    assert accepts_a2ui_mode(None) is True
    assert accepts_a2ui_mode([]) is True
    assert accepts_a2ui_mode(["application/a2ui+json"]) is True
    assert accepts_a2ui_mode(["application/*"]) is True
    assert accepts_a2ui_mode(["*/*"]) is True
    assert accepts_a2ui_mode(["application/json"]) is False
    assert accepts_a2ui_mode(["text/plain"]) is False


@pytest.mark.parametrize("path", ["/v1/message:send", "/v1/message:stream"])
async def test_echo_omits_a2ui_when_modes_rule_it_out(client, fake_model, path) -> None:
    from agent_sdk.models.content_types import A2UI_EXTENSION_URI

    fake_model.script(reply("ok"))
    r = await client.post(
        path,
        json=_body(configuration={"acceptedOutputModes": ["application/json"]}),
        headers={"X-A2A-Extensions": A2UI_EXTENSION_URI},
    )
    assert r.status_code == 200, r.text
    assert A2UI_EXTENSION_URI not in r.headers.get("x-a2a-extensions", "")


@pytest.mark.parametrize("path", ["/v1/message:send", "/v1/message:stream"])
async def test_echo_keeps_a2ui_when_no_modes(client, fake_model, path) -> None:
    from agent_sdk.models.content_types import A2UI_EXTENSION_URI

    fake_model.script(reply("ok"))
    r = await client.post(
        path, json=_body(), headers={"X-A2A-Extensions": A2UI_EXTENSION_URI}
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("x-a2a-extensions") == A2UI_EXTENSION_URI


def test_apply_output_modes_rewrites_mimetype_to_kept_type() -> None:
    from agent_sdk.agent.runner import apply_output_modes
    from agent_sdk.models.a2a import Artifact, DataPart

    art = Artifact(
        artifactId="a",
        parts=[
            DataPart(data={"a2ui": 1}, metadata={"mimeType": "application/a2ui+json"}),
            DataPart(data={"k": 1}),
        ],
        metadata={"mimeType": "application/a2ui+json"},
    )
    out = apply_output_modes(art, ["application/json"])
    assert [p.kind for p in out.parts] == ["data"]
    assert out.metadata["mimeType"] == "application/json"


def test_apply_output_modes_drops_mimetype_when_kept_parts_are_mixed() -> None:
    from agent_sdk.agent.runner import apply_output_modes
    from agent_sdk.models.a2a import Artifact, DataPart, TextPart

    art = Artifact(
        artifactId="a",
        parts=[
            DataPart(data={"a2ui": 1}, metadata={"mimeType": "application/a2ui+json"}),
            DataPart(data={"k": 1}),
            TextPart(text="t"),
        ],
        metadata={"mimeType": "application/a2ui+json"},
    )
    out = apply_output_modes(art, ["application/json", "text/plain"])
    assert len(out.parts) == 2
    assert "mimeType" not in out.metadata
