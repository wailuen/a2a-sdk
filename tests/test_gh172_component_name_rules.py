"""GH-172: component names must be PascalCase and unique case-insensitively."""
from __future__ import annotations

from typing import ClassVar

import pytest

from agent_sdk.models.content_types import (
    _REGISTRY,
    ContentModel,
    register_content_type,
)


def _card(name: str, data_type: str) -> type[ContentModel]:
    class _Card(ContentModel):
        pass

    _Card.data_type = data_type  # type: ignore[misc]
    _Card.component = name  # type: ignore[misc]
    _Card.catalog_id = "urn:test-catalog:v1"  # type: ignore[misc]
    _Card.to_plain_text = lambda self: ""  # type: ignore[method-assign]
    return _Card


@pytest.mark.parametrize(
    ("name", "match"),
    [
        ("KPICard", "KpiCard"),
        ("tradeactivity", "PascalCase"),
        ("tradeactivity", "TradeActivity"),
        ("my_card", "my_card"),
        ("kpiCard", "kpiCard"),
    ],
)
def test_bad_component_name_refused(name: str, match: str) -> None:
    cls = _card(name, "gh172_bad")
    try:
        with pytest.raises(ValueError, match=match):
            register_content_type(cls)
    finally:
        _REGISTRY.pop("gh172_bad", None)


def test_valid_pascal_case_registers() -> None:
    cls = _card("TradeFeed", "gh172_ok")
    try:
        assert register_content_type(cls) is cls
        assert register_content_type(cls) is cls
    finally:
        _REGISTRY.pop("gh172_ok", None)
