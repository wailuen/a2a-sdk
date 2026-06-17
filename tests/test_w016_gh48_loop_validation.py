"""GH-48: tool ValidationError surfaces field/type/msg without leaking input (SI-2)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, field_validator

from agent_sdk.agent.events import ToolResultEvent
from agent_sdk.agent.loop import run_loop
from agent_sdk.agent.registry import ToolSet, ToolRegistry
from agent_sdk.testing import FakeModelClient, tool_call

tools = ToolSet()


class StrictIn(BaseModel):
    count: int


@tools.tool(tier=1)
async def strict_tool(inp: StrictIn) -> dict[str, Any]:
    """Requires count to be an int."""
    return {"n": inp.count}


class MappingIn(BaseModel):
    """Arbitrary-key dict field — the loc carries the user-supplied KEY, and
    extra='forbid' makes the loc carry an unexpected field NAME (SI-2 loc gap)."""

    model_config = {"extra": "forbid"}
    mapping: dict[str, int]


@tools.tool(tier=1)
async def mapping_tool(inp: MappingIn) -> dict[str, Any]:
    """Accepts a str->int mapping with arbitrary keys."""
    return {"keys": list(inp.mapping)}


class TokenIn(BaseModel):
    """Models the GH-48-recommended custom validator pattern that echoes the
    rejected value into the ValueError message (value_error type)."""

    token: str

    @field_validator("token")
    @classmethod
    def must_be_known(cls, v: str) -> str:
        if v != "expected-token":
            # The documented pattern: raise ValueError(f"... {v!r}")
            raise ValueError(f"unknown token {v!r}")
        return v


@tools.tool(tier=1)
async def token_tool(inp: TokenIn) -> dict[str, Any]:
    """Requires a known token."""
    return {"token": inp.token}


REGISTRY = ToolRegistry([tools], {})


async def collect(model) -> list[Any]:
    events = []
    async for ev in run_loop(
        model=model,
        registry=REGISTRY,
        adapters={},
        system="test",
        messages=[{"role": "user", "content": [{"text": "go"}]}],
    ):
        events.append(ev)
    return events


async def test_validation_error_reports_field_name():
    """Field name appears in the tool-result error string."""
    model = FakeModelClient([tool_call("strict_tool", {"count": "not-an-int"})])
    events = await collect(model)
    tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert tool_results, "expected at least one ToolResultEvent"
    result = tool_results[0]
    assert not result.ok
    assert "count" in result.error, f"field name missing from: {result.error!r}"


async def test_validation_error_omits_raw_input():
    """The raw rejected value must NOT appear in the error string (SI-2)."""
    bad_value = "SENSITIVE-VALUE-NOT-AN-INT"
    model = FakeModelClient([tool_call("strict_tool", {"count": bad_value})])
    events = await collect(model)
    tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert tool_results
    result = tool_results[0]
    assert not result.ok
    assert bad_value not in result.error, f"raw input leaked: {result.error!r}"


async def test_validation_error_explains_failure_category():
    """The error explains WHAT failed (a safe, type-derived phrase) so the model
    can self-correct — without leaking the rejected value. We map Pydantic's
    int_parsing/int_type codes to a fixed human phrase rather than passing the
    raw code through (the raw msg/input can echo the value — SI-2)."""
    model = FakeModelClient([tool_call("strict_tool", {"count": "oops"})])
    events = await collect(model)
    tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert tool_results
    result = tool_results[0]
    assert not result.ok
    assert "integer" in result.error, f"failure category missing from: {result.error!r}"
    assert "oops" not in result.error, f"raw input leaked: {result.error!r}"


async def test_dict_key_in_loc_is_redacted(caplog):
    """SI-2 loc gap: a value error under dict[str, X] puts the user-supplied
    KEY in the error loc (loc=('mapping', 'USER_KEY')). The tool-result error
    must echo the declared field name but NOT the user key."""
    secret_key = "SK-LIVE-SECRET-KEY-NAME"
    model = FakeModelClient([tool_call("mapping_tool", {"mapping": {secret_key: "not-an-int"}})])
    with caplog.at_level("DEBUG"):
        events = await collect(model)
    tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert tool_results
    result = tool_results[0]
    assert not result.ok
    assert "mapping" in result.error, f"declared field missing: {result.error!r}"
    assert secret_key not in result.error, f"user dict key leaked into error: {result.error!r}"
    assert secret_key not in caplog.text, "user dict key leaked into logs"


async def test_extra_forbidden_field_name_is_redacted(caplog):
    """SI-2 loc gap: an extra_forbidden error puts the user-supplied extra
    field NAME in the loc (loc=('USER_FIELD',)). It must not be echoed."""
    secret_field = "SK-LIVE-EXTRA-FIELD-NAME"
    model = FakeModelClient(
        [tool_call("mapping_tool", {"mapping": {"ok": 1}, secret_field: "x"})]
    )
    with caplog.at_level("DEBUG"):
        events = await collect(model)
    tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert tool_results
    result = tool_results[0]
    assert not result.ok
    assert secret_field not in result.error, f"extra field name leaked: {result.error!r}"
    assert secret_field not in caplog.text, "extra field name leaked into logs"


async def test_custom_field_validator_does_not_leak_value(caplog):
    """SI-2: a custom @field_validator that raises ValueError(f'... {v!r}')
    produces a value_error whose Pydantic msg echoes the secret. The
    tool-result error (fed back to the model AND logged) must NOT contain it.

    This is the dangerous path the int_parsing-based test cannot exercise:
    int_parsing's msg happens not to echo the value, value_error always does.
    """
    secret = "SK-LIVE-SECRET-9f3a2b71c0"
    model = FakeModelClient([tool_call("token_tool", {"token": secret})])
    with caplog.at_level("DEBUG"):
        events = await collect(model)
    tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert tool_results
    result = tool_results[0]
    assert not result.ok
    # Field name + type still surface for the model to self-correct.
    assert "token" in result.error, f"field name missing from: {result.error!r}"
    # The secret value must not appear anywhere in the error string …
    assert secret not in result.error, f"raw input leaked into error: {result.error!r}"
    # … nor leak via captured logs.
    assert secret not in caplog.text, "raw input leaked into logs"
