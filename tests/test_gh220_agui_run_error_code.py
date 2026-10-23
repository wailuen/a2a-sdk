"""GH-220: AG-UI RUN_ERROR carries a stable ``code``; successful RUN_FINISHED carries outcome."""

from __future__ import annotations

from agent_sdk.models.errors import AgentError, ErrorCategory
from agent_sdk.testing import reply

from .conftest import sse_frames


def run_body(**extra) -> dict:
    return {
        "threadId": "t1",
        "runId": "r1",
        "messages": [{"id": "m1", "role": "user", "content": "hi"}],
        "state": {},
        "tools": [],
        "context": [],
        "forwardedProps": {},
        **extra,
    }


async def run(client, body) -> list[dict]:
    r = await client.post("/ag-ui/run", json=body)
    assert r.status_code == 200, r.text
    return sse_frames(r.text)


class _RaisingModel:
    def __init__(self, err: AgentError) -> None:
        self.err = err

    async def converse(self, **_kw):
        raise self.err


async def test_rate_limited_agent_error_sets_code(app, client):
    app.state.model_client = _RaisingModel(
        AgentError(ErrorCategory.RATE_LIMITED, "provider rate limit", source="model")
    )
    frames = await run(client, run_body())
    err = frames[-1]
    assert err["type"] == "RUN_ERROR"
    assert err["code"] == "rate_limited"


async def test_success_run_finished_has_success_outcome(client, fake_model):
    fake_model.script(reply("hello"))
    frames = await run(client, run_body())
    assert frames[-1]["type"] == "RUN_FINISHED"
    assert frames[-1]["outcome"] == {"type": "success"}


async def test_malformed_body_code_validation(client):
    r = await client.post(
        "/ag-ui/run", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert r.status_code == 200, r.text
    err = sse_frames(r.text)[-1]
    assert err["type"] == "RUN_ERROR"
    assert err["code"] == "validation"
    assert "not json" not in str(err)


async def test_no_user_message_code_validation(client):
    frames = await run(client, run_body(messages=[]))
    assert frames[-1]["type"] == "RUN_ERROR"
    assert frames[-1]["code"] == "validation"


async def test_unknown_interrupt_code_not_found(client):
    frames = await run(
        client, run_body(resume=[{"interrupt_id": "nope-secret", "status": "resolved"}])
    )
    assert frames[-1]["type"] == "RUN_ERROR"
    assert frames[-1]["code"] == "not_found"
    assert "nope-secret" not in str(frames[-1])
