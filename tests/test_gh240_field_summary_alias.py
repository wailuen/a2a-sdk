"""GH-240: the catalog field summary uses the wire name. Ruling:
https://github.com/wailuen/a2a-sdk/issues/240#issuecomment-6379597173"""
from __future__ import annotations

from typing import ClassVar

from pydantic import ConfigDict, Field

from agent_sdk.a2ui.catalog import _field_summary
from agent_sdk.models.content_types import ContentModel


class _Aliased(ContentModel):
    model_config = ConfigDict(populate_by_name=True)
    data_type: ClassVar[str] = "gh240_aliased"
    component: ClassVar[str] = "Gh240Aliased"
    catalog_id: ClassVar[str] = "urn:a2ui-catalog:gh240:v1"
    pb_id: str = Field(serialization_alias="pbId")
    in_name: str = Field(alias="inName")
    plain: int

    def _body_text(self) -> str:
        return ""


def test_field_summary_uses_wire_alias() -> None:
    summary = _field_summary(_Aliased)
    assert "pbId: " in summary
    assert "pb_id" not in summary
    assert "plain: " in summary
    assert "inName: " in summary
    assert "in_name" not in summary
