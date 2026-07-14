"""RT-001 (SI-2): ``POST /admin/api/tools/{name}/try`` must NOT echo the
rejected input value when a tool's input model raises a validation error.

The prior implementation built the error response from raw Pydantic
``e['msg']`` under a ``# never echo input values`` comment. That comment was
false: ``ValidationError.errors(include_input=False)`` strips only the
``input`` field, NOT ``msg`` — a custom ``@field_validator`` that interpolates
the rejected value (``raise ValueError(f'... {value!r}')``) surfaces that value
in ``msg``, which was reflected verbatim into the admin-console response. A
tool argument may itself be a token/credential, so this is an SI-2 leak. The
fix routes the branch through ``safe_validation_message()`` — the same helper
the MCP sibling surface (routes/mcp.py) uses — which keeps only loc + type.
"""

from __future__ import annotations

import gc

import httpx
import pytest
from pydantic import BaseModel, field_validator

from agent_sdk.agent.registry import ToolSet
from agent_sdk.example.agent import make_agent

_LEAKED_SECRET = "SUPERSECRET_token_abc123"


class _SecretArgs(BaseModel):
    token: str

    @field_validator("token")
    @classmethod
    def _reject(cls, v: str) -> str:
        # A realistic custom validator that interpolates the (secret) value
        # into its error message — Pydantic folds this into e['msg'].
        raise ValueError(f"invalid token {v!r}")


leaky_tools = ToolSet()


@leaky_tools.tool(tier=1)
async def admin_leaky_tool(args: _SecretArgs) -> str:
    """Tier-1 tool whose input model always rejects, leaking the value in msg."""
    return args.token


@pytest.fixture
def leaky_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [leaky_tools]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def leaky_client(leaky_app):
    async with leaky_app.router.lifespan_context(leaky_app):
        _, token = leaky_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=leaky_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            yield c


async def test_try_tool_validation_error_does_not_leak_input(leaky_client) -> None:
    r = await leaky_client.post(
        "/admin/api/tools/admin_leaky_tool/try",
        json={"token": _LEAKED_SECRET},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is False, body
    assert body["error"]["category"] == "validation"
    # The rejected value must appear NOWHERE in the serialized response.
    assert _LEAKED_SECRET not in r.text, "SI-2 leak: rejected input echoed in response"
    # The response must still name the offending field so the error is actionable.
    assert "token" in body["error"]["message"]
