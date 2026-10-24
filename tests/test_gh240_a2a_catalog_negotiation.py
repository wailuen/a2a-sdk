"""GH-240: A2A Standard Profile cards are sent only when the client's advertised
catalogs contain CATALOG_ID. Ruling:
https://github.com/wailuen/a2a-sdk/issues/240#issuecomment-6379597173"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from agent_sdk.a2ui.translator import CATALOG_ID, A2uiCapabilities, translate
from typing import ClassVar

from agent_sdk.models.content_types import (
    A2UI_EXTENSION_URI,
    ContentModel,
    KpiCard,
    MetricItem,
    WaterfallChart,
)
from agent_sdk.routes.a2a import _capabilities
from agent_sdk.routes.ag_ui import _RunMapper
from agent_sdk.routes.ag_ui import _capabilities as ag_ui_capabilities
from agent_sdk.agent.events import ArtifactEvent
from agent_sdk.testing import reply, tool_call

from .conftest import wait_for_state

OTHER = "urn:other:catalog:v1"
CARD = KpiCard(metrics=[MetricItem(label="A", value=1)])


def _a2a_caps(raw: object) -> A2uiCapabilities:
    message = SimpleNamespace(metadata={"a2uiClientCapabilities": raw})
    request = SimpleNamespace(headers={"x-a2a-extensions": A2UI_EXTENSION_URI})
    return _capabilities(message, request)  # type: ignore[arg-type]


@pytest.mark.parametrize("raw", [{"tier": "core"}, {}, {"catalogs": "x"}])
def test_no_catalogs_key_keeps_standard_card(raw: dict) -> None:
    assert translate(CARD, capabilities=_a2a_caps(raw)) is not None


@pytest.mark.parametrize(
    "raw",
    [
        {"catalogs": [OTHER]},
        {"catalogs": []},
        {"v0.9": {"supportedCatalogIds": [OTHER]}},
        {"supportedCatalogIds": [OTHER]},
        {"v0.9": {"supportedCatalogIds": []}},
    ],
)
def test_catalogs_without_profile_urn_gate_standard_card_off(raw: dict) -> None:
    assert translate(CARD, capabilities=_a2a_caps(raw)) is None


@pytest.mark.parametrize(
    "raw",
    [
        {"catalogs": [CATALOG_ID]},
        {"v0.9": {"supportedCatalogIds": [OTHER, CATALOG_ID]}},
        {"supportedCatalogIds": [CATALOG_ID]},
    ],
)
def test_urn_via_each_alias_sends_standard_card(raw: dict) -> None:
    assert translate(CARD, capabilities=_a2a_caps(raw)) is not None


def test_first_list_in_order_wins() -> None:
    raw = {"catalogs": [OTHER], "supportedCatalogIds": [CATALOG_ID]}
    assert translate(CARD, capabilities=_a2a_caps(raw)) is None


def test_default_from_metadata_unchanged() -> None:
    assert A2uiCapabilities.from_metadata({"catalogs": []}).catalogs == [CATALOG_ID]
    assert A2uiCapabilities.gated(True, {"catalogs": [OTHER]}).allows(type(CARD)) is True


def test_transport_scoped_kwarg_keeps_present_list() -> None:
    caps = A2uiCapabilities.gated(True, {"catalogs": []}, keep_declared_catalogs=True)
    assert caps.catalogs == []
    caps = A2uiCapabilities.from_metadata({}, keep_declared_catalogs=True)
    assert caps.catalogs == [CATALOG_ID]


def test_ag_ui_custom_unchanged() -> None:
    caps = ag_ui_capabilities(
        {"forwardedProps": {"a2uiClientCapabilities": {"catalogs": [OTHER]}}}
    )
    mapper = _RunMapper(thread_id="t", run_id="r", capabilities=caps)
    event = ArtifactEvent(data_type=CARD.data_type, tool_name="t", model=CARD)
    names = [f["name"] for f in mapper.map(event) if f.get("type") == "CUSTOM"]
    assert names == ["AGENT_ARTIFACT", "A2UI_UPDATE"]


class _Domain(ContentModel):
    data_type: ClassVar[str] = "gh249_domain"
    component: ClassVar[str] = "Gh249Domain"
    catalog_id: ClassVar[str] = OTHER

    def to_plain_text(self) -> str:
        return ""


def test_mixed_domain_only_list_passes_domain_blocks_standard() -> None:
    caps = _a2a_caps({"catalogs": [OTHER]})
    assert caps.allows(_Domain) is True
    assert caps.allows(KpiCard) is False


def test_extended_standard_type_under_negotiation() -> None:
    extended = _a2a_caps({"catalogs": [CATALOG_ID], "tier": "core+extended"})
    core = _a2a_caps({"catalogs": [CATALOG_ID], "tier": "core"})
    other = _a2a_caps({"catalogs": [OTHER], "tier": "core+extended"})
    assert extended.allows(WaterfallChart) is True
    assert core.allows(WaterfallChart) is False
    assert other.allows(WaterfallChart) is False


def test_empty_catalogs_wins_over_v09_list() -> None:
    raw = {"catalogs": [], "v0.9": {"supportedCatalogIds": [CATALOG_ID, OTHER]}}
    caps = _a2a_caps(raw)
    assert caps.catalogs == []
    assert caps.allows(KpiCard) is False
    assert caps.allows(_Domain) is False


def _body() -> dict:
    return {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": "kpis"}],
            "messageId": uuid.uuid4().hex,
            "metadata": {"a2uiClientCapabilities": {"catalogs": [OTHER]}},
        }
    }


async def test_a2a_end_to_end_text_fallback(client, fake_model) -> None:
    fake_model.script(tool_call("demo_kpis", {"title": "Q2"}), reply("done"))
    r = await client.post(
        "/v1/message:send", json=_body(), headers={"X-A2A-Extensions": A2UI_EXTENSION_URI}
    )
    done = await wait_for_state(client, r.json()["id"])
    parts = done["artifacts"][0]["parts"]
    assert parts[0]["kind"] == "text"
    mimes = [p.get("metadata", {}).get("mimeType") for p in parts if p["kind"] == "data"]
    assert "application/a2ui+json" not in mimes
