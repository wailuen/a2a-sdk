"""GH-91: _validate_emits async-generator path.

SC-F1 previously rejected any return annotation whose __origin__ was not Union,
which meant async-generator tools annotated with -> AsyncIterator[T] or
-> AsyncGenerator[T, None] raised a spurious ValueError at build_app() time.

Four cases:
  1. async-gen with -> AsyncIterator[EmitsType]    → passes _validate_emits
  2. async-gen with -> AsyncGenerator[EmitsType, None] → passes _validate_emits
  3. async-gen with -> AsyncIterator[WrongType]    → raises ValueError (tool name + mismatch)
  4. async-gen with no return annotation           → passes _validate_emits (existing path)

No unittest.mock / MagicMock / AsyncMock — uses FakeModelClient and the real
build_app() flow.
"""

from __future__ import annotations

import gc
from typing import AsyncGenerator, AsyncIterator

import pytest
from pydantic import BaseModel

from agent_sdk import Agent, BaseAgentSettings
from agent_sdk.agent.registry import ToolSet
from agent_sdk.models.content_types import KpiCard
from agent_sdk.testing import FakeModelClient


# ── shared helper ─────────────────────────────────────────────────────────────


def _agent(tmp_path, toolsets):
    return Agent(
        settings=BaseAgentSettings(DEV_MODE=True, DATA_DIR=str(tmp_path / "data")),
        persona="test agent",
        toolsets=toolsets,
        model_client=FakeModelClient(),
    )


# ── reusable "wrong" model ────────────────────────────────────────────────────


class AnotherModel(BaseModel):
    """Not KpiCard — used for mismatch tests."""
    value: str


# ── test 1: AsyncIterator[EmitsType] passes ───────────────────────────────────


def test_generator_with_correct_asynciterator_annotation_passes(tmp_path):
    """async-gen annotated -> AsyncIterator[KpiCard] with emits=KpiCard must pass."""
    tools = ToolSet()

    @tools.tool(emits=KpiCard)
    async def my_gen() -> AsyncIterator[KpiCard]:
        """Yields a KpiCard."""
        yield KpiCard(title="ok", metrics=[])

    app = _agent(tmp_path, [tools]).build_app()
    app.state.credential_store.close()
    gc.collect()


# ── test 2: AsyncGenerator[EmitsType, None] passes ───────────────────────────


def test_generator_with_asyncgenerator_annotation_passes(tmp_path):
    """async-gen annotated -> AsyncGenerator[KpiCard, None] with emits=KpiCard must pass."""
    tools = ToolSet()

    @tools.tool(emits=KpiCard)
    async def my_gen() -> AsyncGenerator[KpiCard, None]:
        """Yields a KpiCard (two-arg generator form)."""
        yield KpiCard(title="ok", metrics=[])

    app = _agent(tmp_path, [tools]).build_app()
    app.state.credential_store.close()
    gc.collect()


# ── test 3: AsyncIterator[WrongType] raises ValueError ───────────────────────


def test_generator_with_wrong_type_raises(tmp_path):
    """async-gen annotated -> AsyncIterator[AnotherModel] with emits=KpiCard must raise.

    The ValueError message must mention the tool name and the type mismatch.
    """
    tools = ToolSet()

    @tools.tool(emits=KpiCard)
    async def my_gen() -> AsyncIterator[AnotherModel]:  # type: ignore[misc]
        """Wrong yield type — KpiCard is not a subclass of AnotherModel."""
        yield AnotherModel(value="bad")

    with pytest.raises(ValueError) as exc_info:
        _agent(tmp_path, [tools]).build_app()

    msg = str(exc_info.value)
    assert "my_gen" in msg, f"tool name missing from error: {msg!r}"
    # The message must describe the mismatch (yield type and/or emits)
    assert "emits" in msg or "AnotherModel" in msg or "KpiCard" in msg, (
        f"mismatch description missing from error: {msg!r}"
    )


# ── test 4: no return annotation passes (existing unannotated path) ───────────


def test_generator_with_no_annotation_passes(tmp_path):
    """async-gen with no return annotation must still pass _validate_emits."""
    tools = ToolSet()

    @tools.tool(emits=KpiCard)
    async def my_gen():
        """No annotation — always permitted."""
        yield KpiCard(title="ok", metrics=[])

    app = _agent(tmp_path, [tools]).build_app()
    app.state.credential_store.close()
    gc.collect()
