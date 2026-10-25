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


def _validation_errors(schema: dict, value: dict) -> list[str]:
    return [e.message for e in jsonschema.Draft202012Validator(schema).iter_errors(value)]


def test_gh236_three_member_union_drops_null_in_property() -> None:
    from typing import Optional, Union

    from pydantic import BaseModel

    class Opt(BaseModel):
        a: Optional[Union[int, str]] = None
        b: Optional[Union[int, str]]

    in_schema = flatten_schema(Opt.model_json_schema(), keep_required=True)
    assert in_schema["properties"]["a"]["anyOf"] == [{"type": "integer"}, {"type": "string"}]
    assert "null" not in str(in_schema["properties"]["b"]["anyOf"])
    assert in_schema["required"] == ["b"]

    out_schema = _strict(Opt)
    assert "null" not in str(out_schema["properties"]["a"])
    assert "required" not in out_schema
    assert {"type": "null"} in out_schema["properties"]["b"]["anyOf"]
    for payload in ({"b": None}, {"b": 3}, {"a": "x", "b": "y"}, {"a": 4, "b": 1}):
        assert _validation_errors(out_schema, payload) == []
    dumped = Opt(a=None, b=None).model_dump(mode="json", exclude_none=True)
    assert _validation_errors(out_schema, dumped) == []


def _sample(node: dict, defs: dict, depth: int = 0, *, fill_optional: bool = False):
    if "$ref" in node:
        return _sample(defs[node["$ref"].rsplit("/", 1)[1]], defs, depth, fill_optional=fill_optional)
    if "const" in node:
        return node["const"]
    if "enum" in node:
        return node["enum"][0]
    if "anyOf" in node or "oneOf" in node:
        options = [o for o in node.get("anyOf", node.get("oneOf")) if o != {"type": "null"}]
        return _sample(options[0], defs, depth, fill_optional=fill_optional)
    kind = node.get("type")
    if kind == "object" or "properties" in node:
        required = node.get("required", [])
        return {
            k: _sample(v, defs, depth + 1, fill_optional=fill_optional)
            for k, v in node.get("properties", {}).items()
            if (fill_optional or k in required) and depth < 6
        }
    if kind == "array":
        count = node.get("minItems", 0)
        count = count or (1 if fill_optional else 0)
        return [_sample(node["items"], defs, depth + 1, fill_optional=fill_optional) for _ in range(count)]
    if kind == "integer":
        return 1
    if kind == "number":
        return 1.5
    if kind == "boolean":
        return True
    if isinstance(node.get("default"), str):
        # GH-258: some string fields accept only their default
        # (TimeSeriesChart x_key/y_key), so a string default is the sample.
        return node["default"]
    return "2026-01-01" if node.get("format") in ("date", "date-time") else "x"


def test_gh236_all_builtin_content_types_have_no_validation_error_and_none_skipped() -> None:
    skipped: list[str] = []
    for cls in list(_REGISTRY.values()):
        raw = cls.model_json_schema()
        try:
            inst = cls.model_validate(_sample(raw, raw.get("$defs", {})))
            wire = inst.model_dump(mode="json", by_alias=True, exclude_none=True)
        except Exception:
            skipped.append(cls.__name__)
            continue
        errors = _validation_errors(_strict(cls), wire)
        assert errors == [], f"{cls.__name__}: {errors}"
    assert skipped == []


def test_all_optional_sample_of_every_builtin_content_type_validates() -> None:
    """Optional fields, including 3+-member nullable unions, are filled too."""
    skipped: list[str] = []
    for cls in list(_REGISTRY.values()):
        raw = cls.model_json_schema()
        try:
            inst = cls.model_validate(_sample(raw, raw.get("$defs", {}), fill_optional=True))
            wire = inst.model_dump(mode="json", by_alias=True, exclude_none=True)
        except Exception:
            skipped.append(cls.__name__)
            continue
        errors = _validation_errors(_strict(cls), wire)
        assert errors == [], f"{cls.__name__}: {errors}"
    assert skipped == []
