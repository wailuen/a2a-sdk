"""w011 fixes: GH-23 (structuredContent coercion failure) + GH-24 (safe_get SSRF guard).

GH-23: Tools with emits=SomeModel that return an unconvertible value must return
       isError:True (not a silent success with missing structuredContent).

GH-24: safe_get blocks RFC 1918 / loopback / link-local / reserved addresses;
       passes for valid public hostnames; shared _is_non_public_ip predicate
       powers both safe_get and SourceAdapter._on_request.
"""

from __future__ import annotations

import gc
import ipaddress

import httpx
import pytest
from pydantic import BaseModel

from agent_sdk.agent.registry import ToolDecl, ToolSet
from agent_sdk.common.http import _is_non_public_ip, safe_get
from agent_sdk.example.agent import make_agent
from agent_sdk.models.errors import AgentError, ErrorCategory


# ---------------------------------------------------------------------------
# GH-23 helpers
# ---------------------------------------------------------------------------


class _StrictModel(BaseModel):
    required_field: str  # a plain int dict cannot satisfy this


async def _mcp_init(client):
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
    )
    assert r.status_code == 200
    session = r.headers.get("mcp-session-id")
    headers: dict[str, str] = {"MCP-Protocol-Version": "2025-06-18"}
    if session:
        headers["Mcp-Session-Id"] = session
    return headers


@pytest.fixture
def coercion_fail_app(settings, fake_model):
    """App with a tool that declares emits=_StrictModel but returns an int."""

    class _Empty(BaseModel):
        pass

    extra = ToolSet()

    async def bad_emitter(inp: _Empty):  # no return annotation — bypasses SC-F1
        """Return an int that cannot be coerced to _StrictModel."""
        return 42

    extra.decls.append(
        ToolDecl(
            fn=bad_emitter,
            name="bad_emitter",
            description="Returns an int that cannot coerce to _StrictModel.",
            tier=1,
            emits=_StrictModel,
            sample=None,
            input_model=_Empty,
            adapter_params={},
            title=None,
            annotations=None,
        )
    )

    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [extra]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def coercion_fail_client(coercion_fail_app):
    async with coercion_fail_app.router.lifespan_context(coercion_fail_app):
        _, token = coercion_fail_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=coercion_fail_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            yield c


# ---------------------------------------------------------------------------
# GH-23 tests
# ---------------------------------------------------------------------------


async def test_gh23_coercion_failure_returns_is_error(coercion_fail_client):
    """Tool returning an unconvertible value with emits= MUST return isError:True.

    MCP §4 forbids a successful result (isError:False) with missing structuredContent
    when outputSchema is advertised.  The fix surfaces coercion failure explicitly.
    """
    headers = await _mcp_init(coercion_fail_client)
    r = await coercion_fail_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "bad_emitter", "arguments": {}},
        },
        headers=headers,
    )
    assert r.status_code == 200
    result = r.json()["result"]
    assert result.get("isError") is True, (
        "coercion failure must return isError:True, not a silent success"
    )
    assert "structuredContent" not in result
    assert "coercion failed" in result["content"][0]["text"]


async def test_gh23_valid_dict_still_coerces(settings, fake_model):
    """A coercible dict with emits= still succeeds with structuredContent present."""
    from agent_sdk.agent.registry import ToolDecl, ToolSet

    class _Empty(BaseModel):
        pass

    class _Simple(BaseModel):
        label: str

    extra = ToolSet()

    async def good_emitter(inp: _Empty):
        return {"label": "hello"}

    extra.decls.append(
        ToolDecl(
            fn=good_emitter,
            name="good_emitter",
            description="Returns a dict that coerces to _Simple.",
            tier=1,
            emits=_Simple,
            sample=None,
            input_model=_Empty,
            adapter_params={},
            title=None,
            annotations=None,
        )
    )

    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [extra]
    app = agent.build_app()
    try:
        async with app.router.lifespan_context(app):
            _, token = app.state.auth.api_keys.mint("test-admin", admin=True)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers={"Authorization": f"Bearer {token}"},
            ) as c:
                headers = await _mcp_init(c)
                r = await c.post(
                    "/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": "good_emitter", "arguments": {}},
                    },
                    headers=headers,
                )
            assert r.status_code == 200
            result = r.json()["result"]
            assert result.get("isError") is False
            assert result.get("structuredContent") == {"label": "hello"}
    finally:
        app.state.credential_store.close()
        gc.collect()


# ---------------------------------------------------------------------------
# GH-24 tests — _is_non_public_ip predicate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("addr,expected", [
    ("192.168.1.1", True),       # RFC 1918 private
    ("10.0.0.1", True),          # RFC 1918 private
    ("172.16.0.1", True),        # RFC 1918 private
    ("127.0.0.1", True),         # loopback
    ("::1", True),               # IPv6 loopback
    ("169.254.169.254", True),   # link-local / IMDS
    ("fe80::1", True),           # IPv6 link-local
    ("0.0.0.0", True),           # unspecified
    ("224.0.0.1", True),         # multicast
    ("8.8.8.8", False),          # public
    ("1.1.1.1", False),          # public
    ("2606:4700:4700::1111", False),  # public IPv6
])
def test_gh24_is_non_public_ip(addr, expected):
    ip = ipaddress.ip_address(addr)
    assert _is_non_public_ip(ip) is expected


# ---------------------------------------------------------------------------
# GH-24 tests — safe_get
# ---------------------------------------------------------------------------


def _fake_resolver(ip: str):
    """Return an async callable that always resolves to *ip* — no asyncio patching."""

    async def _resolve(host: str) -> list:
        return [(None, None, None, None, (ip, 0))]

    return _resolve


async def test_gh24_safe_get_blocks_loopback():
    with pytest.raises(AgentError) as exc_info:
        await safe_get("http://localhost/secret", _resolver=_fake_resolver("127.0.0.1"))
    assert exc_info.value.category == ErrorCategory.VALIDATION
    assert "non-public" in str(exc_info.value)


async def test_gh24_safe_get_blocks_imds():
    with pytest.raises(AgentError) as exc_info:
        await safe_get(
            "http://169.254.169.254/latest/meta-data/",
            _resolver=_fake_resolver("169.254.169.254"),
        )
    assert exc_info.value.category == ErrorCategory.VALIDATION


async def test_gh24_safe_get_blocks_rfc1918():
    with pytest.raises(AgentError):
        await safe_get("http://internal.corp/api", _resolver=_fake_resolver("192.168.0.1"))


async def test_gh24_safe_get_passes_public_url():
    """Passes for a public IP; uses httpx.MockTransport — no AsyncClient patching."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    result = await safe_get(
        "https://dns.google/",
        _resolver=_fake_resolver("8.8.8.8"),
        _transport=transport,
    )
    assert result.status_code == 200


async def test_gh24_safe_get_no_follow_redirects():
    """safe_get must not follow redirects (open-redirect SSRF vector).

    Verified by inspecting that the MockTransport receives the request without
    a redirect being followed; ``httpx.MockTransport`` raises
    ``httpx.RemoteProtocolError`` if a response with ``follow_redirects=True``
    would loop — but the simpler check is that safe_get itself passes
    ``follow_redirects=False`` into the AsyncClient constructor.  We confirm
    this by issuing a 301 response and asserting no second request is made.
    """
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            # Return a redirect — safe_get must NOT follow it
            return httpx.Response(301, headers={"location": "https://evil.example.com/"})
        return httpx.Response(200)

    transport = httpx.MockTransport(handler)
    result = await safe_get(
        "https://dns.google/",
        _resolver=_fake_resolver("8.8.8.8"),
        _transport=transport,
    )
    # Only one call — the redirect was not followed
    assert len(calls) == 1
    assert result.status_code == 301
