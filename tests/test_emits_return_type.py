"""SC-F1: _validate_emits return-type enforcement at build_app() time.

Seven cases:
  (a) tool annotated -> KpiCard           with emits=KpiCard  → passes build_app()
  (b) tool annotated -> Any               with emits=KpiCard  → passes
  (c) unannotated tool                    with emits=KpiCard  → passes
  (d) tool annotated -> dict              with emits=KpiCard  → raises ValueError at build_app()
  (e) tool annotated -> Optional[KpiCard] with emits=KpiCard  → passes  (RTGA-002)
  (f) tool annotated -> list[KpiCard]     with emits=KpiCard  → raises ValueError (RT-SC-F1-LIST)
  (g) Agent(persona=..., artifacts_dir=...) both supplied     → raises ValueError (RT-AGENT-PERSONA-EXCLUSIVE)
"""

from __future__ import annotations

import gc
from typing import Any, Optional

import pytest

from agent_sdk import Agent, BaseAgentSettings
from agent_sdk.agent.registry import ToolSet
from agent_sdk.models.content_types import KpiCard
from agent_sdk.testing import FakeModelClient


def _agent_dir(tmp_path, toolsets, artifacts_dir=None):
    """Helper that uses artifacts_dir= instead of persona=."""
    return Agent(
        settings=BaseAgentSettings(DEV_MODE=True, DATA_DIR=str(tmp_path / "data")),
        artifacts_dir=str(artifacts_dir or tmp_path / "artifacts"),
        toolsets=toolsets,
        model_client=FakeModelClient(),
    )


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


# ── (e) annotated -> Optional[KpiCard], emits=KpiCard — must pass (RTGA-002) ──

def test_emits_optional_annotation_passes(tmp_path):
    """Optional[T] return annotation where T satisfies emits must be accepted.

    Before the RTGA-002 fix, Optional[KpiCard] caused a false-positive
    ValueError because inspect.isclass(Optional[KpiCard]) is False.
    """
    tools = ToolSet()

    @tools.tool(emits=KpiCard)
    async def my_tool() -> Optional[KpiCard]:
        """Return a KpiCard or None when short-circuiting."""
        return KpiCard(title="test", metrics=[])

    app = _agent(tmp_path, [tools]).build_app()
    app.state.credential_store.close()
    gc.collect()


# ── (f) annotated -> list[KpiCard], emits=KpiCard — must raise ValueError ──────
# RT-SC-F1-LIST: typing.get_args(list[KpiCard]) returns (KpiCard,), which is
# identical to Optional[KpiCard]'s args.  Without an __origin__ guard, the
# Union-unwrap path falsely passes the check.

def test_emits_list_annotation_raises(tmp_path):
    """list[T] return annotation must be rejected at build_app() time.

    Regression guard for RT-SC-F1-LIST: without the __origin__ check,
    get_args(list[KpiCard]) == (KpiCard,) silently passes the Union-unwrap
    path and the tool only fails at runtime.
    """
    tools = ToolSet()

    @tools.tool(emits=KpiCard)
    async def my_tool() -> list[KpiCard]:  # type: ignore[return-value]
        """Returns a list — not permitted for emits=KpiCard."""
        return []

    with pytest.raises(ValueError, match="return annotation"):
        _agent(tmp_path, [tools]).build_app()


# ── (g) Agent(persona=..., artifacts_dir=...) both supplied — must raise ────────

def test_agent_persona_and_artifacts_dir_both_raise(tmp_path):
    """Passing both persona= and artifacts_dir= is mutually exclusive.

    Regression guard for RT-AGENT-PERSONA-EXCLUSIVE: before the fix,
    build_app() silently used artifacts_dir and discarded persona.
    """
    with pytest.raises(ValueError, match="exactly one of persona="):
        Agent(
            settings=BaseAgentSettings(DEV_MODE=True, DATA_DIR=str(tmp_path / "data")),
            persona="my persona",
            artifacts_dir=str(tmp_path / "artifacts"),
            model_client=FakeModelClient(),
        )
