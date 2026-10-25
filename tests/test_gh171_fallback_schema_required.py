"""GH-171: fallback field summary derives ``?`` from is_required() only."""
from __future__ import annotations

from agent_sdk.a2ui.catalog import _COMPACT_SCHEMAS, _field_summary
from agent_sdk.models.content_types import ContentModel
from tests._compact_schema import parse_schema, required_paths


def _fields(summary: str) -> dict[str, str]:
    parsed = parse_schema(summary)
    assert isinstance(parsed, dict)
    return parsed


class _Gh171Card(ContentModel):
    data_type = "gh171_card"
    component = "Gh171Card"

    a: str | None
    b: str | None = None
    c: int

    def _body_text(self) -> str:
        return "x"


class _Gh171Many(ContentModel):
    data_type = "gh171_many"
    component = "Gh171Many"

    req_first: str
    opt_01: str | None = None
    opt_02: str | None = None
    opt_03: str | None = None
    opt_04: str | None = None
    opt_05: str | None = None
    opt_06: str | None = None
    opt_07: str | None = None
    opt_08: str | None = None
    opt_09: str | None = None
    opt_10: str | None = None
    opt_11: str | None = None
    opt_12: str | None = None
    req_last_one: int
    req_last_two: bool

    def _body_text(self) -> str:
        return "x"


def test_nullable_without_keep_null_renders_optional():
    # GH-262 supersedes GH-171: wire() drops a None value, so ``a`` is optional.
    f = _fields(_field_summary(_Gh171Card))
    assert f["a?"] == "str|null"
    assert "b?" in f
    assert f["c"] == "int"
    assert required_paths(parse_schema(_field_summary(_Gh171Card))) == {"c"}


def test_many_fields_keep_every_required_field_and_mark_drop():
    summary = _field_summary(_Gh171Many)
    f = _fields(summary)
    for name in ("req_first", "req_last_one", "req_last_two"):
        assert name in f
    assert {"req_first", "req_last_one", "req_last_two"} <= required_paths(parse_schema(summary))
    assert len(f) < 15
    assert "..." in summary


def test_builtin_compact_schemas_unchanged():
    assert _COMPACT_SCHEMAS["KpiCard"] == '{"metrics":[{label,value,unit?,trend?,change_pct?}],"title?":str}'


def test_prompt_section_keeps_every_required_field():
    """The fallback summary reaches the system prompt with every required field."""
    from agent_sdk.a2ui.catalog import get_system_prompt_section
    from agent_sdk.models.content_types import _REGISTRY, register_content_type

    class _Gh171ManyDomain(_Gh171Many):
        catalog_id = "urn:test-catalog:v1"

    register_content_type(_Gh171ManyDomain)
    try:
        section = get_system_prompt_section(allowed_components=["Gh171Many"])
        line = next(
            ln for ln in section.splitlines() if ln.startswith("- Gh171Many")
        )
        schema = line.split(": ", 1)[1]
        assert {"req_first", "req_last_one", "req_last_two"} <= required_paths(
            parse_schema(schema)
        )
        assert "..." in schema
    finally:
        _REGISTRY.pop("gh171_many", None)
