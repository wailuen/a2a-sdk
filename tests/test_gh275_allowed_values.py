"""GH-275: literal_error / enum validation errors name the allowed values (SI-2)."""

from __future__ import annotations

import gc
import logging
from enum import Enum
from typing import Annotated, Any, Literal, Optional

import httpx
import pytest
from pydantic import BaseModel, Field, ValidationError, field_validator
from pydantic_core import PydanticCustomError

from agent_sdk.agent.loop import safe_validation_message
from agent_sdk.agent.registry import ToolSet
from agent_sdk.common.text import cap_whole_entries
from agent_sdk.example.agent import make_agent

MARKER = "MARKER_ceased_desc_q7"
FALLBACK = "value is not one of the allowed choices"


def _msg(model: type[BaseModel], data: dict[str, Any], with_model: bool = True) -> str:
    with pytest.raises(ValidationError) as ei:
        model(**data)
    return safe_validation_message("t", ei.value, model if with_model else None)


class Appt(BaseModel):
    sort: Literal["appointment_date", "-appointment_date"] | None = None


class Color(Enum):
    RED = "red"
    BLUE = "blue"


class EnumIn(BaseModel):
    color: Color


class IntLit(BaseModel):
    n: Literal[1, 2]


class N(BaseModel):
    sort: Literal["a", "b"]


class PipeNested(BaseModel):
    n: N | None = None


class OptNested(BaseModel):
    n: Optional[N] = None


class ListLit(BaseModel):
    xs: list[Literal["x", "y"]]


class ListAnnLit(BaseModel):
    xs: list[Annotated[Literal["x", "y"], Field(description="d")]]


class Big(BaseModel):
    v: Literal[tuple(range(50))]  # type: ignore[valid-type]


LONG = "L" * 400


class Mixed(BaseModel):
    v: Literal[LONG, "s1", "s2"]  # type: ignore[valid-type]


class PlainStr(BaseModel):
    s: str

    @field_validator("s")
    @classmethod
    def _c(cls, v: str) -> str:
        raise PydanticCustomError("literal_error", "nope", {"expected": MARKER})


class EnumStrField(BaseModel):
    s: str

    @field_validator("s")
    @classmethod
    def _c(cls, v: str) -> str:
        raise PydanticCustomError("enum", "nope", {"expected": MARKER})


class DictLit(BaseModel):
    m: dict[str, Literal["a", "b"]]


def test_repro_literal_optional() -> None:
    text = _msg(Appt, {"sort": MARKER})
    assert 'sort — must be one of: "appointment_date", "-appointment_date"' in text
    assert MARKER not in text


def test_enum_values() -> None:
    text = _msg(EnumIn, {"color": MARKER})
    assert 'color — must be one of: "red", "blue"' in text
    assert MARKER not in text


def test_int_literal() -> None:
    assert "n — must be one of: 1, 2" in _msg(IntLit, {"n": 9})


@pytest.mark.parametrize("model", [PipeNested, OptNested])
def test_nested_optional_model(model: type[BaseModel]) -> None:
    text = _msg(model, {"n": {"sort": MARKER}})
    assert 'n.sort — must be one of: "a", "b"' in text
    assert MARKER not in text


@pytest.mark.parametrize("model", [ListLit, ListAnnLit])
def test_list_item(model: type[BaseModel]) -> None:
    text = _msg(model, {"xs": ["x", MARKER]})
    assert 'xs.1 — must be one of: "x", "y"' in text
    assert MARKER not in text


def test_dict_value_keeps_fallback() -> None:
    text = _msg(DictLit, {"m": {MARKER: "zzz"}})
    assert FALLBACK in text
    assert MARKER not in text


def test_fifty_values_capped_at_twenty() -> None:
    text = _msg(Big, {"v": 99})
    expected = (
        "must be one of: " + ", ".join(str(i) for i in range(20)) + ", …and 30 more"
    )
    assert expected in text


def test_over_long_value_skipped_not_cut() -> None:
    text = _msg(Mixed, {"v": "nope"})
    assert 'must be one of: "s1", "s2", …and 1 more' in text
    assert "LLLL" not in text


def test_custom_error_on_plain_str_keeps_fallback_and_no_echo() -> None:
    for model in (PlainStr, EnumStrField):
        text = _msg(model, {"s": "x"})
        assert FALLBACK in text
        assert MARKER not in text


def test_no_input_model_keeps_fallback() -> None:
    text = _msg(Appt, {"sort": MARKER}, with_model=False)
    assert FALLBACK in text
    assert "must be one of" not in text


def test_unserialisable_enum_value_keeps_fallback() -> None:
    class B(Enum):
        A = b"x"

    class M(BaseModel):
        b: B

    assert FALLBACK in _msg(M, {"b": "nope"})


def test_all_values_over_long_keeps_fallback() -> None:
    class M(BaseModel):
        v: Literal[LONG]  # type: ignore[valid-type]

    assert FALLBACK in _msg(M, {"v": "nope"})


# ---- C-075 unit tests ----


def test_cap_skip_misfit_keeps_later_short_entries() -> None:
    text, kept = cap_whole_entries(["aa", "b" * 50, "cc"], 20)
    assert text == "aa; cc; …and 1 more"
    assert kept == 2


def test_cap_max_entries_blocks_shortcut() -> None:
    text, kept = cap_whole_entries(["a", "b", "c"], 300, sep=", ", max_entries=2)
    assert (text, kept) == ("a, b, …and 1 more", 2)


def test_cap_max_entries_not_limiting_uses_shortcut() -> None:
    assert cap_whole_entries(["a", "b"], 300, sep=", ", max_entries=5) == ("a, b", 2)


def test_cap_omitted_forces_tail() -> None:
    assert cap_whole_entries(["a", "b"], 300, sep=", ", omitted=1) == ("a, b, …and 1 more", 2)


def test_cap_omitted_adds_to_left_out() -> None:
    text, kept = cap_whole_entries(["a", "b", "c"], 300, sep=", ", max_entries=1, omitted=2)
    assert (text, kept) == ("a, …and 4 more", 1)


def test_cap_never_exceeds_limit() -> None:
    entries = [f"entry{i}" for i in range(40)]
    for limit in (30, 50, 77, 120):
        text, _ = cap_whole_entries(entries, limit)
        assert len(text) <= limit
        assert text.endswith(" more")


def test_cap_nothing_fits() -> None:
    text, kept = cap_whole_entries(["x" * 100], 20)
    assert (text, kept) == ("…and 1 more", 0)


def _pre_gh275_skill_catalog(skills: list[Any], limit: int) -> str:
    """Frozen copy of the v0.25.0 ``_skill_catalog`` fit loop: an independent
    oracle, so the test fails if the shared helper changes the text."""
    entries = [f"{s.name}: {s.description}" for s in skills]
    full = "; ".join(entries)
    if len(full) <= limit:
        return full
    kept: list[str] = []
    used = 0
    for entry in entries:
        left = len(entries) - len(kept) - 1
        suffix_len = len(f"; …and {left} more")
        added = len(entry) + (2 if kept else 0)
        if used + added + suffix_len > limit:
            continue
        kept.append(entry)
        used += added
    more = f"…and {len(entries) - len(kept)} more"
    return "; ".join([*kept, more])


def test_skill_catalog_unchanged() -> None:
    from types import SimpleNamespace

    from agent_sdk.routes.mcp import _MAX_SKILL_CATALOG_LEN, _skill_catalog

    cases = [
        [SimpleNamespace(name=f"s{i}", description="d" * 300) for i in range(20)],
        [SimpleNamespace(name=f"s{i}", description="d" * (50 + 97 * i % 700)) for i in range(30)],
        [SimpleNamespace(name="big", description="x" * 3000)]
        + [SimpleNamespace(name=f"t{i}", description="short") for i in range(5)],
        [SimpleNamespace(name="a", description="one"), SimpleNamespace(name="b", description="two")],
    ]
    for skills in cases:
        assert _skill_catalog(skills) == _pre_gh275_skill_catalog(skills, _MAX_SKILL_CATALOG_LEN)
    assert _pre_gh275_skill_catalog(cases[0], _MAX_SKILL_CATALOG_LEN).endswith(" more")


class FixedTuple(BaseModel):
    t: tuple[Literal["a", "b"], Literal["c", "d"]]


class VarTuple(BaseModel):
    t: tuple[Literal["a", "b"], ...]


def test_fixed_tuple_uses_annotation_at_index() -> None:
    text = _msg(FixedTuple, {"t": ("a", "zz")})
    assert 't.1 — must be one of: "c", "d"' in text
    assert '"a", "b"' not in text
    text = _msg(FixedTuple, {"t": ("zz", "c")})
    assert 't.0 — must be one of: "a", "b"' in text


def test_variadic_tuple_uses_item_annotation() -> None:
    text = _msg(VarTuple, {"t": ("a", "b", "zz")})
    assert 't.2 — must be one of: "a", "b"' in text


# ---- MCP wire ----

tools = ToolSet()


class SortIn(BaseModel):
    sort: Literal["appointment_date", "-appointment_date"] | None = None


@tools.tool(tier=1)
async def sort_tool(inp: SortIn) -> dict[str, Any]:
    """Takes a sort order."""
    return {}


@pytest.fixture
def lit_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [tools]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def lit_client(lit_app):
    async with lit_app.router.lifespan_context(lit_app):
        _, token = lit_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=lit_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            yield c


async def test_mcp_tools_call_lists_choices(lit_client, sdk_caplog) -> None:
    with sdk_caplog("agent_sdk", logging.DEBUG) as records:
        r = await lit_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
            },
        )
        headers = {"MCP-Protocol-Version": "2025-06-18"}
        if r.headers.get("mcp-session-id"):
            headers["Mcp-Session-Id"] = r.headers["mcp-session-id"]
        r = await lit_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "sort_tool", "arguments": {"sort": "ceased_desc"}},
            },
            headers=headers,
        )
    result = r.json()["result"]
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert 'sort — must be one of: "appointment_date", "-appointment_date"' in text
    assert "ceased_desc" not in text
    logs = "\n".join(r.getMessage() + str(r.args) for r in records)
    assert "ceased_desc" not in logs


class MarkerIn(BaseModel):
    s: str

    @field_validator("s")
    @classmethod
    def _c(cls, v: str) -> str:
        raise PydanticCustomError("literal_error", "nope", {"expected": MARKER})


@tools.tool(tier=1)
async def marker_tool(inp: MarkerIn) -> dict[str, Any]:
    """Takes a string."""
    return {}


async def test_mcp_custom_ctx_expected_never_echoed(lit_client, sdk_caplog) -> None:
    """A custom error's ctx["expected"] is not schema-derived: it must reach
    neither the tool result nor the logs (SI-2)."""
    with sdk_caplog("agent_sdk", logging.DEBUG) as records:
        r = await lit_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
            },
        )
        headers = {"MCP-Protocol-Version": "2025-06-18"}
        if r.headers.get("mcp-session-id"):
            headers["Mcp-Session-Id"] = r.headers["mcp-session-id"]
        r = await lit_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "marker_tool", "arguments": {"s": "x"}},
            },
            headers=headers,
        )
    result = r.json()["result"]
    assert result["isError"] is True
    text = result["content"][0]["text"]
    assert FALLBACK in text
    assert MARKER not in text
    logs = "\n".join(r.getMessage() + str(r.args) for r in records)
    assert MARKER not in logs
