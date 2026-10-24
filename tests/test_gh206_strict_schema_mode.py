"""GH-206: AGENT_SDK_MCP_SCHEMA_MODE=strict flattens MCP tools/list schemas.

Ruling: https://github.com/wailuen/a2a-sdk/issues/206#issuecomment-6359827730
"""

from __future__ import annotations

import copy
import gc
import json
from enum import Enum
from typing import Any, ClassVar, Optional

import httpx
import jsonschema
import pytest
from pydantic import BaseModel, ValidationError

from agent_sdk.agent.registry import ToolSet
from agent_sdk.common.schema import flatten_schema, strip_schema_titles
from agent_sdk.config import BaseAgentSettings
from agent_sdk.example.agent import make_agent
from agent_sdk.models.content_types import _REGISTRY, ContentModel, register_content_type

from .test_mcp_conformance_w9 import _mcp_init


class Color(str, Enum):
    RED = "red"
    BLUE = "blue"


class Inner(BaseModel):
    n: int
    note: Optional[str] = None


class Node(BaseModel):
    name: str
    child: Optional["Node"] = None


class Everything(BaseModel):
    opt: Optional[str] = None
    req_nullable: Optional[int]
    color: Color = Color.RED
    maybe_color: Optional[Color] = None
    tags: Optional[list[str]] = None
    inner: Inner
    inners: list[Inner] = []


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _has_null_anyof(schema: Any) -> bool:
    return any(
        isinstance(n.get("anyOf"), list) and {"type": "null"} in n["anyOf"] for n in _walk(schema)
    )


def _has_default_null(schema: Any) -> bool:
    return any("default" in n and n["default"] is None for n in _walk(schema.get("properties", {}).values()))


def test_flatten_everything_has_no_refs_defs_or_null_anyof():
    raw = Everything.model_json_schema()
    assert "$defs" in raw and _has_null_anyof(raw)
    before = copy.deepcopy(raw)
    out = flatten_schema(raw)
    assert raw == before
    text = json.dumps(out)
    assert "$ref" not in text and "$defs" not in out
    assert not _has_null_anyof(out)
    assert not _has_default_null(out)
    jsonschema.Draft202012Validator.check_schema(out)


def test_flatten_optional_fields_become_plain_and_leave_required():
    out = flatten_schema(Everything.model_json_schema())
    props = out["properties"]
    assert props["opt"]["type"] == "string"
    assert props["tags"]["type"] == "array" and props["tags"]["items"] == {"type": "string"}
    assert props["req_nullable"]["type"] == ["integer", "null"]
    assert "req_nullable" not in out["required"]
    assert "opt" not in out.get("required", [])
    assert "inner" in out["required"]


def test_flatten_keeps_enum_description_format():
    class M(BaseModel):
        c: Optional[Color] = None
        when: Optional[str] = Field_(description="the date", fmt="date")

    out = flatten_schema(M.model_json_schema())
    assert out["properties"]["c"]["enum"] == ["red", "blue"]
    assert out["properties"]["when"]["description"] == "the date"
    assert out["properties"]["when"]["format"] == "date"


def Field_(description: str, fmt: str):
    from pydantic import Field

    return Field(default=None, description=description, json_schema_extra={"format": fmt})


def test_flatten_nested_model_inlined():
    out = flatten_schema(Everything.model_json_schema())
    assert out["properties"]["inner"]["properties"]["n"]["type"] == "integer"
    assert out["properties"]["inners"]["items"]["properties"]["note"]["type"] == "string"


def test_flatten_recursive_model_keeps_ref_and_defs():
    out = flatten_schema(Node.model_json_schema())
    assert out["properties"]["child"] == {"$ref": "#/$defs/Node"} or "$ref" in json.dumps(out)
    assert "Node" in out["$defs"]
    assert not _has_null_anyof(out)
    jsonschema.validate({"name": "a", "child": {"name": "b"}}, out)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"name": "a", "child": {"nope": 1}}, out)


def test_flatten_recursive_inside_wrapper_model():
    class Wrap(BaseModel):
        root: Node
        others: list[Node] = []

    out = flatten_schema(Wrap.model_json_schema())
    assert set(out["$defs"]) == {"Node"}
    jsonschema.validate({"root": {"name": "a", "child": {"name": "b"}}, "others": [{"name": "c"}]}, out)


def test_flatten_ref_with_siblings_merges_description():
    schema = {
        "type": "object",
        "properties": {"x": {"$ref": "#/$defs/D", "description": "outer"}},
        "$defs": {"D": {"type": "string", "description": "inner"}},
    }
    out = flatten_schema(schema)
    assert out["properties"]["x"] == {"type": "string", "description": "outer"}


def test_flatten_unknown_ref_left_alone_and_multi_member_anyof_kept():
    schema = {
        "anyOf": [{"$ref": "#/$defs/Missing"}, {"type": "string"}, {"type": "null"}],
    }
    assert flatten_schema(schema) == schema


def test_flatten_property_named_default_or_title_survives():
    class M(BaseModel):
        default: Optional[str] = None
        title: Optional[str] = None

    out = strip_schema_titles(flatten_schema(M.model_json_schema()))
    assert set(out["properties"]) == {"default", "title"}


def test_flatten_then_strip_leaves_no_titles():
    out = strip_schema_titles(flatten_schema(Everything.model_json_schema()))
    stack = [out]
    while stack:
        n = stack.pop()
        if isinstance(n, dict):
            for k, v in n.items():
                if k == "properties":
                    stack.extend(v.values())
                else:
                    assert k != "title"
                    stack.append(v)
        elif isinstance(n, list):
            stack.extend(n)


def test_pydantic_still_accepts_omitted_and_null():
    assert Everything(req_nullable=None, inner=Inner(n=1)).opt is None
    assert Everything(opt=None, req_nullable=3, inner={"n": 1}).opt is None
    with pytest.raises(ValidationError):
        Everything(req_nullable=1)


def test_setting_default_standard_and_rejects_bad_value(tmp_path):
    assert BaseAgentSettings(DEV_MODE=True, DATA_DIR=str(tmp_path)).mcp_schema_mode == "standard"
    assert (
        BaseAgentSettings(DEV_MODE=True, DATA_DIR=str(tmp_path), AGENT_SDK_MCP_SCHEMA_MODE="strict").mcp_schema_mode
        == "strict"
    )
    with pytest.raises(ValidationError):
        BaseAgentSettings(DEV_MODE=True, DATA_DIR=str(tmp_path), AGENT_SDK_MCP_SCHEMA_MODE="loose")


# ── end to end through /mcp ──


class SharedLeaf(BaseModel):
    label: str
    extra: Optional[str] = None


class Gh206A(ContentModel):
    catalog_id: ClassVar[str] = "urn:test-gh206-a:v1"
    data_type: ClassVar[str] = "gh206_a"
    component: ClassVar[str] = "Gh206A"
    leaf: SharedLeaf
    color: Optional[Color] = None
    tags: Optional[list[str]] = None

    def to_plain_text(self) -> str:
        return "a"


class Gh206B(ContentModel):
    catalog_id: ClassVar[str] = "urn:test-gh206-b:v1"
    data_type: ClassVar[str] = "gh206_b"
    component: ClassVar[str] = "Gh206B"
    leaves: list[SharedLeaf]
    count: Optional[int] = None

    def to_plain_text(self) -> str:
        return "b"


class Gh206C(ContentModel):
    """RT-001: required-nullable output fields with no default."""

    catalog_id: ClassVar[str] = "urn:test-gh206-c:v1"
    data_type: ClassVar[str] = "gh206_c"
    component: ClassVar[str] = "Gh206C"
    x: str | None
    c: Optional[Color]
    leaf: Optional[SharedLeaf]

    def to_plain_text(self) -> str:
        return "c"


class ToolIn(BaseModel):
    opt: Optional[str] = None
    node: Optional[Node] = None
    inner: Optional[Inner] = None


def _toolset() -> ToolSet:
    ts = ToolSet()

    @ts.tool(tier=1, emits=Gh206A, sample={"opt": "x"})
    async def gh206_single(inp: ToolIn) -> Gh206A:
        """single"""
        return Gh206A(leaf=SharedLeaf(label="l"))

    @ts.tool(tier=1, emits=(Gh206A, Gh206B), sample={"opt": "x"})
    async def gh206_union(inp: ToolIn) -> Gh206A | Gh206B:
        """union"""
        if inp.opt == "b":
            return Gh206B(leaves=[SharedLeaf(label="l")])
        return Gh206A(leaf=SharedLeaf(label="l", extra="e"), color=Color.BLUE)

    @ts.tool(tier=1, emits=Gh206C, sample={"opt": "x"})
    async def gh206_nullable(inp: ToolIn) -> Gh206C:
        """nullable"""
        if inp.opt == "set":
            return Gh206C(x="v", c=Color.RED, leaf=SharedLeaf(label="l"))
        return Gh206C(x=None, c=None, leaf=None)

    return ts


async def _list_and_call(mode: str, tmp_path, fake_model):
    register_content_type(Gh206A)
    register_content_type(Gh206B)
    register_content_type(Gh206C)
    settings = BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="t",
        AGENT_SDK_MCP_SCHEMA_MODE=mode,
    )
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [_toolset()]
    app = agent.build_app()
    try:
        async with app.router.lifespan_context(app):
            _, token = app.state.auth.api_keys.mint("test-admin", admin=True)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers={"Authorization": f"Bearer {token}"},
            ) as c:
                h = await _mcp_init(c)
                r = await c.post(
                    "/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, headers=h
                )
                tools = {t["name"]: t for t in r.json()["result"]["tools"]}
                calls: dict[str, Any] = {}
                for i, (name, args) in enumerate(
                    [
                        ("gh206_single", {}),
                        ("gh206_union", {"opt": "a"}),
                        ("gh206_union", {"opt": "b"}),
                        ("gh206_nullable", {}),
                        ("gh206_nullable", {"opt": "set"}),
                    ]
                ):
                    resp = await c.post(
                        "/mcp",
                        json={
                            "jsonrpc": "2.0",
                            "id": 10 + i,
                            "method": "tools/call",
                            "params": {"name": name, "arguments": args},
                        },
                        headers=h,
                    )
                    calls[f"{name}:{args.get('opt')}"] = resp.json()["result"]
                return tools, calls
    finally:
        app.state.credential_store.close()
        _REGISTRY.pop("gh206_a", None)
        _REGISTRY.pop("gh206_b", None)
        _REGISTRY.pop("gh206_c", None)
        gc.collect()


async def test_strict_tools_list_input_and_output_schemas(tmp_path, fake_model):
    tools, calls = await _list_and_call("strict", tmp_path, fake_model)
    single = tools["gh206_single"]
    text_in = json.dumps(single["inputSchema"])
    assert "title" not in single["inputSchema"]
    assert not _has_null_anyof(single["inputSchema"]) and not _has_default_null(single["inputSchema"])
    assert "$defs" in single["inputSchema"] and "Node" in single["inputSchema"]["$defs"]
    assert "Inner" not in text_in
    out = single["outputSchema"]
    assert "$ref" not in json.dumps(out) and "$defs" not in out and not _has_null_anyof(out)
    assert "title" not in out
    jsonschema.validate(calls["gh206_single:None"]["structuredContent"], out)

    union = tools["gh206_union"]["outputSchema"]
    assert len(union["anyOf"]) == 2
    assert "$ref" not in json.dumps(union) and "$defs" not in union and not _has_null_anyof(union)
    assert "SharedLeaf" not in json.dumps(union)
    for key in ("gh206_union:a", "gh206_union:b"):
        res = calls[key]
        assert res["isError"] is False
        jsonschema.validate(res["structuredContent"], union)


async def test_strict_required_nullable_output_validates_end_to_end(tmp_path, fake_model):
    """RT-001: the strict outputSchema must not list a required-nullable
    field in required, and must accept an explicit null. Since v0.20.0 the
    MCP route sends such a field as null (_restore_required_nulls)."""
    tools, calls = await _list_and_call("strict", tmp_path, fake_model)
    out = tools["gh206_nullable"]["outputSchema"]
    assert not {"x", "c", "leaf"} & set(out.get("required", []))
    assert out["properties"]["x"]["type"] == ["string", "null"]
    empty = calls["gh206_nullable:None"]
    assert empty["isError"] is False
    assert {k: empty["structuredContent"][k] for k in ("x", "c", "leaf")} == {"x": None, "c": None, "leaf": None}
    jsonschema.validate(empty["structuredContent"], out)
    jsonschema.validate({k: v for k, v in empty["structuredContent"].items() if k not in ("x", "c", "leaf")}, out)
    full = calls["gh206_nullable:set"]
    assert full["isError"] is False
    jsonschema.validate(full["structuredContent"], out)
    jsonschema.validate({**empty["structuredContent"], "x": None, "c": None, "leaf": None}, out)


async def test_standard_tools_list_unchanged(tmp_path, fake_model):
    tools, _ = await _list_and_call("standard", tmp_path, fake_model)
    for name in ("gh206_single", "gh206_union"):
        t = tools[name]
        expected = strip_schema_titles(ToolIn.model_json_schema())
        assert {k: v for k, v in t["inputSchema"].items() if k in expected} == expected
    assert tools["gh206_single"]["outputSchema"] == strip_schema_titles(Gh206A.model_json_schema())
    assert "$defs" in tools["gh206_union"]["outputSchema"]
    assert _has_null_anyof(tools["gh206_single"]["inputSchema"])


# ── RT-001 / RT-002 regressions ──


class ReqNullableIn(BaseModel):
    query: Optional[str]


class NullInContainers(BaseModel):
    items: list[Optional[str]]
    mapping: dict[str, Optional[int]]
    maybe: Optional[str] = None


def test_input_schema_keeps_required_nullable_required():
    raw = ReqNullableIn.model_json_schema()
    out = flatten_schema(raw, keep_required=True)
    assert out["required"] == ["query"] and out["properties"]["query"]["type"] == "string"
    with pytest.raises(ValidationError):
        ReqNullableIn.model_validate({})


def test_nulls_in_list_items_and_dict_values_survive_flatten():
    model = NullInContainers(items=[None, "a"], mapping={"k": None})
    out = flatten_schema(NullInContainers.model_json_schema())
    assert "maybe" not in out.get("required", [])
    assert out["properties"]["maybe"]["type"] == "string"
    jsonschema.validate(model.model_dump(mode="json", exclude_none=True), out)


def test_strict_discriminated_union_leaves_no_dangling_defs_ref():
    """w062 RT-003: inlined union targets must not leave discriminator.mapping
    pointing at removed ``#/$defs`` entries."""
    from typing import Annotated, Literal, Union

    from pydantic import Field

    from agent_sdk.common.schema import flatten_schema

    class _A(BaseModel):
        kind: Literal["a"] = "a"

    class _B(BaseModel):
        kind: Literal["b"] = "b"

    class _U(BaseModel):
        u: Annotated[Union[_A, _B], Field(discriminator="kind")]

    out = flatten_schema(_U.model_json_schema())
    assert "#/$defs/" not in json.dumps(out)
    assert out["properties"]["u"]["discriminator"] == {"propertyName": "kind"}


def test_gh236_top_level_three_member_union_with_null_stays_intact():
    schema = {"anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}]}
    assert flatten_schema(schema) == schema
    assert flatten_schema(schema, keep_required=True) == schema


def test_gh236_list_items_keep_null_in_three_member_union():
    schema = {
        "type": "object",
        "properties": {
            "xs": {"type": "array", "items": {"anyOf": [{"type": "integer"}, {"type": "string"}, {"type": "null"}]}}
        },
    }
    assert flatten_schema(schema) == schema
