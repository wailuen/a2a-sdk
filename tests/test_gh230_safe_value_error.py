"""GH-230: SafeValueError hint channel and pydantic type-code allowlist (SI-2)."""

from __future__ import annotations

import gc
import logging
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, ValidationError, field_validator
from pydantic_core import PydanticCustomError

import agent_sdk
from agent_sdk import SafeValueError
from agent_sdk.agent.events import ToolResultEvent
from agent_sdk.agent.loop import run_loop, safe_validation_message
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.common.redact import LINE_TEXT_MAX_LEN
from agent_sdk.example.agent import make_agent
from agent_sdk.testing import FakeModelClient, tool_call

MARKER = "MARKER_secret_zq81"
HINT = "Use a ticker such as AAPL (not a company name)."


class BadTicker(SafeValueError):
    message = HINT


class NoMessage(SafeValueError):
    pass


class EmptyMessage(SafeValueError):
    message = ""


class NonStrMessage(SafeValueError):
    message = 42  # type: ignore[assignment]


class LongHint(SafeValueError):
    message = "x" * 400


class HintIn(BaseModel):
    ticker: str

    @field_validator("ticker")
    @classmethod
    def _check(cls, v: str) -> str:
        raise BadTicker(f"bad {v}")


class PlainIn(BaseModel):
    ticker: str

    @field_validator("ticker")
    @classmethod
    def _check(cls, v: str) -> str:
        raise ValueError(f"bad {v}")


class LeakCodeIn(BaseModel):
    ticker: str

    @field_validator("ticker")
    @classmethod
    def _check(cls, v: str) -> str:
        raise PydanticCustomError(f"leak_{v}", "nope")


tools = ToolSet()


@tools.tool(tier=1)
async def hint_tool(inp: HintIn) -> dict[str, Any]:
    """Always rejects with a SafeValueError."""
    return {}


@tools.tool(tier=1)
async def plain_tool(inp: PlainIn) -> dict[str, Any]:
    """Always rejects with a ValueError."""
    return {}


@tools.tool(tier=1)
async def leakcode_tool(inp: LeakCodeIn) -> dict[str, Any]:
    """Always rejects with a custom error code built from input."""
    return {}


def _errors(model: type[BaseModel], value: str = "v") -> ValidationError:
    with pytest.raises(ValidationError) as ei:
        model(ticker=value)
    return ei.value


def test_exported() -> None:
    assert agent_sdk.SafeValueError is SafeValueError
    assert issubclass(SafeValueError, ValueError)


def test_hint_rendered_not_runtime_arg() -> None:
    text = safe_validation_message("t", _errors(HintIn, MARKER), HintIn)
    assert HINT in text
    assert MARKER not in text


@pytest.mark.parametrize("cls", [NoMessage, EmptyMessage, NonStrMessage])
def test_bad_message_falls_back(cls: type[SafeValueError]) -> None:
    class M(BaseModel):
        ticker: str

        @field_validator("ticker")
        @classmethod
        def _c(cls_, v: str) -> str:
            raise cls(MARKER)

    text = safe_validation_message("t", _errors(M, "x"), M)
    assert "value failed a validation rule" in text
    assert MARKER not in text


def test_hint_capped_at_line_text_max_len() -> None:
    class M(BaseModel):
        ticker: str

        @field_validator("ticker")
        @classmethod
        def _c(cls, v: str) -> str:
            raise LongHint()

    text = safe_validation_message("t", _errors(M), M)
    assert "x" * (LINE_TEXT_MAX_LEN - 1) + "…" in text
    assert "x" * LINE_TEXT_MAX_LEN not in text


def test_plain_value_error_redacted() -> None:
    text = safe_validation_message("t", _errors(PlainIn, MARKER), PlainIn)
    assert "value failed a validation rule" in text
    assert MARKER not in text


def test_assertion_error_redacted() -> None:
    class M(BaseModel):
        ticker: str

        @field_validator("ticker")
        @classmethod
        def _c(cls, v: str) -> str:
            assert False, f"bad {v}"

    text = safe_validation_message("t", _errors(M, MARKER), M)
    assert MARKER not in text
    assert "value failed a validation rule" in text


def test_unknown_type_code_not_echoed() -> None:
    text = safe_validation_message("t", _errors(LeakCodeIn, MARKER), LeakCodeIn)
    assert MARKER not in text
    assert "leak_" not in text


def test_builtin_codes_render_code_not_generic() -> None:
    class L(BaseModel):
        xs: list[int] = []
        n: int = 0

    try:
        L.model_validate({"xs": "x", "n": 1.5})
    except ValidationError as exc:
        text = safe_validation_message("t", exc, L)
    assert "int_from_float" in text
    assert "input failed validation" not in text
    try:
        BaseModel.model_validate  # noqa: B018
        from pydantic import Field

        class C(BaseModel):
            xs: list[int] = Field(max_length=1)

        C.model_validate({"xs": [1, 2]})
    except ValidationError as exc:
        assert "too_long" in safe_validation_message("t", exc, C)


def test_sdk_unknown_argument_code_keeps_its_phrase() -> None:
    from agent_sdk.agent.registry import ToolInputValidationError, ToolEntry  # noqa: F401

    class M(BaseModel):
        model_config = {"extra": "forbid"}
        ticker: str

    from agent_sdk.agent.registry import UNKNOWN_ARGUMENT_ERROR_TYPE
    from agent_sdk.agent.loop import _VALIDATION_TYPE_PHRASES

    assert UNKNOWN_ARGUMENT_ERROR_TYPE in _VALIDATION_TYPE_PHRASES


PROBE = "gh230-log-probe"


def _assert_no_leak(records: list[logging.LogRecord]) -> None:
    assert any(r.getMessage() == PROBE for r in records), "probe record not captured"
    text = "\n".join(r.getMessage() + (r.exc_text or "") + str(r.args) for r in records)
    assert MARKER not in text


async def test_loop_tool_result_hint_and_no_leak(sdk_caplog) -> None:
    registry = ToolRegistry([tools], {})
    results: dict[str, str] = {}
    with sdk_caplog("agent_sdk", logging.DEBUG) as records:
        logging.getLogger("agent_sdk.test").warning(PROBE)
        for name in ("hint_tool", "plain_tool", "leakcode_tool"):
            model = FakeModelClient([tool_call(name, {"ticker": MARKER})])
            async for ev in run_loop(
                model=model,
                registry=registry,
                adapters={},
                system="t",
                messages=[{"role": "user", "content": [{"text": "go"}]}],
            ):
                if isinstance(ev, ToolResultEvent):
                    results[name] = ev.error or ""
                    break
    assert HINT in results["hint_tool"]
    assert "value failed a validation rule" in results["plain_tool"]
    for err in results.values():
        assert MARKER not in err
    _assert_no_leak(records)


@pytest.fixture
def leaky_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [tools]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def leaky_client(leaky_app):
    async with leaky_app.router.lifespan_context(leaky_app):
        _, token = leaky_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=leaky_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            yield c


async def test_admin_try_tool(leaky_client, sdk_caplog) -> None:
    with sdk_caplog("agent_sdk", logging.DEBUG) as records:
        logging.getLogger("agent_sdk.test").warning(PROBE)
        r = await leaky_client.post("/admin/api/tools/hint_tool/try", json={"ticker": MARKER})
        assert r.status_code == 200, r.text
        assert HINT in r.json()["error"]["message"]
        assert MARKER not in r.text
        r2 = await leaky_client.post("/admin/api/tools/leakcode_tool/try", json={"ticker": MARKER})
        assert MARKER not in r2.text
    _assert_no_leak(records)


async def test_mcp_is_error_text(leaky_client, sdk_caplog) -> None:
    with sdk_caplog("agent_sdk", logging.DEBUG) as records:
        logging.getLogger("agent_sdk.test").warning(PROBE)
        r = await leaky_client.post(
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
        for i, name in enumerate(("hint_tool", "leakcode_tool"), start=2):
            r = await leaky_client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": i,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": {"ticker": MARKER}},
                },
                headers=headers,
            )
            result = r.json()["result"]
            assert result["isError"] is True
            assert MARKER not in r.text
            if name == "hint_tool":
                assert HINT in result["content"][0]["text"]
    _assert_no_leak(records)
