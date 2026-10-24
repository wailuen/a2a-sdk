"""GH-249 (https://github.com/wailuen/a2a-sdk/issues/249, ruling
https://github.com/wailuen/a2a-sdk/issues/249#issuecomment-6381440938)."""
from __future__ import annotations

from typing import ClassVar

import pytest
from pydantic import BaseModel, ConfigDict

from agent_sdk.a2ui import translator
from agent_sdk.a2ui.catalog import get_system_prompt_section, _field_summary
from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.registry import ToolRegistry
from agent_sdk.config import BaseAgentSettings
from agent_sdk.models.content_types import A2UI_EXTENSION_URI, ContentModel
from agent_sdk.routes.agent_card import build_agent_card


def test_empty_catalog_card_has_no_a2ui_extension() -> None:
    card = build_agent_card(BaseAgentSettings(DEV_MODE=True, AGENT_NAME="t"), ToolRegistry([], {}))
    uris = [e["uri"] for e in card["capabilities"]["extensions"]]
    assert A2UI_EXTENSION_URI not in uris
    assert "https://agent-sdk.dev/extensions/ag-ui-run/v1" in uris


@pytest.mark.parametrize("tier", ["non-extended", "extended", "none", "", "core"])
def test_unknown_tier_is_not_extended(tier: str) -> None:
    assert A2uiCapabilities(tier=tier).extended is False


def test_core_plus_extended_is_extended() -> None:
    assert A2uiCapabilities.from_metadata({"tier": "core+extended"}).extended is True


class _Leaf(BaseModel):
    inner_name: str
    inner_note: str | None = None


class _Nested(ContentModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)
    data_type: ClassVar[str] = "gh249_nested"
    component: ClassVar[str] = "Gh249Nested"

    always: int = 0
    maybe: str | None = None
    leaf: _Leaf
    leaves: list[_Leaf] = []

    def to_plain_text(self) -> str:
        return ""


def test_defaulted_but_always_written_field_is_required() -> None:
    summary = _field_summary(_Nested)
    assert "always: int" in summary
    assert "always?" not in summary


def test_nested_model_expanded_one_level() -> None:
    summary = _field_summary(_Nested)
    assert "inner_name: str" in summary
    assert "inner_note?" in summary
    assert summary.count("inner_name") == 2


def test_header_says_common_optional_fields() -> None:
    text = get_system_prompt_section()
    assert "required fields and common optional fields shown" in text


def test_surface_helpers_marked_internal() -> None:
    assert not hasattr(translator, "__all__") or "SurfaceRegistry" not in translator.__all__
    assert "internal" in (translator.SurfaceRegistry.__doc__ or "").lower()
    assert "internal" in (translator.apply_data_model_update.__doc__ or "").lower()


def test_empty_catalog_card_has_no_a2ui_output_mode() -> None:
    # v0.22.0 release gate: output modes follow the same condition as the extension.
    card = build_agent_card(BaseAgentSettings(DEV_MODE=True, AGENT_NAME="t"), ToolRegistry([], {}))
    assert "application/a2ui+json" not in card["defaultOutputModes"]


def test_emitting_agent_card_keeps_a2ui_output_mode(app) -> None:
    card = app.state.agent_card
    assert A2UI_EXTENSION_URI in [e["uri"] for e in card["capabilities"]["extensions"]]
    assert "application/a2ui+json" in card["defaultOutputModes"]


async def test_no_a2ui_echo_when_card_has_no_extension(tmp_path) -> None:
    import uuid

    import httpx

    from agent_sdk import Agent
    from agent_sdk.testing import FakeModelClient, reply

    model = FakeModelClient().script(reply("ok"))
    app = Agent(
        settings=BaseAgentSettings(DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="t"),
        model_client=model,
        persona="p",
        toolsets=[],
    ).build_app()
    try:
        async with app.router.lifespan_context(app):
            _, token = app.state.auth.api_keys.mint("t", admin=True)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers={"Authorization": f"Bearer {token}", "X-A2A-Extensions": A2UI_EXTENSION_URI},
            ) as c:
                r = await c.post(
                    "/v1/message:send",
                    json={"message": {"role": "user", "parts": [{"kind": "text", "text": "hi"}], "messageId": uuid.uuid4().hex}},
                )
        assert r.status_code == 200
        assert A2UI_EXTENSION_URI not in r.headers.get("x-a2a-extensions", "")
    finally:
        app.state.credential_store.close()
