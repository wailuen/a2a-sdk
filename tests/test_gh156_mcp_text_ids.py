"""GH-156: MCP tools/call text block carries the ids follow-up tools need."""

from __future__ import annotations

import gc

import httpx
import pytest

from agent_sdk.agent.registry import ToolSet
from agent_sdk.example.agent import make_agent
from agent_sdk.models.content_types import (
    ContentModel,
    DocumentItem,
    DocumentList,
    EntityItem,
    EntityList,
)

from .test_content_types import (
    _collect_id_values,
    _expected_id_text,
    _id_sample_instances,
)

tools = ToolSet()


@tools.tool(tier=1, emits=EntityList)
async def gh156_entities() -> EntityList:
    """Return one entity."""
    return EntityList(entity_type="company", items=[EntityItem(id="59199-40", name="Databricks")])


@tools.tool(tier=1, emits=DocumentList)
async def gh156_docs() -> DocumentList:
    """Return one document."""
    return DocumentList(documents=[DocumentItem(id="doc-77", name="Q4")])


def _sample_tool_name(key: str) -> str:
    return f"gh156_sample_{key.lower()}"


def _register_sample_tool(key: str, sample: ContentModel) -> None:
    async def _fn() -> ContentModel:
        return sample

    _fn.__doc__ = f"Return the GH-156 {key} id sample."
    tools.tool(tier=1, emits=type(sample), name=_sample_tool_name(key))(_fn)


# One MCP tool per id-bearing sample (the same samples the registry-wide
# meta-test in test_content_types.py proves cover every schema id field), so
# every model is checked on BOTH surfaces: to_plain_text() there, and the MCP
# tools/call content[0].text here.
for _key, _sample in _id_sample_instances().items():
    _register_sample_tool(_key, _sample)


@pytest.fixture
def gh156_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [tools]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def gh156_client(gh156_app):
    async with gh156_app.router.lifespan_context(gh156_app):
        _, token = gh156_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gh156_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            yield c


async def _call(client: httpx.AsyncClient, name: str) -> str:
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
    )
    headers = {"MCP-Protocol-Version": "2025-06-18"}
    if r.headers.get("mcp-session-id"):
        headers["Mcp-Session-Id"] = r.headers["mcp-session-id"]
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": {}},
        },
        headers=headers,
    )
    result = r.json()["result"]
    assert result["isError"] is False, result
    return result["content"][0]["text"]


async def test_mcp_text_entity_list_has_id(gh156_client) -> None:
    text = await _call(gh156_client, "gh156_entities")
    assert "- Databricks" in text
    assert "    id: 59199-40" in text


async def test_mcp_text_document_list_has_id(gh156_client) -> None:
    assert "\n    id: doc-77" in await _call(gh156_client, "gh156_docs")


GRAPH_ID = "AAMkAGI2TAAA="
URN_ID = "urn:li:organization:1"


@tools.tool(tier=1, emits=EntityList)
async def gh156_real_ids() -> EntityList:
    """Return one entity with a URN id."""
    return EntityList(entity_type="company", items=[EntityItem(id=URN_ID, name="Acme")])


async def test_mcp_text_preserves_urn_id(gh156_client) -> None:
    assert f"    id: {URN_ID}" in await _call(gh156_client, "gh156_real_ids")


def test_email_list_plain_text_preserves_graph_id() -> None:
    from agent_sdk.models.content_types import EmailList, EmailMessage

    msg = EmailMessage.model_validate(
        {
            "id": GRAPH_ID,
            "conversation_id": "AAQkA=+/x",
            "subject": "Hi",
            "from": {"name": "A", "email": "a@x.com"},
            "received_at": "2026-01-01T00:00:00Z",
            "is_read": True,
            "preview": "p",
            "to_recipients": [],
            "web_link": "https://x",
        }
    )
    text = EmailList(messages=[msg], total_count=1, has_more=False).to_plain_text()
    assert f"id: {GRAPH_ID}" in text
    assert "conversation: AAQkA=+/x" in text


def test_safe_id_text_blocks_forgery_keeps_alphabet() -> None:
    """GH-212 ruling https://github.com/wailuen/a2a-sdk/issues/212#issuecomment-6359828392:
    ``( )`` and single spaces stay verbatim in standalone ids; ``=`` stays
    byte-exact (HUMAN GATE .../issues/212#issuecomment-6366237627). The joined
    variant keeps the GH-156 defence."""
    from agent_sdk.common.redact import safe_id_text, safe_joined_id_text

    assert safe_id_text("a,b=c:d+e/f.g_h-i!j~k@l") == "a,b=c:d+e/f.g_h-i!j~k@l"
    assert safe_id_text("202601026118 (1688214-U)") == "202601026118 (1688214-U)"
    assert safe_id_text("a \t\n  b") == "a b"
    out = safe_id_text("x), conversation: (id: y\n[z]|<>")
    assert "\n" not in out and "|" not in out
    assert "[" not in out and "]" not in out and "<" not in out and ">" not in out
    assert out.startswith("x), conversation: (id: y ")
    joined = safe_joined_id_text("x), conversation: (id: y\n[z]|")
    assert "\n" not in joined and " " not in joined
    assert "(" not in joined and ")" not in joined and "|" not in joined


@pytest.mark.parametrize("key", sorted(_id_sample_instances()))
async def test_mcp_text_carries_every_id_field(gh156_client, key) -> None:
    ids = _collect_id_values(_id_sample_instances()[key], with_kind=True)
    assert ids, f"{key}: sample populates no id fields"
    text = await _call(gh156_client, _sample_tool_name(key))
    for value, kind in ids:
        assert _expected_id_text(value, kind) in text, (
            f"{key}: {kind} id {value!r} missing from MCP content[0].text"
        )
