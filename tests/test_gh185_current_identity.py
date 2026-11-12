"""GH-185: agent_sdk.auth.current_identity() inside tools and adapters.
Ruling: https://github.com/wailuen/a2a-sdk/issues/185#issuecomment-6217407102"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from agent_sdk import Agent, BaseAgentSettings, SourceAdapter
from agent_sdk.agent.loop import ToolInterrupt
from agent_sdk.agent.registry import ToolSet
from agent_sdk.auth import Identity, current_identity
from agent_sdk.testing import reply, tool_call

tools = ToolSet()
seen: list[tuple[str | None, str | None]] = []
_arrived = 0
_both: asyncio.Event | None = None
_overlap = True


class WhoSource(SourceAdapter):
    source_name = "who"
    _no_http = True
    allowed_hosts: list[str] = []

    def caller_label(self) -> str | None:
        ident = current_identity()
        return ident.label if ident else None


class NoInput(BaseModel):
    pass


@tools.tool(tier=1)
async def whoami(inp: NoInput, *, src: WhoSource) -> dict[str, Any]:
    """Record the caller seen by the tool and by its adapter, before and after an overlap."""
    global _arrived, _both
    ident = current_identity()
    before = ident.label if ident else None
    _arrived += 1
    if not _overlap:
        seen.append((before, src.caller_label()))
        return {"ok": True}
    if _both is None:
        _both = asyncio.Event()
    if _arrived >= 2:
        _both.set()
    try:
        await asyncio.wait_for(_both.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        pass
    after = current_identity()
    seen.append((before, src.caller_label()))
    seen.append((after.label if after else None, None))
    return {"ok": True}


resumed: list[str | None] = []


async def _record_resume(value: Any) -> dict[str, Any]:
    ident = current_identity()
    resumed.append(ident.label if ident else None)
    return {"answered": True}


@tools.tool(tier=1)
async def ask(inp: NoInput) -> dict[str, Any]:
    """Pause for caller input."""
    raise ToolInterrupt("need", "more?", resume_handler=_record_resume)


class IdentityAwareModel:
    async def converse(self, *, system, messages, tools, max_tokens=4096, tool_choice="auto"):
        first = messages[0]["content"][0].get("text", "")
        if first == "ask":
            done = any(
                isinstance(b, dict) and "toolResult" in b
                for m in messages
                for b in (m.get("content") or [])
            )
            return reply("done") if done else tool_call("ask", {})
        done = any(
            isinstance(b, dict) and "toolResult" in b
            for m in messages
            for b in (m.get("content") or [])
        )
        return reply("done") if done else tool_call("whoami", {})


@pytest.fixture
def app(tmp_path):
    global _arrived, _both, _overlap
    seen.clear()
    _overlap = True
    _arrived = 0
    _both = None
    settings = BaseAgentSettings(
        DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="who-agent"
    )
    agent = Agent(
        settings=settings,
        persona="who",
        skills_dir=Path(__file__).parent.parent / "agent_sdk" / "example" / "skills",
        toolsets=[tools],
        model_client=IdentityAwareModel(),
    )
    agent.register_source(WhoSource)
    built = agent.build_app()
    yield built
    built.state.credential_store.close()


def _clients(app):
    keys = app.state.auth.api_keys
    out = []
    for label in ("alice", "bob"):
        _, tok = keys.mint(label)
        out.append(
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers={"Authorization": f"Bearer {tok}", "MCP-Protocol-Version": "2025-06-18"},
            )
        )
    return out


def _send_body() -> dict:
    return {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": "who"}],
            "messageId": uuid.uuid4().hex,
        }
    }


async def _finish(c, task_id):
    for _ in range(300):
        r = await c.get(f"/v1/tasks/{task_id}")
        if r.json()["status"]["state"] in ("completed", "failed"):
            return r.json()
        await asyncio.sleep(0.02)
    raise AssertionError("task did not finish")


def _assert_isolated():
    assert sorted(seen, key=repr) == sorted(
        [("alice", "alice"), ("alice", None), ("bob", "bob"), ("bob", None)], key=repr
    )


def test_none_outside_request():
    assert current_identity() is None


def test_identity_is_frozen_and_only_identity():
    ident = Identity(kind="api_key", subject="k1", label="x")
    with pytest.raises(dataclasses.FrozenInstanceError):
        ident.label = "y"  # type: ignore[misc]


async def test_a2a_send_isolated(app):
    async with app.router.lifespan_context(app):
        a, b = _clients(app)
        ra, rb = await asyncio.gather(
            a.post("/v1/message:send", json=_send_body()),
            b.post("/v1/message:send", json=_send_body()),
        )
        await _finish(a, ra.json()["id"])
        await _finish(b, rb.json()["id"])
        _assert_isolated()
        assert current_identity() is None
        await a.aclose()
        await b.aclose()


async def test_a2a_stream_isolated(app):
    async with app.router.lifespan_context(app):
        a, b = _clients(app)

        async def stream(c):
            async with c.stream("POST", "/v1/message:stream", json=_send_body()) as r:
                async for _ in r.aiter_lines():
                    pass

        await asyncio.gather(stream(a), stream(b))
        _assert_isolated()
        await a.aclose()
        await b.aclose()


async def test_ag_ui_isolated(app):
    async with app.router.lifespan_context(app):
        a, b = _clients(app)

        async def run(c):
            body = {
                "threadId": uuid.uuid4().hex,
                "runId": uuid.uuid4().hex,
                "messages": [{"id": "m1", "role": "user", "content": "who"}],
                "state": {},
                "tools": [],
                "context": [],
                "forwardedProps": {},
            }
            r = await c.post("/ag-ui/run", json=body)
            assert r.status_code == 200

        await asyncio.gather(run(a), run(b))
        _assert_isolated()
        await a.aclose()
        await b.aclose()


async def test_mcp_isolated(app):
    async with app.router.lifespan_context(app):
        a, b = _clients(app)

        async def call(c):
            r = await c.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "whoami", "arguments": {}},
                },
            )
            assert r.status_code == 200, r.text
            assert "error" not in r.json()

        await asyncio.gather(call(a), call(b))
        _assert_isolated()
        # no leak into the next request on the same worker
        await call(a)
        assert current_identity() is None
        await a.aclose()
        await b.aclose()


async def test_resume_binds_resuming_caller(app):
    resumed.clear()
    async with app.router.lifespan_context(app):
        a, _ = _clients(app)
        _, admin_tok = app.state.auth.api_keys.mint("root", admin=True)
        admin = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {admin_tok}"},
        )
        body = _send_body()
        body["message"]["parts"][0]["text"] = "ask"
        r = await a.post("/v1/message:send", json=body)
        tid = r.json()["id"]
        for _ in range(300):
            st = (await a.get(f"/v1/tasks/{tid}")).json()["status"]["state"]
            if st == "input-required":
                break
            await asyncio.sleep(0.02)
        assert st == "input-required"
        resume = _send_body()
        resume["message"]["taskId"] = tid
        resume["message"]["parts"][0]["text"] = "answer"
        r = await admin.post("/v1/message:send", json=resume)
        assert r.status_code == 200, r.text
        await _finish(a, tid)
        assert resumed == ["root"]
        await a.aclose()
        await admin.aclose()


async def test_resubscribe_still_streams(app):
    async with app.router.lifespan_context(app):
        a, _ = _clients(app)
        r = await a.post("/v1/message:send", json=_send_body())
        tid = r.json()["id"]
        await _finish(a, tid)
        resp = await a.post(f"/v1/tasks/{tid}:subscribe")
        assert resp.status_code == 200
        await a.aclose()


async def test_no_identity_value_logged(app, caplog):
    caplog.set_level(logging.DEBUG)
    async with app.router.lifespan_context(app):
        a, b = _clients(app)
        r = await a.post("/v1/message:send", json=_send_body())
        await _finish(a, r.json()["id"])
        await a.aclose()
        await b.aclose()
    assert "alice" not in json.dumps([rec.getMessage() for rec in caplog.records])


def _ag_body(text="who", **extra) -> dict:
    return {
        "threadId": uuid.uuid4().hex,
        "runId": uuid.uuid4().hex,
        "messages": [{"id": "m1", "role": "user", "content": text}],
        "state": {},
        "tools": [],
        "context": [],
        "forwardedProps": {},
        **extra,
    }


def _mcp_call() -> dict:
    return {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "whoami", "arguments": {}},
    }


@pytest.fixture
def bind_spy(monkeypatch):
    calls: list[Any] = []
    import agent_sdk.routes.a2a as a2a_mod
    import agent_sdk.routes.ag_ui as ag_mod
    import agent_sdk.routes.mcp as mcp_mod

    for mod in (a2a_mod, ag_mod, mcp_mod):
        real = mod.bind_identity

        def spy(identity, _real=real):
            calls.append(identity)
            return _real(identity)

        monkeypatch.setattr(mod, "bind_identity", spy)
    return calls


@pytest.mark.parametrize("auth", [None, "Bearer not-a-real-key"])
async def test_rejected_request_never_binds(app, bind_spy, auth):
    headers = {"MCP-Protocol-Version": "2025-06-18"}
    if auth:
        headers["Authorization"] = auth
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", headers=headers
        ) as c:
            for path, body in (
                ("/v1/message:send", _send_body()),
                ("/v1/message:stream", _send_body()),
                ("/ag-ui/run", _ag_body()),
                ("/mcp", _mcp_call()),
                ("/mcp/messages?sessionId=nope", _mcp_call()),
            ):
                r = await c.post(path, json=body)
                assert r.status_code == 401, (path, r.status_code)
    assert bind_spy == []
    assert seen == []


async def _direct_call_sees_none():
    out = await whoami(NoInput(), src=WhoSource.__new__(WhoSource))
    assert out == {"ok": True}
    assert seen[-1] == (None, None)


async def _sequential(app, send):
    global _overlap
    _overlap = False
    async with app.router.lifespan_context(app):
        a, b = _clients(app)
        await send(a)
        await send(b)
        assert seen == [("alice", "alice"), ("bob", "bob")]
        await _direct_call_sees_none()
        await a.aclose()
        await b.aclose()


async def test_a2a_send_no_leak_between_requests(app):
    async def send(c):
        r = await c.post("/v1/message:send", json=_send_body())
        await _finish(c, r.json()["id"])

    await _sequential(app, send)


async def test_a2a_stream_no_leak_between_requests(app):
    async def send(c):
        async with c.stream("POST", "/v1/message:stream", json=_send_body()) as r:
            async for _ in r.aiter_lines():
                pass

    await _sequential(app, send)


async def test_ag_ui_no_leak_between_requests(app):
    async def send(c):
        r = await c.post("/ag-ui/run", json=_ag_body())
        assert r.status_code == 200

    await _sequential(app, send)


async def test_mcp_no_leak_between_requests(app):
    async def send(c):
        r = await c.post("/mcp", json=_mcp_call())
        assert r.status_code == 200, r.text
        assert "error" not in r.json()

    await _sequential(app, send)


async def test_data_part_resume_binds_resuming_caller(app):
    resumed.clear()
    async with app.router.lifespan_context(app):
        a, _ = _clients(app)
        _, admin_tok = app.state.auth.api_keys.mint("root", admin=True)
        admin = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {admin_tok}"},
        )
        body = _send_body()
        body["message"]["parts"][0]["text"] = "ask"
        tid = (await a.post("/v1/message:send", json=body)).json()["id"]
        for _ in range(300):
            st = (await a.get(f"/v1/tasks/{tid}")).json()["status"]["state"]
            if st == "input-required":
                break
            await asyncio.sleep(0.02)
        assert st == "input-required"
        resume = _send_body()
        resume["message"]["taskId"] = tid
        resume["message"]["parts"] = [{"kind": "data", "data": {"decision": "approved"}}]
        r = await admin.post("/v1/message:send", json=resume)
        assert r.status_code == 200, r.text
        await _finish(a, tid)
        assert resumed == ["root"]
        await a.aclose()
        await admin.aclose()


async def test_stream_resume_binds_resuming_caller(app):
    resumed.clear()
    async with app.router.lifespan_context(app):
        a, _ = _clients(app)
        _, admin_tok = app.state.auth.api_keys.mint("root", admin=True)
        admin = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {admin_tok}"},
        )
        body = _send_body()
        body["message"]["parts"][0]["text"] = "ask"
        tid = (await a.post("/v1/message:send", json=body)).json()["id"]
        for _ in range(300):
            st = (await a.get(f"/v1/tasks/{tid}")).json()["status"]["state"]
            if st == "input-required":
                break
            await asyncio.sleep(0.02)
        assert st == "input-required"
        resume = _send_body()
        resume["message"]["taskId"] = tid
        resume["message"]["parts"][0]["text"] = "answer"
        async with admin.stream("POST", "/v1/message:stream", json=resume) as r:
            assert r.status_code == 200
            async for _ in r.aiter_lines():
                pass
        await _finish(a, tid)
        assert resumed == ["root"]
        await a.aclose()
        await admin.aclose()


async def test_ag_ui_resume_binds_resuming_caller(app):
    resumed.clear()
    async with app.router.lifespan_context(app):
        a, _ = _clients(app)
        _, admin_tok = app.state.auth.api_keys.mint("root", admin=True)
        admin = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {admin_tok}"},
        )
        r = await a.post("/ag-ui/run", json=_ag_body("ask"))
        frames = [
            json.loads(line[5:])
            for line in r.text.splitlines()
            if line.startswith("data:")
        ]
        outcome = frames[-1]["outcome"]
        assert outcome["type"] == "interrupt"
        intr = outcome["interrupts"][0]
        r = await admin.post(
            "/ag-ui/run",
            json=_ag_body(
                "ask",
                resume=[{"interruptId": intr["id"], "status": "resolved", "payload": {}}],
            ),
        )
        assert r.status_code == 200
        assert "RUN_FINISHED" in r.text
        assert resumed == ["root"]
        await a.aclose()
        await admin.aclose()


def _admin(app, label):
    _, tok = app.state.auth.api_keys.mint(label, admin=True)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {tok}"},
    )


async def test_a2a_concurrent_resumers_winner_identity_kept(app):
    resumed.clear()
    async with app.router.lifespan_context(app):
        a, _ = _clients(app)
        root, root2 = _admin(app, "root"), _admin(app, "root2")
        body = _send_body()
        body["message"]["parts"][0]["text"] = "ask"
        tid = (await a.post("/v1/message:send", json=body)).json()["id"]
        for _ in range(300):
            if (await a.get(f"/v1/tasks/{tid}")).json()["status"]["state"] == "input-required":
                break
            await asyncio.sleep(0.02)

        def resume_body():
            b = _send_body()
            b["message"]["taskId"] = tid
            return b

        r1, r2 = await asyncio.gather(
            root.post("/v1/message:send", json=resume_body()),
            root2.post("/v1/message:send", json=resume_body()),
        )
        winners = [lbl for lbl, r in (("root", r1), ("root2", r2)) if r.json().get("error") is None]
        assert len(winners) == 1
        await _finish(a, tid)
        assert resumed == winners
        for c in (a, root, root2):
            await c.aclose()


async def test_ag_ui_concurrent_resumers_winner_identity_kept(app):
    resumed.clear()
    async with app.router.lifespan_context(app):
        a, _ = _clients(app)
        root, root2 = _admin(app, "root"), _admin(app, "root2")
        r = await a.post("/ag-ui/run", json=_ag_body("ask"))
        frames = [json.loads(ln[5:]) for ln in r.text.splitlines() if ln.startswith("data:")]
        intr = frames[-1]["outcome"]["interrupts"][0]
        resume = [{"interruptId": intr["id"], "status": "resolved", "payload": {}}]
        r1, r2 = await asyncio.gather(
            root.post("/ag-ui/run", json=_ag_body("ask", resume=resume)),
            root2.post("/ag-ui/run", json=_ag_body("ask", resume=resume)),
        )
        winners = [lbl for lbl, r in (("root", r1), ("root2", r2)) if "RUN_FINISHED" in r.text]
        assert len(winners) == 1
        assert resumed == winners
        for c in (a, root, root2):
            await c.aclose()


# ── GH-276: admin try-tool binds identity + forwarded credentials ──

import base64  # noqa: E402

from agent_sdk import CredentialField  # noqa: E402
from agent_sdk.credentials import forwarding as _fwd  # noqa: E402
from agent_sdk.models.errors import AgentError, ErrorCategory  # noqa: E402

try_tools = ToolSet()
try_seen: list[Any] = []
try_runs: list[str] = []


class TryProbeSource(SourceAdapter):
    source_name = "tryprobe"
    _no_http = True
    allowed_hosts: list[str] = []


@try_tools.tool(tier=1)
async def try_who(inp: NoInput) -> dict[str, Any]:
    """Record the caller identity."""
    try_runs.append("try_who")
    try_seen.append(current_identity())
    return {"ok": True}


@try_tools.tool(tier=1)
async def try_cred(inp: NoInput, *, src: TryProbeSource) -> dict[str, Any]:
    """Read the forwarded credential through the adapter."""
    try_runs.append("try_cred")
    return {"value": src.credential("api_key")}


@try_tools.tool(tier=1)
async def try_cred_opt(inp: NoInput, *, src: TryProbeSource) -> dict[str, Any]:
    """Read the credential, None when absent."""
    try_runs.append("try_cred_opt")
    return {"value": src.credential_or_none("api_key")}


@try_tools.tool(tier=1)
async def try_fail(inp: NoInput) -> dict[str, Any]:
    """Record the caller identity, then raise AgentError."""
    try_runs.append("try_fail")
    try_seen.append(current_identity())
    raise AgentError(ErrorCategory.VALIDATION, "nope", source="x")


@try_tools.tool(tier=1)
async def try_slow(inp: NoInput) -> dict[str, Any]:
    """Record the caller identity, then hang."""
    try_runs.append("try_slow")
    try_seen.append(current_identity())
    await asyncio.sleep(5)
    return {"ok": True}


@pytest.fixture
def try_app(tmp_path):
    try_seen.clear()
    try_runs.clear()
    settings = BaseAgentSettings(
        DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="try-agent"
    )
    agent = Agent(
        settings=settings,
        persona="try",
        skills_dir=Path(__file__).parent.parent / "agent_sdk" / "example" / "skills",
        toolsets=[try_tools],
        model_client=IdentityAwareModel(),
    )
    agent.register_source(
        TryProbeSource, credentials=[CredentialField(name="api_key", label="API key")]
    )
    built = agent.build_app()
    yield built
    built.state.credential_store.close()


def _try_client(app, token, **headers):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}", **headers},
    )


class _BindSpy:
    """Records bind tokens and the tokens passed to unbind, seen from inside
    the request's own context (the test task never sees a leak: ASGITransport
    runs the app in a copied context)."""

    def __init__(self, monkeypatch):
        import agent_sdk.routes.admin as admin_mod

        self.bound: dict[str, list[Any]] = {"identity": [], "fwd": []}
        self.unbound: dict[str, list[Any]] = {"identity": [], "fwd": []}
        real = {
            "identity": (admin_mod.bind_identity, admin_mod.unbind_identity),
            "fwd": (_fwd.bind, _fwd.unbind),
        }

        def wrap_bind(kind):
            def bind(value):
                tok = real[kind][0](value)
                self.bound[kind].append(tok)
                return tok

            return bind

        def wrap_unbind(kind):
            def unbind(tok):
                self.unbound[kind].append(tok)
                return real[kind][1](tok)

            return unbind

        monkeypatch.setattr(admin_mod, "bind_identity", wrap_bind("identity"))
        monkeypatch.setattr(admin_mod, "unbind_identity", wrap_unbind("identity"))
        monkeypatch.setattr(_fwd, "bind", wrap_bind("fwd"))
        monkeypatch.setattr(_fwd, "unbind", wrap_unbind("fwd"))

    def assert_balanced(self, runs: int):
        for kind in ("identity", "fwd"):
            assert len(self.bound[kind]) == runs
            assert len(self.unbound[kind]) == runs
            for tok in self.bound[kind]:
                assert sum(1 for u in self.unbound[kind] if u is tok) == 1


async def test_admin_try_binds_admin_identity(try_app, monkeypatch):
    spy = _BindSpy(monkeypatch)
    async with try_app.router.lifespan_context(try_app):
        _, tok = try_app.state.auth.api_keys.mint("root", admin=True)
        async with _try_client(try_app, tok) as c:
            r = await c.post("/admin/api/tools/try_who/try", json={})
            assert r.status_code == 200 and r.json()["ok"] is True
            r = await c.post("/admin/api/tools/try_who/try", json={})
        assert len(try_seen) == 2
        for ident in try_seen:
            assert ident.kind == "api_key" and ident.admin is True and ident.label == "root"
        spy.assert_balanced(2)


async def test_admin_try_unbinds_on_agent_error_and_timeout(try_app, monkeypatch):
    import agent_sdk.routes.admin as admin_mod

    monkeypatch.setattr(admin_mod, "_TRY_TIMEOUTS", {1: 0.05, 2: 0.05})
    spy = _BindSpy(monkeypatch)
    async with try_app.router.lifespan_context(try_app):
        _, tok = try_app.state.auth.api_keys.mint("root", admin=True)
        async with _try_client(
            try_app, tok, **{"X-Agent-Credentials": _hdr("FWD")}
        ) as c:
            r = await c.post("/admin/api/tools/try_fail/try", json={})
            assert r.json()["ok"] is False and r.json()["error"]["category"] == "validation"
            spy.assert_balanced(1)
            r = await c.post("/admin/api/tools/try_slow/try", json={})
            assert r.json()["error"]["category"] == "timeout"
            spy.assert_balanced(2)
            await c.post("/admin/api/tools/try_who/try", json={})
        assert [i.label for i in try_seen] == ["root"] * 3
        spy.assert_balanced(3)


def _hdr(value: str) -> str:
    return base64.b64encode(json.dumps({"tryprobe": {"api_key": value}}).encode()).decode()


@pytest.mark.parametrize("who", ["none", "bad", "nonadmin"])
async def test_admin_try_rejected_never_binds_or_runs(try_app, monkeypatch, who):
    import agent_sdk.routes.admin as admin_mod

    calls: list[Any] = []
    real_id, real_fw = admin_mod.bind_identity, admin_mod.forwarding.bind
    monkeypatch.setattr(
        admin_mod, "bind_identity", lambda i: (calls.append(i), real_id(i))[1]
    )
    monkeypatch.setattr(
        admin_mod.forwarding, "bind", lambda c: (calls.append(c), real_fw(c))[1]
    )
    async with try_app.router.lifespan_context(try_app):
        if who == "none":
            tok, want = None, 401
        elif who == "bad":
            tok, want = "not-a-real-key", 401
        else:
            _, tok = try_app.state.auth.api_keys.mint("plain")
            want = 403
        headers = {"Authorization": f"Bearer {tok}"} if tok else {}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=try_app), base_url="http://test", headers=headers
        ) as c:
            r = await c.post("/admin/api/tools/try_who/try", json={})
            assert r.status_code == want
    assert calls == []
    assert try_runs == []


async def test_admin_try_forwarded_credentials_via_adapter(try_app, monkeypatch):
    spy = _BindSpy(monkeypatch)
    async with try_app.router.lifespan_context(try_app):
        _, tok = try_app.state.auth.api_keys.mint("root", admin=True)
        async with _try_client(try_app, tok) as c:
            r = await c.post(
                "/admin/api/tools/try_cred/try",
                json={},
                headers={"X-Agent-Credentials": _hdr("FWD-1")},
            )
            assert r.json()["result"] == {"value": "FWD-1"}
            spy.assert_balanced(1)
            r = await c.post("/admin/api/tools/try_cred_opt/try", json={})
            assert r.json()["result"] == {"value": None}
            spy.assert_balanced(2)
