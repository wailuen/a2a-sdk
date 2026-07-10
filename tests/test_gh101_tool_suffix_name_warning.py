"""GH-101 — ToolSet.tool() logs a WARNING at registration time when the
resolved tool name comes from a function whose ``__name__`` ends in
``_tool`` and no explicit ``name=`` override was supplied.

Without this, a function named e.g. ``get_price_tool`` silently registers a
tool named ``get_price_tool`` (not ``get_price``), and the mismatch only
surfaces later as an "unknown tool" error at call time (loop.py) — well
after a skill/persona was authored against the wrong name.

AC:
(a) tool fn named `foo_tool` with no name= → WARNING fires, message names
    the function, the resolved tool name, and the name= override as the fix.
(b) same fn with explicit name="foo" → no warning.
(c) tool fn named `foo` (no `_tool` suffix) → no warning.
Never raises; never renames.
"""

from __future__ import annotations

import logging

from agent_sdk.agent.registry import ToolSet

REGISTRY_LOGGER = "agent_sdk.agent.registry"


def test_tool_suffix_without_name_override_warns(sdk_caplog):
    tools = ToolSet()

    with sdk_caplog(REGISTRY_LOGGER, logging.WARNING) as records:

        @tools.tool(tier=1)
        async def foo_tool() -> None:
            """A tool whose function name ends in _tool."""

    warnings = [r for r in records if r.levelno == logging.WARNING]
    assert warnings, "expected a WARNING when fn.__name__ ends in '_tool' and name= is omitted"
    msg = warnings[0].getMessage()
    assert "foo_tool" in msg, f"warning must name the function; got: {msg!r}"
    assert "name=" in msg, f"warning must mention the name= override as the fix; got: {msg!r}"

    # Never raises, never renames.
    assert tools.decls[0].name == "foo_tool"


def test_tool_suffix_with_explicit_name_override_no_warning(sdk_caplog):
    tools = ToolSet()

    with sdk_caplog(REGISTRY_LOGGER, logging.WARNING) as records:

        @tools.tool(tier=1, name="foo")
        async def foo_tool() -> None:
            """A tool whose function name ends in _tool but has an override."""

    warnings = [r for r in records if r.levelno == logging.WARNING]
    assert not warnings, f"expected no WARNING when name= is explicitly supplied; got: {[r.getMessage() for r in warnings]}"
    assert tools.decls[0].name == "foo"


def test_tool_suffix_with_empty_string_name_override_warns(sdk_caplog):
    """RT-001: name="" is falsy but not None, and still falls through to
    fn.__name__ via `name or fn.__name__` — the warning must fire for this
    case too, not just the omitted-kwarg (None) case.
    """
    tools = ToolSet()

    with sdk_caplog(REGISTRY_LOGGER, logging.WARNING) as records:

        @tools.tool(tier=1, name="")
        async def foo_tool() -> None:
            """A tool whose function name ends in _tool with an explicit empty override."""

    warnings = [r for r in records if r.levelno == logging.WARNING]
    assert warnings, "expected a WARNING when name='' falls through to fn.__name__ ending in '_tool'"
    msg = warnings[0].getMessage()
    assert "foo_tool" in msg, f"warning must name the function; got: {msg!r}"

    assert tools.decls[0].name == "foo_tool"


def test_tool_named_exactly_underscore_tool_gets_generic_hint(sdk_caplog):
    """RT-002: fn.__name__ == "_tool" strips to "", which would otherwise
    suggest the nonsensical `name=""` override (itself falsy, so it would
    fall through to fn.__name__ again). The warning must fall back to a
    generic hint instead of a degenerate empty-string suggestion.
    """
    tools = ToolSet()

    with sdk_caplog(REGISTRY_LOGGER, logging.WARNING) as records:

        @tools.tool(tier=1)
        async def _tool() -> None:
            """A pathological tool function named exactly '_tool'."""

    warnings = [r for r in records if r.levelno == logging.WARNING]
    assert warnings, "expected a WARNING even for the degenerate '_tool' function name"
    msg = warnings[0].getMessage()
    assert "name=''" not in msg and 'name=""' not in msg, (
        f"warning must not suggest the degenerate empty-string override; got: {msg!r}"
    )

    assert tools.decls[0].name == "_tool"


def test_no_tool_suffix_no_warning(sdk_caplog):
    tools = ToolSet()

    with sdk_caplog(REGISTRY_LOGGER, logging.WARNING) as records:

        @tools.tool(tier=1)
        async def foo() -> None:
            """A tool whose function name does not end in _tool."""

    warnings = [r for r in records if r.levelno == logging.WARNING]
    assert not warnings, f"expected no WARNING for a function name without '_tool' suffix; got: {[r.getMessage() for r in warnings]}"
    assert tools.decls[0].name == "foo"
