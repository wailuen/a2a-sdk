"""SC-F1: _validate_emits return-type enforcement at build_app() time.

Four cases:
  (a) tool annotated -> KpiCard with emits=KpiCard  → passes build_app()
  (b) tool annotated -> Any   with emits=KpiCard     → passes
  (c) unannotated tool        with emits=KpiCard     → passes
  (d) tool annotated -> dict  with emits=KpiCard     → raises ValueError at build_app()
"""

from __future__ import annotations

import gc
from typing import Any

import pytest

from agent_sdk import Agent, BaseAgentSettings
from agent_sdk.agent.registry import ToolSet
from agent_sdk.models.content_types import KpiCard
from agent_sdk.testing import FakeModelClient


def _agent(tmp_path, toolsets):
    return Agent(
        settings=BaseAgentSettings(DEV_MODE=True, DATA_DIR=str(tmp_path / "data")),
        persona="test agent",
        toolsets=toolsets,
        model_client=FakeModelClient(),
    )


# ── (a) annotated -> KpiCard, emits=KpiCard — must pass ──────────────────────

def test_emits_exact_match_passes(tmp_path):
    """Return annotation matching the emits type exactly is accepted."""
    tools = ToolSet()

    @tools.tool(emits=KpiCard)
    async def my_tool() -> KpiCard:
        """Return a KpiCard."""
        return KpiCard(title="test", metrics=[])

    app = _agent(tmp_path, [tools]).build_app()
    app.state.credential_store.close()
    gc.collect()


# ── (b) annotated -> Any, emits=KpiCard — must pass ──────────────────────────

def test_emits_any_annotation_passes(tmp_path):
    """Return annotation of typing.Any is always accepted."""
    tools = ToolSet()

    @tools.tool(emits=KpiCard)
    async def my_tool() -> Any:
        """Return anything."""
        return KpiCard(title="test", metrics=[])

    app = _agent(tmp_path, [tools]).build_app()
    app.state.credential_store.close()
    gc.collect()


# ── (c) unannotated tool, emits=KpiCard — must pass ──────────────────────────

def test_emits_unannotated_passes(tmp_path):
    """A tool with no return annotation is always accepted."""
    tools = ToolSet()

    @tools.tool(emits=KpiCard)
    async def my_tool():
        """Return a KpiCard without annotation."""
        return KpiCard(title="test", metrics=[])

    app = _agent(tmp_path, [tools]).build_app()
    app.state.credential_store.close()
    gc.collect()


# ── (d) annotated -> dict, emits=KpiCard — must raise ValueError ─────────────

def test_emits_mismatched_annotation_raises(tmp_path):
    """A concrete return annotation that is not emits (or a superclass) must
    raise ValueError at build_app() time — not at runtime."""
    tools = ToolSet()

    @tools.tool(emits=KpiCard)
    async def my_tool() -> dict:  # type: ignore[return-value]
        """Wrong return type."""
        return {}

    with pytest.raises(ValueError, match="return annotation"):
        _agent(tmp_path, [tools]).build_app()
