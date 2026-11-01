"""GH-224: MCP elicitation (SSE answer mode) for ToolInterrupt over POST /mcp.

httpx.ASGITransport buffers whole responses, so the stream under test is
driven through a small raw-ASGI harness (``RawCall``) while answers are posted
with the normal httpx client against the same app.
"""

from __future__ import annotations

import asyncio
import base64
import gc
import json
import logging
import time
import types
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from agent_sdk.agent.loop import ToolInterrupt
from agent_sdk.agent.registry import ToolInputValidationError, ToolSet
from agent_sdk.auth import current_identity
from agent_sdk.common import sse as sse_mod
from agent_sdk.common.admission import prune_finished
from agent_sdk.contrib.action_gate import confirmation_required
from agent_sdk.credentials import forwarding
from agent_sdk.example.agent import make_agent
from agent_sdk.models.content_types import KpiCard, UserProfile
from agent_sdk.routes import mcp as mcp_mod
from agent_sdk.routes.mcp import MCP_INTERRUPT_SUFFIX, _answer_streams, _get_streams, _sessions

# ---------------------------------------------------------------------------
# Tool under test
# ---------------------------------------------------------------------------

SCHEMAS: dict[str, Any] = {
    "name": {
        "type": "object",
        "properties": {"name": {"type": "string", "maxLength": 5}},
        "required": ["name"],
    },
    "none": None,
    "empty": {},
    "nested": {
        "type": "object",
        "properties": {"a": {"type": "object", "properties": {"b": {"type": "string"}}}},
    },
    "secret": {"type": "object", "properties": {"api_token": {"type": "string"}}},
    "pin": {
        "type": "object",
        "properties": {
            k: {"type": "string"} for k in ("pin", "otp", "passcode", "passphrase", "code")
        },
    },
    "inf": {
        "type": "object",
        "properties": {"n": {"type": "number", "minimum": float("inf")}},
    },
    "multi": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 2, "maxLength": 5},
            "age": {"type": "integer", "minimum": 1, "maximum": 9},
            "email": {"type": "string", "format": "email"},
            "day": {"type": "string", "format": "date"},
            "site": {"type": "string", "format": "uri"},
            "choice": {"type": "string", "enum": ["a", "b"]},
            "flag": {"type": "boolean"},
            "when": {"type": "string", "format": "date-time"},
        },
        "required": ["name"],
    },
}

STATE = types.SimpleNamespace()


def _reset_state() -> None:
    STATE.handler_calls = []
    STATE.seen = []
    STATE.actions = 0
    STATE.entered = asyncio.Event()
    STATE.block = asyncio.Event()
    STATE.tool_runs = 0


_reset_state()


class In(BaseModel):
    mode: str = "plain"
    reason: str = "needs_input"
    schema_kind: str = "name"


tools = ToolSet()


def _who() -> tuple[str | None, str | None]:
    ident = current_identity()
    return (ident.label if ident else None, forwarding.lookup("src", "key"))


async def _handler(value: Any) -> str:
    STATE.handler_calls.append(value)
    STATE.seen.append(("handler", *_who()))
    return "got:" + json.dumps(value["payload"], sort_keys=True)


@tools.tool(tier=1, emits=KpiCard)
async def gh224_emits_tool(inp: In) -> KpiCard:
    """GH-224 elicitation test tool that declares an outputSchema."""
    raise ToolInterrupt(
        "needs_input",
        "Pick a title",
        response_schema={"type": "object", "properties": {"title": {"type": "string"}}},
    )


@tools.tool(tier=1, emits=UserProfile)
async def gh224_emits_valid_tool(inp: In) -> UserProfile:
    """GH-224 emits tool whose accepted form content validates as its model."""
    raise ToolInterrupt(
        "needs_input",
        "Who are you",
        response_schema={
            "type": "object",
            "properties": {k: {"type": "string"} for k in ("id", "display_name", "email")},
            "required": ["id", "display_name", "email"],
        },
    )


@tools.tool(tier=1)
async def gh224_tool(inp: In) -> str:
    """GH-224 elicitation test tool."""
    STATE.tool_runs += 1
    mode = inp.mode
    schema = SCHEMAS[inp.schema_kind]
    if mode == "plain":
        return "plain-done"
    if mode == "ident":
        STATE.seen.append(("body", *_who()))
        return "|".join(str(x) for x in _who())
    if mode == "ask":
        STATE.seen.append(("body", *_who()))
        raise ToolInterrupt(inp.reason, "Pick a name", response_schema=schema, resume_handler=_handler)
    if mode == "cancel":
        raise asyncio.CancelledError()
    if mode == "ask_validation":

        async def bad(value: Any) -> str:
            try:
                In.model_validate({"mode": 5})
            except ValidationError as exc:
                raise ToolInputValidationError(exc, tool_name="gh224_tool") from None
            raise AssertionError

        raise ToolInterrupt(inp.reason, "Pick a name", response_schema=schema, resume_handler=bad)
    if mode == "ask_big":
        raise ToolInterrupt(
            inp.reason,
            "Pick a name",
            response_schema={"type": "object", "properties": {"t": {"type": "string"}}},
        )
    if mode == "ask_raw":
        raise ToolInterrupt(inp.reason, "Pick a name", response_schema=schema)
    if mode == "gate":

        async def gated(_decision: Any) -> str:
            STATE.entered.set()
            await STATE.block.wait()
            STATE.actions += 1
            return "gated-done"

        raise confirmation_required(summary="Delete it?", on_confirm=gated)
    if mode == "gate_instant":

        async def gated_now(_decision: Any) -> str:
            STATE.actions += 1
            return "gated-done"

        raise confirmation_required(summary="Delete it?", on_confirm=gated_now)
    if mode == "block":
        STATE.entered.set()
        await STATE.block.wait()
        STATE.actions += 1
        return "blocked-done"
    if mode == "ask_reraise":

        async def again(value: Any) -> str:
            STATE.entered.set()
            await STATE.block.wait()
            raise ToolInterrupt("again", "Again?", response_schema=SCHEMAS["name"])

        raise ToolInterrupt("needs_input", "Pick a name", response_schema=schema, resume_handler=again)
    if mode == "block_ask":
        STATE.entered.set()
        await STATE.block.wait()
        raise ToolInterrupt("needs_input", "Pick a name", response_schema=schema, resume_handler=_handler)
    raise AssertionError(mode)


# ---------------------------------------------------------------------------
# Fixtures + harness
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_state():
    _reset_state()


@pytest.fixture
def gapp(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [tools]
    built = agent.build_app()
    yield built
    built.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def gc_(gapp):
    async with gapp.router.lifespan_context(gapp):
        _, token = gapp.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gapp),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            c.app = gapp  # type: ignore[attr-defined]
            c.token = token  # type: ignore[attr-defined]
            yield c


class RawCall:
    """One raw-ASGI request whose response is observed frame by frame."""

    def __init__(
        self,
        app: Any,
        method: str,
        path: str,
        headers: dict[str, str],
        body: bytes = b"",
        *,
        hold_start: bool = False,
    ) -> None:
        self.app = app
        self.data: list[str] = []
        self.comments = 0
        self.status: int | None = None
        self.resp_headers: dict[str, str] = {}
        self.disconnect_event = asyncio.Event()
        self.start_gate = asyncio.Event()
        self.hold_start = hold_start
        self._buf = ""
        self._body = body
        self._body_sent = False
        scope_headers = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
        self.scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": scope_headers,
            "server": ("test", 80),
            "client": ("test-client", 12345),
            "root_path": "",
        }
        self.task: "asyncio.Task[None]" = asyncio.create_task(
            self.app(self.scope, self._receive, self._send)
        )

    async def _receive(self) -> dict:
        if not self._body_sent:
            self._body_sent = True
            return {"type": "http.request", "body": self._body, "more_body": False}
        await self.disconnect_event.wait()
        return {"type": "http.disconnect"}

    async def _send(self, message: dict) -> None:
        if message["type"] == "http.response.start":
            self.status = message["status"]
            self.resp_headers = {k.decode().lower(): v.decode() for k, v in message["headers"]}
            if self.hold_start:
                await self.start_gate.wait()
        elif message["type"] == "http.response.body":
            self._buf += message.get("body", b"").decode()
            while "\n\n" in self._buf:
                block, self._buf = self._buf.split("\n\n", 1)
                for line in block.split("\n"):
                    if line.startswith("data:"):
                        self.data.append(line[5:].strip())
                    elif line.startswith(":"):
                        self.comments += 1

    @property
    def events(self) -> list[dict[str, Any]]:
        return [json.loads(d) for d in self.data if d.startswith("{")]

    def disconnect(self) -> None:
        self.disconnect_event.set()

    async def wait_events(self, n: int, timeout: float = 3.0) -> None:
        end = time.monotonic() + timeout
        while len(self.data) < n:
            if time.monotonic() > end:
                raise AssertionError(f"only {len(self.data)} data events: {self.data}")
            await asyncio.sleep(0.01)

    async def finish(self, timeout: float = 3.0) -> None:
        await asyncio.wait_for(self.task, timeout)

    async def stop(self) -> None:
        self.disconnect()
        try:
            await asyncio.wait_for(self.task, 2.0)
        except BaseException:
            self.task.cancel()


def _args(mode: str, **extra: str) -> dict[str, Any]:
    return {"mode": mode, **extra}


def _call_body(args: dict[str, Any], rid: Any = 7) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": rid,
        "method": "tools/call",
        "params": {"name": args.get("_tool", "gh224_tool"), "arguments": {k: v for k, v in args.items() if k != "_tool"}},
    }


async def init_session(
    c: httpx.AsyncClient, caps: dict[str, Any] | None = None, version: str = "2025-06-18"
) -> dict[str, str]:
    r = await c.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": version, "capabilities": caps if caps is not None else {}},
        },
    )
    assert r.status_code == 200, r.text
    return {"Mcp-Session-Id": r.headers["mcp-session-id"], "MCP-Protocol-Version": version}


ELICIT = {"elicitation": {}}
SSE_ACCEPT = "application/json, text/event-stream"


def open_call(
    c: httpx.AsyncClient,
    sess: dict[str, str],
    args: dict[str, Any],
    *,
    rid: Any = 7,
    extra: dict[str, str] | None = None,
    hold_start: bool = False,
    accept: str = SSE_ACCEPT,
) -> RawCall:
    headers = {
        "Authorization": f"Bearer {c.token}",  # type: ignore[attr-defined]
        "Content-Type": "application/json",
        "Accept": accept,
        **sess,
        **(extra or {}),
    }
    return RawCall(
        c.app,  # type: ignore[attr-defined]
        "POST",
        "/mcp",
        headers,
        json.dumps(_call_body(args, rid)).encode(),
        hold_start=hold_start,
    )


async def answer(
    c: httpx.AsyncClient, sess: dict[str, str], rid: Any, **payload: Any
) -> httpx.Response:
    return await c.post("/mcp", json={"jsonrpc": "2.0", "id": rid, **payload}, headers=sess)


async def accept(c: httpx.AsyncClient, sess: dict[str, str], rid: Any, content: Any = None) -> httpx.Response:
    result: dict[str, Any] = {"action": "accept"}
    if content is not None:
        result["content"] = content
    return await answer(c, sess, rid, result=result)


async def json_mode_body(c: httpx.AsyncClient, args: dict[str, Any], rid: Any = 7) -> dict[str, Any]:
    sess = await init_session(c)
    r = await c.post("/mcp", json=_call_body(args, rid), headers={**sess, "Accept": "application/json"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    return r.json()


def pending(app: Any) -> Any:
    return mcp_mod._pending_table(app)


def is_error(frame: dict[str, Any]) -> bool:
    return frame["result"]["isError"] is True


def text(frame: dict[str, Any]) -> str:
    return frame["result"]["content"][0]["text"]


async def settle(predicate, timeout: float = 3.0) -> None:
    end = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > end:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.01)


# ---------------------------------------------------------------------------
# 1-5: outcomes
# ---------------------------------------------------------------------------


async def test_accept_runs_resume_handler(gc_) -> None:
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("ask"))
    await call.wait_events(1)
    req = call.events[0]
    assert req["method"] == "elicitation/create"
    assert "mode" not in req["params"]
    assert req["params"]["message"] == "Pick a name"
    assert req["params"]["requestedSchema"] == {
        "type": "object",
        "properties": {"name": {"type": "string", "maxLength": 5}},
        "required": ["name"],
    }
    assert set(req["params"]["requestedSchema"]) <= {"type", "properties", "required"}
    assert call.status == 200
    assert call.resp_headers["content-type"].startswith("text/event-stream")
    assert call.resp_headers["mcp-protocol-version"] == "2025-06-18"
    r = await accept(gc_, sess, req["id"], {"name": "bob"})
    assert r.status_code == 202
    await call.finish()
    assert len(call.events) == 2
    final = call.events[1]
    assert final["id"] == 7 and not is_error(final)
    assert text(final) == 'got:{"name": "bob"}'
    assert STATE.handler_calls == [{"status": None, "payload": {"name": "bob"}}]
    assert len(_answer_streams(gc_.app)) == 0 and len(pending(gc_.app)) == 0


async def test_accept_without_resume_handler_returns_loop_envelope(gc_) -> None:
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("ask_raw", reason="needs\x07_input"))
    await call.wait_events(1)
    await accept(gc_, sess, call.events[0]["id"], {"name": "amy"})
    await call.finish()
    final = call.events[-1]
    assert not is_error(final)
    assert json.loads(text(final)) == {"interrupt": "needs _input", "user_response": {"name": "amy"}}
    assert "structuredContent" not in final["result"]


async def test_accept_without_resume_handler_emits_tool_is_fixed_error(gc_) -> None:
    """User content never goes through emits coercion, even when it would
    validate as the tool's declared model."""
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, {"_tool": "gh224_emits_valid_tool"})
    await call.wait_events(1)
    content = {"id": "u1", "display_name": "Ann", "email": "a@b.co"}
    await accept(gc_, sess, call.events[0]["id"], content)
    await call.finish()
    final = call.events[-1]
    assert is_error(final)
    assert text(final) == mcp_mod.MCP_ELICIT_NO_HANDLER_EMITS
    assert "structuredContent" not in final["result"]
    assert "Ann" not in json.dumps(final)


async def test_accept_without_resume_handler_over_cap_is_fixed_error(gc_) -> None:
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("ask_big"))
    await call.wait_events(1)
    await accept(gc_, sess, call.events[0]["id"], {"t": "Z" * 9000})
    await call.finish()
    final = call.events[-1]
    assert is_error(final)
    assert text(final) == mcp_mod.MCP_ELICIT_TOO_LARGE
    assert "ZZZ" not in json.dumps(final)


async def test_empty_response_schema_is_an_empty_form(gc_) -> None:
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("ask", schema_kind="empty"))
    await call.wait_events(1)
    assert call.events[0]["params"]["requestedSchema"] == {"type": "object", "properties": {}}
    await call.stop()


async def test_decline_cancel_error_fixed_text_no_echo(gc_) -> None:
    texts = []
    for payload in (
        {"result": {"action": "decline", "content": {"name": "SECRET-ECHO"}}},
        {"result": {"action": "cancel", "content": {"name": "SECRET-ECHO"}}},
        {"error": {"code": -1, "message": "SECRET-ECHO"}},
    ):
        sess = await init_session(gc_, ELICIT)
        call = open_call(gc_, sess, _args("ask"))
        await call.wait_events(1)
        await answer(gc_, sess, call.events[0]["id"], **payload)
        await call.finish()
        final = call.events[-1]
        assert is_error(final)
        assert "SECRET-ECHO" not in json.dumps(final)
        texts.append(text(final))
    assert len(set(texts)) == 3
    assert STATE.handler_calls == []


async def test_timeout_fixed_is_error(gc_, monkeypatch) -> None:
    monkeypatch.setattr(gc_.app.state.settings, "mcp_elicitation_timeout_seconds", 0.2, raising=False)
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("ask"))
    await call.wait_events(1)
    await call.finish()
    final = call.events[-1]
    assert is_error(final) and "SECRET" not in json.dumps(final)
    assert len(call.events) == 3
    assert call.events[1] == {
        "jsonrpc": "2.0",
        "method": "notifications/cancelled",
        "params": {"requestId": call.events[0]["id"]},
    }
    assert len(pending(gc_.app)) == 0
    assert STATE.handler_calls == []
    assert len(_answer_streams(gc_.app)) == 0


# ---------------------------------------------------------------------------
# 6-8: untouched JSON mode
# ---------------------------------------------------------------------------

EXPECTED_INTERRUPT = {
    "jsonrpc": "2.0",
    "id": 7,
    "result": {
        "content": [{"type": "text", "text": f"Pick a name {MCP_INTERRUPT_SUFFIX}"}],
        "isError": True,
    },
}


async def test_no_capability_keeps_json_mode(gc_) -> None:
    sess = await init_session(gc_, {})
    r = await gc_.post("/mcp", json=_call_body(_args("ask")), headers={**sess, "Accept": SSE_ACCEPT})
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == EXPECTED_INTERRUPT


async def test_old_version_keeps_json_mode(gc_) -> None:
    sess = await init_session(gc_, ELICIT, version="2025-03-26")
    r = await gc_.post("/mcp", json=_call_body(_args("ask")), headers={**sess, "Accept": SSE_ACCEPT})
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == EXPECTED_INTERRUPT


async def test_accept_without_event_stream_keeps_json_mode(gc_) -> None:
    sess = await init_session(gc_, ELICIT)
    r = await gc_.post("/mcp", json=_call_body(_args("ask")), headers={**sess, "Accept": "application/json"})
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == EXPECTED_INTERRUPT
    assert len(pending(gc_.app)) == 0


async def test_url_only_capability_does_not_count(gc_) -> None:
    sess = await init_session(gc_, {"elicitation": {"url": {}}})
    r = await gc_.post("/mcp", json=_call_body(_args("ask")), headers={**sess, "Accept": SSE_ACCEPT})
    assert r.headers["content-type"].startswith("application/json")


# ---------------------------------------------------------------------------
# 9, 10, 25: fallbacks in the stream
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("schema_kind", ["nested", "secret"])
async def test_not_convertible_falls_back_in_stream(gc_, schema_kind) -> None:
    args = _args("ask", schema_kind=schema_kind)
    expected = await json_mode_body(gc_, args)
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, args)
    await call.finish()
    assert len(call.data) == 1
    assert call.events == [expected]
    assert len(pending(gc_.app)) == 0 and len(_answer_streams(gc_.app)) == 0


@pytest.mark.parametrize("reason", ["auth", "needs_auth", "Auth"])
@pytest.mark.parametrize("schema_kind", ["none", "pin"])
async def test_auth_reason_never_elicits(gc_, reason, schema_kind) -> None:
    args = _args("ask", reason=reason, schema_kind=schema_kind)
    expected = await json_mode_body(gc_, args)
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, args)
    await call.finish()
    assert len(call.data) == 1
    assert call.events == [expected]
    assert "elicitation/create" not in call.data[0]


# ---------------------------------------------------------------------------
# 11-12: answer binding, session delete
# ---------------------------------------------------------------------------


async def test_foreign_answers_ignored(gc_) -> None:
    sess = await init_session(gc_, ELICIT)
    other_sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("ask"))
    await call.wait_events(1)
    rid = call.events[0]["id"]
    good = {"result": {"action": "accept", "content": {"name": "bob"}}}

    r = await answer(gc_, other_sess, rid, **good)
    assert r.status_code == 202
    r = await answer(gc_, sess, "no-such-id", **good)
    assert r.status_code == 202
    _, other_token = gc_.app.state.auth.api_keys.mint("other-224", admin=True)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gc_.app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {other_token}"},
    ) as other:
        r = await answer(other, sess, rid, **good)
        assert r.status_code == 404
    await asyncio.sleep(0.1)
    assert len(call.data) == 1 and not call.task.done()
    assert len(pending(gc_.app)) == 1

    assert (await answer(gc_, sess, rid, **good)).status_code == 202
    assert (await answer(gc_, sess, rid, **good)).status_code == 202  # duplicate
    await call.finish()
    assert len(call.events) == 2 and not is_error(call.events[1])
    assert len(STATE.handler_calls) == 1


async def test_session_delete_ends_call(gc_) -> None:
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("ask"))
    await call.wait_events(1)
    r = await gc_.delete("/mcp", headers=sess)
    assert r.status_code == 204
    await call.finish()
    assert is_error(call.events[-1])
    assert len(pending(gc_.app)) == 0
    assert sess["Mcp-Session-Id"] not in mcp_mod._session_elicitation(gc_.app)
    assert STATE.handler_calls == []


# ---------------------------------------------------------------------------
# 13: action gate
# ---------------------------------------------------------------------------


async def _gate_run(gc_, content: Any = None, **payload: Any) -> RawCall:
    sess = await init_session(gc_, ELICIT)
    STATE.block.set()
    call = open_call(gc_, sess, _args("gate"))
    await call.wait_events(1)
    req = call.events[0]
    assert req["params"]["message"] == "Delete it?"
    if payload:
        await answer(gc_, sess, req["id"], **payload)
    else:
        await accept(gc_, sess, req["id"], content)
    await call.finish()
    return call


async def test_action_gate_runs_only_on_approving_accept(gc_) -> None:
    await _gate_run(gc_, {"decision": "approved"})
    assert STATE.actions == 1
    await _gate_run(gc_, {"decision": "rejected"})
    assert STATE.actions == 1
    await _gate_run(gc_, result={"action": "decline"})
    await _gate_run(gc_, result={"action": "cancel"})
    assert STATE.actions == 1


async def test_action_gate_timeout_never_runs(gc_, monkeypatch) -> None:
    monkeypatch.setattr(gc_.app.state.settings, "mcp_elicitation_timeout_seconds", 0.2, raising=False)
    STATE.block.set()
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("gate"))
    await call.finish()
    assert STATE.actions == 0 and is_error(call.events[-1])


# ---------------------------------------------------------------------------
# 14: mode: form
# ---------------------------------------------------------------------------


async def test_form_mode_only_on_newest_version(gc_) -> None:
    for version, expect_mode in (("2025-11-25", True), ("2025-06-18", False)):
        sess = await init_session(gc_, ELICIT, version=version)
        call = open_call(gc_, sess, _args("ask"))
        await call.wait_events(1)
        params = call.events[0]["params"]
        assert (params.get("mode") == "form") is expect_mode
        await call.stop()


# ---------------------------------------------------------------------------
# 15: non-interrupting call
# ---------------------------------------------------------------------------


async def test_plain_call_gets_single_response_stream(gc_) -> None:
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("plain"))
    await call.finish()
    assert call.status == 200
    assert call.resp_headers["content-type"].startswith("text/event-stream")
    assert len(call.data) == 1
    assert call.events[0] == {
        "jsonrpc": "2.0",
        "id": 7,
        "result": {"content": [{"type": "text", "text": "plain-done"}], "isError": False},
    }
    assert len(_answer_streams(gc_.app)) == 0


# ---------------------------------------------------------------------------
# 16: content validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content",
    [
        {"name": 5},
        {"age": 3},
        {"name": "bob", "extra": 1},
        {"name": "b"},
        {"name": "toolongname"},
        {"name": "bob", "age": 10},
        {"name": "bob", "age": 0},
        {"name": "bob", "age": True},
        {"name": "bob", "age": 1.5},
        {"name": "bob", "email": "nope"},
        {"name": "bob", "email": "@x.com"},
        {"name": "bob", "day": "2025-13-45"},
        {"name": "bob", "when": "2025-01-02"},
        {"name": "bob", "when": "20250102"},
        {"name": "bob", "when": "2025-01-02T10:00:00"},
        {"name": "bob", "site": "no-scheme"},
        {"name": "bob", "choice": "c"},
        {"name": "bob", "flag": "yes"},
        ["not", "an", "object"],
    ],
)
async def test_invalid_accept_content_rejected(gc_, content) -> None:
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("ask", schema_kind="multi"))
    await call.wait_events(1)
    await answer(gc_, sess, call.events[0]["id"], result={"action": "accept", "content": content})
    await call.finish()
    assert is_error(call.events[-1])
    assert STATE.handler_calls == []


async def test_valid_multi_accept_passes(gc_) -> None:
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("ask", schema_kind="multi"))
    await call.wait_events(1)
    content = {
        "name": "bob",
        "age": 3,
        "email": "a@b.co",
        "day": "2025-01-02",
        "site": "https://x.test",
        "choice": "a",
        "flag": True,
        "when": "2025-01-02T10:00:00Z",
    }
    await accept(gc_, sess, call.events[0]["id"], content)
    await call.finish()
    assert not is_error(call.events[-1])
    assert STATE.handler_calls == [{"status": None, "payload": content}]


async def test_gate_out_of_enum_never_runs_action(gc_) -> None:
    await _gate_run(gc_, {"decision": "ok"})
    assert STATE.actions == 0


# ---------------------------------------------------------------------------
# 17: converter
# ---------------------------------------------------------------------------


def test_converter_enum_optional_and_recursive() -> None:
    import enum
    from typing import Optional

    from agent_sdk.routes.mcp_elicitation import convert_schema

    class Color(enum.Enum):
        red = "red"
        blue = "blue"

    class Form(BaseModel):
        color: Color
        note: Optional[str] = None

    converted = convert_schema(Form.model_json_schema())
    assert converted is not None
    assert set(converted) == {"type", "properties", "required"}
    assert converted["properties"]["color"].get("title") == "Color"
    assert convert_schema({}) == {"type": "object", "properties": {}}
    assert converted["properties"]["color"]["enum"] == ["red", "blue"]
    assert converted["properties"]["note"]["type"] == "string"
    assert converted["required"] == ["color"]

    class Node(BaseModel):
        child: "Optional[Node]" = None

    assert convert_schema(Node.model_json_schema()) is None
    assert convert_schema(None) == {"type": "object", "properties": {}}


def test_converter_refuses_constraints_it_cannot_carry() -> None:
    from typing import Literal

    from pydantic import Field

    from agent_sdk.routes.mcp_elicitation import convert_schema

    class Yes(BaseModel):
        pick: Literal["yes"]

    class Lvl(BaseModel):
        lvl: Literal[1, 2, 3]

    class Code(BaseModel):
        code: str = Field(pattern="^[A-Z]{3}$")

    class Step(BaseModel):
        n: int = Field(ge=1, multiple_of=5)

    class Excl(BaseModel):
        n: int = Field(gt=1)

    for model in (Yes, Lvl, Code, Step, Excl):
        assert convert_schema(model.model_json_schema()) is None, model


# ---------------------------------------------------------------------------
# 18: disconnect while waiting
# ---------------------------------------------------------------------------


async def test_disconnect_while_waiting(gc_) -> None:
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("ask"))
    await call.wait_events(1)
    call.disconnect()
    await call.finish()
    await settle(lambda: len(_answer_streams(gc_.app)) == 0)
    assert len(pending(gc_.app)) == 0
    assert STATE.handler_calls == []


async def test_generator_aclose_while_waiting(gc_, monkeypatch) -> None:
    """The GeneratorExit path a spec_version>=2.4 server leaves to GC."""
    captured: list[Any] = []

    class Manual(mcp_mod.StreamingResponse):  # type: ignore[misc]
        async def __call__(self, scope, receive, send):  # noqa: ANN001
            captured.append(self)
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await asyncio.Event().wait()

    monkeypatch.setattr(mcp_mod, "StreamingResponse", Manual)
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("ask"))
    await settle(lambda: bool(captured))
    resp = captured[0]
    first = await asyncio.wait_for(resp.body_iterator.__anext__(), 3)
    assert b"elicitation/create" in first
    assert len(pending(gc_.app)) == 1
    await resp.body_iterator.aclose()
    assert len(pending(gc_.app)) == 0
    await settle(lambda: not [t for t in asyncio.all_tasks() if "_sse_worker" in repr(t)])
    await resp.background()
    await settle(lambda: len(_answer_streams(gc_.app)) == 0)
    assert STATE.handler_calls == []
    call.task.cancel()


# ---------------------------------------------------------------------------
# 19-20: session lifetime while waiting
# ---------------------------------------------------------------------------


async def test_heartbeat_touch_keeps_session_alive(gc_, monkeypatch) -> None:
    sess = await init_session(gc_, ELICIT)
    monkeypatch.setattr(mcp_mod, "SESSION_TTL_SECONDS", 0.8)
    monkeypatch.setattr(sse_mod, "STREAM_HEARTBEAT_SECONDS", 0.2)
    call = open_call(gc_, sess, _args("ask"))
    await call.wait_events(1)
    await asyncio.sleep(1.6)
    assert not call.task.done()
    r = await accept(gc_, sess, call.events[0]["id"], {"name": "bob"})
    assert r.status_code == 202
    await call.finish()
    assert not is_error(call.events[-1])


async def test_session_ttl_expiry_ends_call(gc_, monkeypatch) -> None:
    sess = await init_session(gc_, ELICIT)
    monkeypatch.setattr(sse_mod, "STREAM_HEARTBEAT_SECONDS", 100.0)
    call = open_call(gc_, sess, _args("ask"))
    await call.wait_events(1)
    monkeypatch.setattr(mcp_mod, "SESSION_TTL_SECONDS", 0.3)
    await asyncio.sleep(0.5)
    r = await gc_.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 9, "method": "tools/list"}, headers=sess
    )
    assert r.status_code == 404
    await call.finish()
    assert is_error(call.events[-1])
    assert len(pending(gc_.app)) == 0


async def test_global_session_cap_eviction_ends_call(gc_, monkeypatch) -> None:
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("ask"))
    await call.wait_events(1)
    monkeypatch.setattr(mcp_mod, "_MAX_SESSIONS", 2)
    await init_session(gc_, {})
    await init_session(gc_, {})
    await call.finish()
    assert is_error(call.events[-1])
    assert len(pending(gc_.app)) == 0
    assert sess["Mcp-Session-Id"] not in _sessions(gc_.app)
    assert sess["Mcp-Session-Id"] not in mcp_mod._session_elicitation(gc_.app)


# ---------------------------------------------------------------------------
# 21: legacy /mcp/messages and unauthenticated answers
# ---------------------------------------------------------------------------


async def test_legacy_messages_never_resolves(gc_) -> None:
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("ask"))
    await call.wait_events(1)
    rid = call.events[0]["id"]

    legacy = RawCall(
        gc_.app,
        "GET",
        "/mcp/sse",
        {"Authorization": f"Bearer {gc_.token}", "Accept": "text/event-stream"},
    )
    await legacy.wait_events(1)
    legacy_sid = legacy.data[0].split("session_id=")[1]
    r = await gc_.post(
        f"/mcp/messages?session_id={legacy_sid}",
        json={"jsonrpc": "2.0", "id": rid, "result": {"action": "accept", "content": {"name": "bob"}}},
    )
    assert r.status_code == 202
    await asyncio.sleep(0.1)
    assert not call.task.done() and len(pending(gc_.app)) == 1

    anon = await httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gc_.app), base_url="http://test"
    ).post("/mcp", json={"jsonrpc": "2.0", "id": rid, "result": {"action": "accept"}}, headers=sess)
    assert anon.status_code == 401
    wrong = await gc_.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": rid, "result": {"action": "accept"}},
        headers={**sess, "Mcp-Session-Id": "0" * 32},
    )
    assert wrong.status_code == 404
    assert len(pending(gc_.app)) == 1
    await legacy.stop()
    await call.stop()


# ---------------------------------------------------------------------------
# 22: capability survives touch
# ---------------------------------------------------------------------------


async def test_capability_survives_touch(gc_) -> None:
    sess = await init_session(gc_, ELICIT)
    sid = sess["Mcp-Session-Id"]
    for i in range(3):
        r = await gc_.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 10 + i, "method": "tools/list"}, headers=sess
        )
        assert r.status_code == 200
    assert mcp_mod._session_elicitation(gc_.app).get(sid) is True
    assert len(_sessions(gc_.app)[sid]) == 3
    plain = await init_session(gc_, {})
    assert mcp_mod._session_elicitation(gc_.app).get(plain["Mcp-Session-Id"], False) is False


# ---------------------------------------------------------------------------
# 23: strict writer
# ---------------------------------------------------------------------------


async def test_strict_writer_refuses_accepted_content(gc_, monkeypatch) -> None:
    real = mcp_mod.dumps_strict

    def picky(obj: Any, *a: Any, **k: Any) -> str:
        if isinstance(obj, dict) and obj.get("user_response") == {"name": "bob"}:
            raise ValueError("refused")
        return real(obj, *a, **k)

    monkeypatch.setattr(mcp_mod, "dumps_strict", picky)
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("ask_raw"))
    await call.wait_events(1)
    await accept(gc_, sess, call.events[0]["id"], {"name": "bob"})
    await call.finish()
    assert len(call.events) == 2 and is_error(call.events[1])
    assert call.events[1]["id"] == 7


async def test_non_finite_schema_falls_back(gc_, monkeypatch) -> None:
    args = _args("ask", schema_kind="inf")
    expected = await json_mode_body(gc_, args)
    inserts: list[str] = []
    from agent_sdk.routes.mcp_elicitation import PendingTable

    orig_add = PendingTable.add

    def spy(self, *a, **k):  # noqa: ANN001
        inserts.append(a[0])
        return orig_add(self, *a, **k)

    monkeypatch.setattr(PendingTable, "add", spy)
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, args)
    await call.finish()
    assert call.events == [expected] and len(call.data) == 1
    assert inserts == []


async def test_writer_refused_final_result_is_32603(gc_, monkeypatch) -> None:
    async def bad(app: Any, params: dict, call: Any = None) -> dict:
        return {"content": [{"type": "text", "text": "x"}], "isError": False, "junk": float("nan")}

    monkeypatch.setattr(mcp_mod, "_handle_tools_call", bad)
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("plain"))
    await call.finish()
    assert len(call.data) == 1
    assert call.events[0] == {
        "jsonrpc": "2.0",
        "id": 7,
        "error": {"code": -32603, "message": "internal error"},
    }


# ---------------------------------------------------------------------------
# 24: heartbeats
# ---------------------------------------------------------------------------


async def test_heartbeats_are_comments(gc_, monkeypatch) -> None:
    monkeypatch.setattr(sse_mod, "STREAM_HEARTBEAT_SECONDS", 0.1)
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("ask"))
    await call.wait_events(1)
    await asyncio.sleep(0.5)
    assert call.comments >= 2
    assert len(call.data) == 1
    await accept(gc_, sess, call.events[0]["id"], {"name": "bob"})
    await call.finish()
    assert len(call.events) == 2


# ---------------------------------------------------------------------------
# 26: identity and forwarded credentials inside the stream task
# ---------------------------------------------------------------------------


async def test_identity_and_forwarded_credentials_in_sse_mode(gc_) -> None:
    header = {
        forwarding.HEADER_NAME: base64.b64encode(json.dumps({"src": {"key": "v1"}}).encode()).decode()
    }
    sess = await init_session(gc_, ELICIT)

    plain = open_call(gc_, sess, _args("ident"), extra=header)
    await plain.finish()
    assert text(plain.events[0]) == "test-admin|v1"

    call = open_call(gc_, sess, _args("ask"), extra=header, rid=8)
    await call.wait_events(1)
    await accept(gc_, sess, call.events[0]["id"], {"name": "bob"})
    await call.finish()
    assert ("body", "test-admin", "v1") in STATE.seen
    assert ("handler", "test-admin", "v1") in STATE.seen


# ---------------------------------------------------------------------------
# 27-30: disconnect phases and the slot rule
# ---------------------------------------------------------------------------


def _assert_drop_logged(caplog, secret: str) -> None:
    drops = [r.getMessage() for r in caplog.records if "result dropped" in r.getMessage()]
    assert len(drops) == 1
    assert "tool=gh224_tool" in drops[0] and secret not in drops[0]


async def test_phase_a_body_shielded_slot_held(gc_, caplog) -> None:
    caplog.set_level(logging.INFO, logger="agent_sdk")
    sess = await init_session(gc_, ELICIT)
    streams = _answer_streams(gc_.app)
    call = open_call(gc_, sess, _args("block"))
    await asyncio.wait_for(STATE.entered.wait(), 3)
    call.disconnect()
    await call.finish()
    await asyncio.sleep(0.1)
    assert len(streams) == 1
    await prune_finished(streams)
    assert len(streams) == 1
    assert STATE.actions == 0
    STATE.block.set()
    await settle(lambda: len(streams) == 0)
    assert STATE.actions == 1
    assert len(pending(gc_.app)) == 0
    _assert_drop_logged(caplog, "blocked-done")


async def test_phase_c_resume_shielded_slot_held(gc_, caplog) -> None:
    caplog.set_level(logging.INFO, logger="agent_sdk")
    sess = await init_session(gc_, ELICIT)
    streams = _answer_streams(gc_.app)
    call = open_call(gc_, sess, _args("gate"))
    await call.wait_events(1)
    await accept(gc_, sess, call.events[0]["id"], {"decision": "approved"})
    await asyncio.wait_for(STATE.entered.wait(), 3)
    call.disconnect()
    await call.finish()
    await asyncio.sleep(0.1)
    assert len(streams) == 1
    await prune_finished(streams)
    assert len(streams) == 1
    assert STATE.actions == 0
    STATE.block.set()
    await settle(lambda: len(streams) == 0)
    assert STATE.actions == 1
    assert len(pending(gc_.app)) == 0
    _assert_drop_logged(caplog, "gated-done")


async def test_move2_accept_before_disconnect_still_runs(gc_, monkeypatch) -> None:
    """The Future was resolved by an accept, then the disconnect lands before
    the worker starts resume_handler: the approved action still runs once."""
    states: list[Any] = []
    orig_cls = mcp_mod.CallState

    class Recording(orig_cls):  # type: ignore[valid-type, misc]
        def __init__(self, *a: Any, **k: Any) -> None:
            super().__init__(*a, **k)
            states.append(self)

    monkeypatch.setattr(mcp_mod, "CallState", Recording)
    real_validate = mcp_mod.validate_content

    def validate_then_disconnect(requested: Any, content: Any) -> bool:
        states[0].disconnected = True
        pending(gc_.app).drop_call(states[0].call_id)
        return real_validate(requested, content)

    monkeypatch.setattr(mcp_mod, "validate_content", validate_then_disconnect)
    STATE.block.set()
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("gate"))
    await call.wait_events(1)
    await accept(gc_, sess, call.events[0]["id"], {"decision": "approved"})
    await settle(lambda: STATE.actions == 1)
    call.disconnect()
    await call.finish()
    await settle(lambda: len(_answer_streams(gc_.app)) == 0)
    assert STATE.actions == 1


async def test_move3_reraise_after_disconnect_no_second_elicitation(gc_, monkeypatch) -> None:
    frames: list[Any] = []
    inserts: list[str] = []
    real = mcp_mod.dumps_strict

    def recording(obj: Any, *a: Any, **k: Any) -> str:
        if isinstance(obj, dict) and obj.get("method") == "elicitation/create":
            frames.append(obj)
        return real(obj, *a, **k)

    monkeypatch.setattr(mcp_mod, "dumps_strict", recording)
    from agent_sdk.routes.mcp_elicitation import PendingTable

    orig_add = PendingTable.add

    def spy(self, *a, **k):  # noqa: ANN001
        inserts.append(a[0])
        return orig_add(self, *a, **k)

    monkeypatch.setattr(PendingTable, "add", spy)
    sess = await init_session(gc_, ELICIT)
    streams = _answer_streams(gc_.app)
    call = open_call(gc_, sess, _args("ask_reraise"))
    await call.wait_events(1)
    await accept(gc_, sess, call.events[0]["id"], {"name": "bob"})
    await asyncio.wait_for(STATE.entered.wait(), 3)
    call.disconnect()
    await call.finish()
    STATE.block.set()
    await settle(lambda: len(streams) == 0, timeout=2.0)
    assert len(frames) == 1 and len(inserts) == 1
    assert len(pending(gc_.app)) == 0


async def test_phase_d_disconnect_at_response_start(gc_, monkeypatch) -> None:
    """Disconnect before the generator body starts: Starlette runs only the
    BackgroundTask. The app's outer middleware defers http.response.start, so
    the response is replaced with one that never iterates its body and runs
    only its background."""

    class SkipBody(mcp_mod.StreamingResponse):  # type: ignore[misc]
        async def __call__(self, scope, receive, send):  # noqa: ANN001
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            await self.background()

    monkeypatch.setattr(mcp_mod, "StreamingResponse", SkipBody)
    sess = await init_session(gc_, ELICIT)
    streams = _answer_streams(gc_.app)
    call = open_call(gc_, sess, _args("ask"))
    await call.finish()
    assert len(streams) == 0
    assert STATE.tool_runs == 0
    assert len(pending(gc_.app)) == 0


async def test_move1_interrupt_after_disconnect_makes_no_entry(gc_, monkeypatch) -> None:
    inserts: list[str] = []
    frames: list[Any] = []
    from agent_sdk.routes.mcp_elicitation import PendingTable

    orig_add = PendingTable.add

    def spy(self, *a, **k):  # noqa: ANN001
        inserts.append(a[0])
        return orig_add(self, *a, **k)

    monkeypatch.setattr(PendingTable, "add", spy)
    real = mcp_mod.dumps_strict

    def recording(obj: Any, *a: Any, **k: Any) -> str:
        if isinstance(obj, dict) and obj.get("method") == "elicitation/create":
            frames.append(obj)
        return real(obj, *a, **k)

    monkeypatch.setattr(mcp_mod, "dumps_strict", recording)
    assert gc_.app.state.settings.mcp_elicitation_timeout_seconds == 300
    sess = await init_session(gc_, ELICIT)
    streams = _answer_streams(gc_.app)
    call = open_call(gc_, sess, _args("block_ask"))
    await asyncio.wait_for(STATE.entered.wait(), 3)
    call.disconnect()
    await call.finish()
    STATE.block.set()
    await settle(lambda: len(streams) == 0, timeout=2.0)
    assert inserts == [] and frames == []
    assert len(pending(gc_.app)) == 0


@pytest.mark.parametrize(
    "extra",
    [
        {"anyOf": [{"required": ["a"]}, {"required": ["b"]}]},
        {"allOf": [{"required": ["a"]}]},
        {"oneOf": [{"required": ["a"]}]},
        {"minProperties": 1},
        {"dependentRequired": {"a": ["b"]}},
    ],
)
def test_converter_refuses_unknown_top_level_keywords(extra: dict[str, Any]) -> None:
    from agent_sdk.routes.mcp_elicitation import convert_schema

    schema = {
        "type": "object",
        "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
        **extra,
    }
    assert convert_schema(schema) is None


# ---------------------------------------------------------------------------
# w070 follow-ups (D-01 .. D-16 + protocol findings)
# ---------------------------------------------------------------------------


async def test_worker_dies_without_final_frame_ends_stream(gc_) -> None:
    """D-01: a BaseException leaking from the tool must not heartbeat forever."""
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("cancel"))
    await call.finish()
    assert call.events == [
        {"jsonrpc": "2.0", "id": 7, "error": {"code": -32603, "message": "internal error"}}
    ]
    await settle(lambda: len(_answer_streams(gc_.app)) == 0)


async def test_stream_budget_full_falls_back_to_json_mode(gc_, monkeypatch, caplog) -> None:
    """D-03a: answer-mode budget full -> JSON reply, never 5xx, one info line."""
    caplog.set_level(logging.INFO, logger="agent_sdk")
    monkeypatch.setattr(mcp_mod, "_max_answer_streams_per_identity", lambda app: 0)
    sess = await init_session(gc_, ELICIT)
    r = await gc_.post("/mcp", json=_call_body(_args("ask")), headers={**sess, "Accept": SSE_ACCEPT})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == EXPECTED_INTERRUPT
    lines = [x.getMessage() for x in caplog.records if "answer stream budget full" in x.getMessage()]
    assert lines == ["mcp answer stream budget full, JSON fallback tool=gh224_tool"]


async def test_pending_cap_falls_back_in_stream(gc_) -> None:
    """D-03b: the 9th pending entry in a session -> in-stream interrupt isError."""
    sess = await init_session(gc_, ELICIT)
    first = open_call(gc_, sess, _args("ask"), rid=1)
    await first.wait_events(1)
    table = pending(gc_.app)
    entry = next(iter(table._entries.values()))
    for i in range(7):
        assert table.add(f"dummy-{i}", entry.owner, entry.session_id, "dummy") is not None
    assert len(table) == 8
    ninth = open_call(gc_, sess, _args("ask"), rid=9)
    await ninth.finish()
    assert len(ninth.data) == 1
    assert ninth.events == [{**EXPECTED_INTERRUPT, "id": 9}]
    assert "elicitation/create" not in ninth.data[0]
    table.fail_session(entry.session_id, mcp_mod.ElicitationCancelled)
    await first.finish()


async def test_answer_streams_never_push_get_mcp_to_429(gc_, monkeypatch) -> None:
    """Protocol finding: an open answer-mode stream takes no GET slot."""
    monkeypatch.setattr(mcp_mod, "_max_streams_per_identity", lambda app: 2)
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("ask"))
    await call.wait_events(1)
    assert len(_answer_streams(gc_.app)) == 1 and len(_get_streams(gc_.app)) == 0
    gets = []
    for _ in range(2):
        g = RawCall(
            gc_.app,
            "GET",
            "/mcp",
            {"Authorization": f"Bearer {gc_.token}", "Accept": "text/event-stream", **sess},
        )
        await settle(lambda: g.status is not None)
        assert g.status == 200
        gets.append(g)
    over = await gc_.get("/mcp", headers={**sess, "Accept": "text/event-stream"})
    assert over.status_code == 429
    for g in gets:
        await g.stop()
    await call.stop()


async def test_answer_streams_capped_per_identity_separately(gc_, monkeypatch) -> None:
    monkeypatch.setattr(mcp_mod, "_max_answer_streams_per_identity", lambda app: 1)
    sess = await init_session(gc_, ELICIT)
    first = open_call(gc_, sess, _args("ask"), rid=1)
    await first.wait_events(1)
    r = await gc_.post("/mcp", json=_call_body(_args("ask"), 2), headers={**sess, "Accept": SSE_ACCEPT})
    assert r.headers["content-type"].startswith("application/json")
    assert len(_answer_streams(gc_.app)) == 1
    await first.stop()


async def test_accept_then_real_disconnect_action_runs_once(gc_) -> None:
    """D-04 (28b): disconnect right after the accept resolves the Future."""
    sess = await init_session(gc_, ELICIT)
    streams = _answer_streams(gc_.app)
    call = open_call(gc_, sess, _args("gate"))
    await call.wait_events(1)
    r = await accept(gc_, sess, call.events[0]["id"], {"decision": "approved"})
    assert r.status_code == 202
    call.disconnect()
    await call.finish()
    await asyncio.wait_for(STATE.entered.wait(), 3)
    assert len(streams) == 1
    assert STATE.actions == 0
    STATE.block.set()
    await settle(lambda: len(streams) == 0)
    assert STATE.actions == 1
    assert len(pending(gc_.app)) == 0


async def test_disconnect_while_response_start_is_held(gc_) -> None:
    """D-04 (29): a real disconnect while http.response.start is stuck."""
    sess = await init_session(gc_, ELICIT)
    streams = _answer_streams(gc_.app)
    call = open_call(gc_, sess, _args("ask"), hold_start=True)
    await settle(lambda: call.status is not None)
    call.disconnect()
    await asyncio.sleep(0.1)
    call.start_gate.set()
    await call.finish()
    await settle(lambda: len(streams) == 0)
    assert len(pending(gc_.app)) == 0
    assert STATE.handler_calls == []


async def test_cancelled_notification_ends_waiting_call(gc_) -> None:
    """D-07: notifications/cancelled for a waiting tools/call frees it."""
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("ask"), rid=41)
    await call.wait_events(1)
    r = await gc_.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 41}},
        headers=sess,
    )
    assert r.status_code == 202
    await call.finish()
    final = call.events[-1]
    assert final["id"] == 41 and is_error(final)
    assert text(final) == mcp_mod.MCP_ELICIT_CANCELLED
    assert len(pending(gc_.app)) == 0
    assert len(_answer_streams(gc_.app)) == 0
    assert STATE.handler_calls == []


async def test_cancelled_notification_of_other_session_or_id_is_ignored(gc_) -> None:
    sess = await init_session(gc_, ELICIT)
    other = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("ask"), rid=41)
    await call.wait_events(1)
    for headers, rid in ((other, 41), (sess, 42), (sess, "41"), (sess, True)):
        r = await gc_.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": rid}},
            headers=headers,
        )
        assert r.status_code == 202
    await asyncio.sleep(0.1)
    assert not call.task.done() and len(pending(gc_.app)) == 1
    await call.stop()


async def test_resume_handler_validation_error_is_generic(gc_) -> None:
    """D-10: not rendered against the tool's input model."""
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("ask_validation"))
    await call.wait_events(1)
    await accept(gc_, sess, call.events[0]["id"], {"name": "bob"})
    await call.finish()
    final = call.events[-1]
    assert is_error(final) and text(final) == "tool execution failed"


async def test_reraised_interrupt_returns_first_interrupt_error(gc_, caplog) -> None:
    """D-11: same response JSON mode sends; re-raise logged by tool name only."""
    caplog.set_level(logging.INFO, logger="agent_sdk")
    STATE.block.set()
    sess = await init_session(gc_, ELICIT)
    call = open_call(gc_, sess, _args("ask_reraise"))
    await call.wait_events(1)
    await accept(gc_, sess, call.events[0]["id"], {"name": "bob"})
    await call.finish()
    assert call.events[-1] == EXPECTED_INTERRUPT
    logged = [r.getMessage() for r in caplog.records if "re-raised" in r.getMessage()]
    assert logged == ["mcp elicitation re-raised, answering with the first interrupt tool=gh224_tool"]


async def test_catch_all_log_has_error_type_and_frames_not_message(gc_, monkeypatch, caplog) -> None:
    """D-12."""

    async def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("SECRET-LEAK")

    sess = await init_session(gc_, ELICIT)
    monkeypatch.setattr(mcp_mod, "_dispatch", boom)
    call = open_call(gc_, sess, _args("plain"))
    await call.finish()
    assert call.events[0]["error"]["code"] == -32603
    msgs = [r.getMessage() for r in caplog.records if "mcp stream response failed" in r.getMessage()]
    assert len(msgs) == 1
    assert "error_type=RuntimeError" in msgs[0] and "frames=" in msgs[0]
    assert "SECRET-LEAK" not in caplog.text


@pytest.mark.parametrize("bad", ["inf", "-inf", "nan", "0", "-1", "86401"])
def test_elicitation_timeout_setting_rejects_unbounded(tmp_path, bad) -> None:
    """D-13."""
    from agent_sdk.config import BaseAgentSettings

    with pytest.raises(ValidationError):
        BaseAgentSettings(
            DEV_MODE=True,
            DATA_DIR=str(tmp_path / "d"),
            AGENT_NAME="t",
            AGENT_SDK_MCP_ELICITATION_TIMEOUT_SECONDS=bad,
        )
