"""RT-001: strict outputSchema takes every nullable field out of required
(exclude_none drops the key) and keeps null on required-nullable fields
that a custom serializer may re-emit as null."""

from __future__ import annotations

import jsonschema

from agent_sdk.common.schema import flatten_schema, strip_schema_titles
from agent_sdk.models.content_types import _REGISTRY, TimeSeriesChart, TimeSeriesDataPoint


def _strict(model: type) -> dict:
    return strip_schema_titles(flatten_schema(model.model_json_schema()))


def test_time_series_gap_validates_against_strict_schema() -> None:
    chart = TimeSeriesChart(
        chart_type="line", title="t", data=[TimeSeriesDataPoint(date="2026-01-01", value=None)]
    )
    jsonschema.validate(chart.wire(), _strict(TimeSeriesChart))


def test_input_mode_still_keeps_required() -> None:
    class_schema = {
        "type": "object",
        "properties": {"a": {"anyOf": [{"type": "string"}, {"type": "null"}]}},
        "required": ["a"],
    }
    out = flatten_schema(class_schema, keep_required=True)
    assert out["required"] == ["a"]
    assert out["properties"]["a"] == {"type": "string"}


def test_required_nullable_output_becomes_type_list() -> None:
    schema = {
        "type": "object",
        "properties": {
            "a": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            "b": {"anyOf": [{"type": "number"}, {"type": "null"}], "default": None},
        },
        "required": ["a"],
    }
    out = flatten_schema(schema)
    assert out["properties"]["a"] == {"type": ["number", "null"]}
    assert out["properties"]["b"] == {"type": "number"}
    assert "required" not in out
    jsonschema.validate({}, out)
    jsonschema.validate({"a": None}, out)


def test_every_builtin_content_type_sample_wire_validates() -> None:
    for model in list(_REGISTRY.values()):
        cls = model if isinstance(model, type) else getattr(model, "model", None)
        if cls is None or not hasattr(cls, "model_json_schema"):
            continue
        try:
            inst = cls.model_construct()
            wire = inst.wire()
        except Exception:
            continue
        schema = _strict(cls)
        validator = jsonschema.Draft202012Validator(schema)
        for err in validator.iter_errors(wire):
            if err.validator in ("required", "type") and "null" in str(err.message):
                raise AssertionError(f"{cls.__name__}: {err.message}")


def test_nullable_type_alias_validates_against_strict_schema() -> None:
    from typing import Optional

    from pydantic import BaseModel
    from typing_extensions import TypeAliasType

    MaybeInt = TypeAliasType("MaybeInt", Optional[int])

    class Out(BaseModel):
        b: MaybeInt

    schema = _strict(Out)
    for value in (None, 3):
        dumped = Out(b=value).model_dump(mode="json", exclude_none=True)
        jsonschema.validate(dumped, schema)
