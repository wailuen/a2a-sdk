"""RT-009: Reusable / ReuseKind / DeferredResult are tool-author-facing public
API (a tool returns Reusable; an input_model annotates a field with
ReuseKind; a long-running tool returns DeferredResult) and must be reachable
from the top-level `agent_sdk` package and listed in `agent_sdk.__all__`,
matching every other stable-core primitive (DESIGN.md §4.0)."""

from __future__ import annotations

import agent_sdk


def test_reuse_and_deferred_primitives_are_top_level_exports() -> None:
    for name in ("Reusable", "ReuseKind", "DeferredResult"):
        assert name in agent_sdk.__all__, f"{name} missing from agent_sdk.__all__"
        assert hasattr(agent_sdk, name), f"agent_sdk.{name} is not importable"


def test_reuse_and_deferred_primitives_match_source_classes() -> None:
    from agent_sdk.agent.deferred import DeferredResult
    from agent_sdk.agent.reuse import ReuseKind, Reusable

    assert agent_sdk.Reusable is Reusable
    assert agent_sdk.ReuseKind is ReuseKind
    assert agent_sdk.DeferredResult is DeferredResult
