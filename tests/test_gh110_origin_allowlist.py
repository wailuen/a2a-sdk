"""GH-110 (RT-004 parity): the Origin allow-list guard mcp.py enforces on
every browser-reachable streaming surface (POST/GET/DELETE /mcp, legacy SSE
pair) was missing on POST /ag-ui/run and all six A2A HTTP+JSON handlers
(message_send, message_stream, tasks_list, tasks_get, tasks_cancel,
tasks_resubscribe). Each of those seven routes must now reject a
non-allowlisted Origin with 403 (mirroring agent_sdk/routes/mcp.py:446-448
exactly) while an absent or allowlisted Origin passes through unaffected.
"""

from __future__ import annotations

import gc
import uuid
from typing import AsyncIterator

import httpx
import pytest

from agent_sdk import BaseAgentSettings
from agent_sdk.example.agent import make_agent
from agent_sdk.testing import FakeModelClient, reply

from .conftest import sse_frames, wait_for_state

_EVIL = "https://evil.example.com"
_ALLOWED = "https://claude.ai"  # always present in app.state.cors_origins

# Cross-surface origin-403 body shapes (RT-002): the guard raises the same
# HTTPException(403, "origin not allowed") everywhere, but the /v1/* surface
# has an app-level exception handler (_a2a_auth_envelope, app.py) that rewrites
# it into the A2A JSON-RPC error envelope, whereas MCP and AG-UI — which have
# no such handler — return FastAPI's bare {"detail": ...}. Pinning both shapes
# makes that divergence a tested contract, not an accident a refactor can flip.
_A2A_ORIGIN_403_BODY = {"error": {"code": -32000, "message": "origin not allowed"}}
_BARE_ORIGIN_403_BODY = {"detail": "origin not allowed"}


def send_body(text: str, task_id: str | None = None) -> dict:
    msg = {
        "role": "user",
        "parts": [{"kind": "text", "text": text}],
        "messageId": uuid.uuid4().hex,
    }
    if task_id:
        msg["taskId"] = task_id
    return {"message": msg}


def run_body(text: str = "hello", **extra) -> dict:
    return {
        "threadId": "t1",
        "runId": "r1",
        "messages": [{"id": "m1", "role": "user", "content": text}],
        "state": {},
        "tools": [],
        "context": [],
        "forwardedProps": {},
        **extra,
    }


# ---------------------------------------------------------------------------
# AG-UI — POST /ag-ui/run
# ---------------------------------------------------------------------------


async def test_ag_ui_run_rejects_disallowed_origin(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/ag-ui/run", json=run_body(), headers={"Origin": _EVIL}
    )
    assert r.status_code == 403, (
        f"POST /ag-ui/run with non-allowlisted origin must return 403; got {r.status_code}: {r.text}"
    )
    # AG-UI has no envelope handler: bare FastAPI {"detail": ...} (RT-002).
    assert r.json() == _BARE_ORIGIN_403_BODY, r.text


async def test_ag_ui_run_allows_absent_origin(client: httpx.AsyncClient, fake_model) -> None:
    from agent_sdk.testing import reply

    fake_model.script(reply("hi there"))
    r = await client.post("/ag-ui/run", json=run_body())
    assert r.status_code == 200, r.text
    frames = sse_frames(r.text)
    assert frames[0]["type"] == "RUN_STARTED"


async def test_ag_ui_run_allows_allowlisted_origin(client: httpx.AsyncClient, fake_model) -> None:
    from agent_sdk.testing import reply

    fake_model.script(reply("hi there"))
    r = await client.post(
        "/ag-ui/run", json=run_body(), headers={"Origin": _ALLOWED}
    )
    assert r.status_code == 200, r.text
    frames = sse_frames(r.text)
    assert frames[0]["type"] == "RUN_STARTED"


# ---------------------------------------------------------------------------
# A2A — POST /v1/message:send
# ---------------------------------------------------------------------------


async def test_message_send_rejects_disallowed_origin(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/v1/message:send", json=send_body("hi"), headers={"Origin": _EVIL}
    )
    assert r.status_code == 403, (
        f"POST /v1/message:send with non-allowlisted origin must return 403; got {r.status_code}: {r.text}"
    )
    # /v1/* is rewritten into the A2A JSON-RPC envelope, NOT bare {"detail"} (RT-002).
    assert r.json() == _A2A_ORIGIN_403_BODY, r.text


async def test_message_send_allows_absent_origin(client: httpx.AsyncClient, fake_model) -> None:
    from agent_sdk.testing import reply

    fake_model.script(reply("done"))
    r = await client.post("/v1/message:send", json=send_body("hi"))
    assert r.status_code == 200, r.text


async def test_message_send_allows_allowlisted_origin(client: httpx.AsyncClient, fake_model) -> None:
    from agent_sdk.testing import reply

    fake_model.script(reply("done"))
    r = await client.post(
        "/v1/message:send", json=send_body("hi"), headers={"Origin": _ALLOWED}
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# A2A — POST /v1/message:stream
# ---------------------------------------------------------------------------


async def test_message_stream_rejects_disallowed_origin(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/v1/message:stream", json=send_body("hi"), headers={"Origin": _EVIL}
    )
    assert r.status_code == 403, (
        f"POST /v1/message:stream with non-allowlisted origin must return 403; got {r.status_code}: {r.text}"
    )
    assert r.json() == _A2A_ORIGIN_403_BODY, r.text


async def test_message_stream_allows_absent_origin(client: httpx.AsyncClient, fake_model) -> None:
    from agent_sdk.testing import reply

    fake_model.script(reply("streamed"))
    async with client.stream(
        "POST", "/v1/message:stream", json=send_body("hi")
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")


async def test_message_stream_allows_allowlisted_origin(client: httpx.AsyncClient, fake_model) -> None:
    from agent_sdk.testing import reply

    fake_model.script(reply("streamed"))
    async with client.stream(
        "POST",
        "/v1/message:stream",
        json=send_body("hi"),
        headers={"Origin": _ALLOWED},
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")


# ---------------------------------------------------------------------------
# A2A — GET /v1/tasks
# ---------------------------------------------------------------------------


async def test_tasks_list_rejects_disallowed_origin(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/tasks", headers={"Origin": _EVIL})
    assert r.status_code == 403, (
        f"GET /v1/tasks with non-allowlisted origin must return 403; got {r.status_code}: {r.text}"
    )
    assert r.json() == _A2A_ORIGIN_403_BODY, r.text


async def test_tasks_list_allows_absent_origin(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/tasks")
    assert r.status_code == 200, r.text


async def test_tasks_list_allows_allowlisted_origin(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/tasks", headers={"Origin": _ALLOWED})
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# A2A — GET /v1/tasks/{task_id}
# ---------------------------------------------------------------------------


async def test_tasks_get_rejects_disallowed_origin(client: httpx.AsyncClient) -> None:
    # Origin guard fires before task lookup — a bogus id still 403s, not 404.
    r = await client.get("/v1/tasks/nonexistent", headers={"Origin": _EVIL})
    assert r.status_code == 403, (
        f"GET /v1/tasks/{{id}} with non-allowlisted origin must return 403; got {r.status_code}: {r.text}"
    )
    assert r.json() == _A2A_ORIGIN_403_BODY, r.text


async def test_tasks_get_allows_absent_origin(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/tasks/nonexistent")
    assert r.status_code == 404, r.text


async def test_tasks_get_allows_allowlisted_origin(client: httpx.AsyncClient) -> None:
    r = await client.get("/v1/tasks/nonexistent", headers={"Origin": _ALLOWED})
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------
# A2A — POST /v1/tasks/{task_id}:cancel
# ---------------------------------------------------------------------------


async def test_tasks_cancel_rejects_disallowed_origin(client: httpx.AsyncClient) -> None:
    r = await client.post("/v1/tasks/nonexistent:cancel", headers={"Origin": _EVIL})
    assert r.status_code == 403, (
        f"POST /v1/tasks/{{id}}:cancel with non-allowlisted origin must return 403; got {r.status_code}: {r.text}"
    )
    assert r.json() == _A2A_ORIGIN_403_BODY, r.text


async def test_tasks_cancel_allows_absent_origin(client: httpx.AsyncClient) -> None:
    r = await client.post("/v1/tasks/nonexistent:cancel")
    assert r.status_code == 404, r.text


async def test_tasks_cancel_allows_allowlisted_origin(client: httpx.AsyncClient) -> None:
    r = await client.post("/v1/tasks/nonexistent:cancel", headers={"Origin": _ALLOWED})
    assert r.status_code == 404, r.text


# ---------------------------------------------------------------------------
# A2A — POST /v1/tasks/{task_id}:subscribe
# ---------------------------------------------------------------------------


async def test_tasks_resubscribe_rejects_disallowed_origin(client: httpx.AsyncClient) -> None:
    r = await client.post("/v1/tasks/nonexistent:subscribe", headers={"Origin": _EVIL})
    assert r.status_code == 403, (
        f"POST /v1/tasks/{{id}}:subscribe with non-allowlisted origin must return 403; got {r.status_code}: {r.text}"
    )
    assert r.json() == _A2A_ORIGIN_403_BODY, r.text


async def test_tasks_resubscribe_allows_absent_origin(client: httpx.AsyncClient, fake_model) -> None:
    from agent_sdk.testing import reply

    fake_model.script(reply("done"))
    r = await client.post("/v1/message:send", json=send_body("hi"))
    task_id = r.json()["id"]
    await wait_for_state(client, task_id)

    r2 = await client.post(f"/v1/tasks/{task_id}:subscribe")
    assert r2.status_code != 403, r2.text


async def test_tasks_resubscribe_allows_allowlisted_origin(client: httpx.AsyncClient, fake_model) -> None:
    from agent_sdk.testing import reply

    fake_model.script(reply("done"))
    r = await client.post("/v1/message:send", json=send_body("hi"))
    task_id = r.json()["id"]
    await wait_for_state(client, task_id)

    r2 = await client.post(
        f"/v1/tasks/{task_id}:subscribe", headers={"Origin": _ALLOWED}
    )
    assert r2.status_code != 403, r2.text


# ---------------------------------------------------------------------------
# MCP — /mcp surfaces keep the guard's BARE {"detail": ...} (no envelope
# handler). Pins the other half of the cross-surface divergence (RT-002).
# ---------------------------------------------------------------------------


async def test_mcp_post_rejects_disallowed_origin(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"Origin": _EVIL, "MCP-Protocol-Version": "2025-06-18"},
    )
    assert r.status_code == 403, r.text
    assert r.json() == _BARE_ORIGIN_403_BODY, r.text


async def test_mcp_get_rejects_disallowed_origin(client: httpx.AsyncClient) -> None:
    r = await client.get("/mcp", headers={"Origin": _EVIL})
    assert r.status_code == 403, r.text
    assert r.json() == _BARE_ORIGIN_403_BODY, r.text


async def test_mcp_messages_rejects_disallowed_origin(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/mcp/messages?session_id=x",
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
        headers={"Origin": _EVIL},
    )
    assert r.status_code == 403, r.text
    assert r.json() == _BARE_ORIGIN_403_BODY, r.text


# ---------------------------------------------------------------------------
# GH-119: settings.resolved_base_url (the bundled console's own origin on a
# deployed, non-claude.ai agent) must be allowed even when CORS_ORIGINS is
# left unset (default ["https://claude.ai"]). Uses a production-shaped
# PUBLIC_URL *with* a trailing slash to also pin the same normalization
# (rstrip("/")) applied to the configured cors_origins list.
# ---------------------------------------------------------------------------

_OWN_ORIGIN = "https://my-agent.example.com"  # == resolved_base_url, normalized


@pytest.fixture
def own_origin_settings(tmp_path) -> BaseAgentSettings:
    return BaseAgentSettings(
        DEV_MODE=False,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
        PUBLIC_URL=f"{_OWN_ORIGIN}/",
        MASTER_KEY="a" * 32,
    )


@pytest.fixture
def own_origin_fake_model() -> FakeModelClient:
    return FakeModelClient()


@pytest.fixture
def own_origin_app(own_origin_settings: BaseAgentSettings, own_origin_fake_model: FakeModelClient):
    built = make_agent(own_origin_settings, model_client=own_origin_fake_model).build_app()
    yield built
    built.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def own_origin_client(own_origin_app) -> AsyncIterator[httpx.AsyncClient]:
    async with own_origin_app.router.lifespan_context(own_origin_app):
        _, token = own_origin_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=own_origin_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            yield c


def test_own_resolved_base_url_in_app_state_cors_origins(own_origin_app) -> None:
    assert _OWN_ORIGIN in own_origin_app.state.cors_origins, (
        f"resolved_base_url (normalized) must be unioned into app.state.cors_origins; "
        f"got: {own_origin_app.state.cors_origins!r}"
    )


async def test_mcp_post_allows_own_resolved_base_url_origin(
    own_origin_client: httpx.AsyncClient,
) -> None:
    r = await own_origin_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
        headers={"Origin": _OWN_ORIGIN},
    )
    assert r.status_code != 403, (
        f"POST /mcp with Origin == settings.resolved_base_url (CORS_ORIGINS unset) "
        f"must not be 403'd; got {r.status_code}: {r.text}"
    )


async def test_ag_ui_run_allows_own_resolved_base_url_origin(
    own_origin_client: httpx.AsyncClient, own_origin_fake_model: FakeModelClient
) -> None:
    own_origin_fake_model.script(reply("hi there"))
    r = await own_origin_client.post(
        "/ag-ui/run", json=run_body(), headers={"Origin": _OWN_ORIGIN}
    )
    assert r.status_code == 200, r.text
    frames = sse_frames(r.text)
    assert frames[0]["type"] == "RUN_STARTED"


async def test_message_send_allows_own_resolved_base_url_origin(
    own_origin_client: httpx.AsyncClient, own_origin_fake_model: FakeModelClient
) -> None:
    own_origin_fake_model.script(reply("done"))
    r = await own_origin_client.post(
        "/v1/message:send", json=send_body("hi"), headers={"Origin": _OWN_ORIGIN}
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# RT-001 (GH-119 follow-up): a path-prefixed PUBLIC_URL (reverse-proxy
# deployment, e.g. https://gw.example.com/agents/x) must union only its
# ORIGIN component (scheme://host[:port]) into app.state.cors_origins.
# Browser Origin headers are always path-less (RFC 6454), so unioning the
# full resolved_base_url (including path) makes the allow-list entry never
# match the console's real Origin header, and guard_origin() 403s same-origin
# MCP/AG-UI/A2A requests — the exact breakage GH-119 set out to fix.
# ---------------------------------------------------------------------------

_PATH_PREFIXED_BASE = "https://gw.example.com/agents/x"
_PATH_PREFIXED_ORIGIN = "https://gw.example.com"  # what the browser actually sends


@pytest.fixture
def path_prefixed_settings(tmp_path) -> BaseAgentSettings:
    return BaseAgentSettings(
        DEV_MODE=False,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
        PUBLIC_URL=_PATH_PREFIXED_BASE,
        MASTER_KEY="a" * 32,
    )


@pytest.fixture
def path_prefixed_fake_model() -> FakeModelClient:
    return FakeModelClient()


@pytest.fixture
def path_prefixed_app(path_prefixed_settings: BaseAgentSettings, path_prefixed_fake_model: FakeModelClient):
    built = make_agent(path_prefixed_settings, model_client=path_prefixed_fake_model).build_app()
    yield built
    built.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def path_prefixed_client(path_prefixed_app) -> AsyncIterator[httpx.AsyncClient]:
    async with path_prefixed_app.router.lifespan_context(path_prefixed_app):
        _, token = path_prefixed_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=path_prefixed_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            yield c


def test_path_prefixed_public_url_origin_in_cors_origins(path_prefixed_app) -> None:
    assert _PATH_PREFIXED_ORIGIN in path_prefixed_app.state.cors_origins, (
        f"only the origin component (scheme://host[:port]) of a path-prefixed "
        f"PUBLIC_URL must be unioned into app.state.cors_origins, since browser "
        f"Origin headers are always path-less; got: {path_prefixed_app.state.cors_origins!r}"
    )
    assert _PATH_PREFIXED_BASE not in path_prefixed_app.state.cors_origins


async def test_mcp_post_allows_path_prefixed_base_url_origin(
    path_prefixed_client: httpx.AsyncClient,
) -> None:
    r = await path_prefixed_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
        headers={"Origin": _PATH_PREFIXED_ORIGIN},
    )
    assert r.status_code != 403, (
        f"POST /mcp with the path-less Origin derived from a path-prefixed "
        f"PUBLIC_URL must not be 403'd; got {r.status_code}: {r.text}"
    )


async def test_ag_ui_run_allows_path_prefixed_base_url_origin(
    path_prefixed_client: httpx.AsyncClient, path_prefixed_fake_model: FakeModelClient
) -> None:
    path_prefixed_fake_model.script(reply("hi there"))
    r = await path_prefixed_client.post(
        "/ag-ui/run", json=run_body(), headers={"Origin": _PATH_PREFIXED_ORIGIN}
    )
    assert r.status_code == 200, r.text
    frames = sse_frames(r.text)
    assert frames[0]["type"] == "RUN_STARTED"


async def test_message_send_allows_path_prefixed_base_url_origin(
    path_prefixed_client: httpx.AsyncClient, path_prefixed_fake_model: FakeModelClient
) -> None:
    path_prefixed_fake_model.script(reply("done"))
    r = await path_prefixed_client.post(
        "/v1/message:send", json=send_body("hi"), headers={"Origin": _PATH_PREFIXED_ORIGIN}
    )
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# RT-003: a scheme-less/protocol-relative PUBLIC_URL (e.g. a DEV_MODE
# ``//localhost:8080``, which passes ``_is_local`` since ``urlparse`` still
# resolves its hostname even without a scheme) makes ``urlsplit`` yield an
# empty ``scheme`` while ``netloc`` is present. Unconditionally unioning
# f"{scheme}://{netloc}" would then pollute app.state.cors_origins with the
# garbage entry "://localhost:8080" — never a valid RFC-6454 Origin, but
# noise nonetheless. The fix only unions the own-origin entry when BOTH
# components are present.
# ---------------------------------------------------------------------------

_SCHEME_LESS_PUBLIC_URL = "//localhost:8080"


@pytest.fixture
def scheme_less_settings(tmp_path) -> BaseAgentSettings:
    return BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
        PUBLIC_URL=_SCHEME_LESS_PUBLIC_URL,
    )


@pytest.fixture
def scheme_less_app(scheme_less_settings: BaseAgentSettings):
    built = make_agent(scheme_less_settings, model_client=FakeModelClient()).build_app()
    yield built
    built.state.credential_store.close()
    gc.collect()


def test_scheme_less_public_url_contributes_no_garbage_origin(scheme_less_app) -> None:
    origins = scheme_less_app.state.cors_origins
    assert "://localhost:8080" not in origins, (
        f"a scheme-less resolved_base_url ({_SCHEME_LESS_PUBLIC_URL!r}) must not "
        f"union a malformed '://host' entry into cors_origins; got: {origins!r}"
    )
    assert all(o.count("://") == 1 and not o.startswith("://") for o in origins), (
        f"every cors_origins entry must be a well-formed scheme://netloc origin; "
        f"got: {origins!r}"
    )
