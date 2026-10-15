"""GH-176: Basic Catalog primitive names are reserved (case-insensitive)."""
from __future__ import annotations

import pytest

from agent_sdk.models.content_types import (
    _REGISTRY,
    BASIC_CATALOG_COMPONENTS,
    ContentModel,
    register_content_type,
)


def _card(name: object, data_type: str) -> type[ContentModel]:
    class _Card(ContentModel):
        pass

    _Card.data_type = data_type  # type: ignore[misc]
    _Card.component = name  # type: ignore[misc]
    _Card.catalog_id = "urn:test-catalog:v1"  # type: ignore[misc]
    _Card.to_plain_text = lambda self: ""  # type: ignore[method-assign]
    return _Card


def test_basic_catalog_list() -> None:
    assert set(BASIC_CATALOG_COMPONENTS) == {
        "Text", "Card", "Column", "Row", "List", "Tabs", "Button", "Image",
        "Icon", "Video", "AudioPlayer", "Divider", "Modal", "CheckBox",
        "TextField", "DateTimeInput", "ChoicePicker", "Slider",
    }


@pytest.mark.parametrize(
    ("name", "clash"),
    [("Card", "Card"), ("Text", "Text"), ("Textfield", "TextField")],
)
def test_basic_primitive_refused(name: str, clash: str) -> None:
    cls = _card(name, "gh176_bad")
    try:
        with pytest.raises(ValueError, match=clash) as exc:
            register_content_type(cls)
        assert repr(name) in str(exc.value)
    finally:
        _REGISTRY.pop("gh176_bad", None)


def test_non_string_component_gives_documented_error() -> None:
    cls = _card(5, "gh176_int")
    try:
        with pytest.raises(ValueError, match="PascalCase"):
            register_content_type(cls)
    finally:
        _REGISTRY.pop("gh176_int", None)


def test_snake_case_gets_pascalcase_message() -> None:
    cls = _card("my_card", "gh176_snake")
    try:
        with pytest.raises(ValueError, match="PascalCase"):
            register_content_type(cls)
    finally:
        _REGISTRY.pop("gh176_snake", None)


def test_valid_name_registers() -> None:
    cls = _card("Gh176Widget", "gh176_ok")
    try:
        assert register_content_type(cls) is cls
    finally:
        _REGISTRY.pop("gh176_ok", None)


@pytest.mark.parametrize(
    ("name", "clash"),
    [("checkbox", "CheckBox"), ("text", "Text"), ("kpicard", "KpiCard")],
)
def test_lowercase_clash_gets_pascalcase_message_naming_clash(name: str, clash: str) -> None:
    cls = _card(name, "gh176_lower")
    try:
        with pytest.raises(ValueError, match="PascalCase") as exc:
            register_content_type(cls)
        assert clash in str(exc.value)
    finally:
        _REGISTRY.pop("gh176_lower", None)
