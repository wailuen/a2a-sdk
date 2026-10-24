from __future__ import annotations

from typing import ClassVar

from pydantic import ConfigDict, Field

from agent_sdk.a2ui.catalog import _field_summary
from agent_sdk.models.content_types import ContentModel


class _Aliased(ContentModel):
    model_config = ConfigDict(populate_by_name=True)
    data_type: ClassVar[str] = "gh240_aliased"
    component: ClassVar[str] = "Gh240Aliased"
    pb_id: str = Field(serialization_alias="pbId")
    plain: int

    def _body_text(self) -> str:
        return ""


def test_field_summary_uses_wire_alias() -> None:
    summary = _field_summary(_Aliased)
    assert "pbId: " in summary
    assert "pb_id" not in summary
    assert "plain: " in summary
