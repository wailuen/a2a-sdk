"""GH-41: lifespan_extras documented as the single scheduling entry point.

ACs verified:
  1. Agent.__init__ docstring documents lifespan_extras with a minimal
     asyncio.create_task example.
  2. DESIGN.md contains a ## Scheduling section (§10.4).
  3. CHANGELOG.md contains a GH-41 entry.
  4. No agent_sdk.scheduler module exists (no silent leakage of a new API surface).
"""
from __future__ import annotations

import inspect
import importlib
import sys
from pathlib import Path

import pytest

import agent_sdk.app as _app_module


# ---------------------------------------------------------------------------
# AC-1: Agent.__init__ docstring
# ---------------------------------------------------------------------------


def test_lifespan_extras_param_exists():
    """lifespan_extras must be a named parameter of Agent.__init__."""
    sig = inspect.signature(_app_module.Agent.__init__)
    assert "lifespan_extras" in sig.parameters, (
        "Agent.__init__ must accept a lifespan_extras= parameter"
    )


def test_lifespan_extras_docstring_present():
    """Agent.__init__ docstring must document the lifespan_extras parameter."""
    doc = _app_module.Agent.__init__.__doc__ or ""
    assert "lifespan_extras" in doc, (
        "Agent.__init__ docstring must describe the lifespan_extras parameter"
    )


def test_lifespan_extras_docstring_asyncio_create_task():
    """Agent.__init__ docstring must include a minimal asyncio.create_task example."""
    doc = _app_module.Agent.__init__.__doc__ or ""
    assert "asyncio.create_task" in doc, (
        "Agent.__init__ docstring must show a minimal asyncio.create_task example"
    )


def test_lifespan_extras_docstring_no_scheduler_import():
    """Docstring must explicitly warn that agent_sdk.scheduler does not exist."""
    doc = _app_module.Agent.__init__.__doc__ or ""
    assert "agent_sdk.scheduler" in doc, (
        "Agent.__init__ docstring should mention agent_sdk.scheduler explicitly "
        "(to warn callers it does not exist)"
    )


def test_lifespan_extras_docstring_asynccontextmanager():
    """Docstring must reference asynccontextmanager — the required decorator."""
    doc = _app_module.Agent.__init__.__doc__ or ""
    assert "asynccontextmanager" in doc, (
        "Agent.__init__ docstring must show @asynccontextmanager as the required pattern"
    )


# ---------------------------------------------------------------------------
# AC-2: DESIGN.md ## Scheduling section
# ---------------------------------------------------------------------------


def _design_md_path() -> Path:
    repo_root = Path(_app_module.__file__).parent.parent
    return repo_root / "DESIGN.md"


def test_design_md_scheduling_section_exists():
    """DESIGN.md must contain a ## Scheduling (or §10.4 Scheduling) section."""
    path = _design_md_path()
    assert path.exists(), f"DESIGN.md not found at {path}"
    content = path.read_text()
    assert "Scheduling" in content, (
        "DESIGN.md must contain a Scheduling section"
    )
    # Must be a top-level section heading (##)
    assert any(
        line.startswith("##") and "Scheduling" in line
        for line in content.splitlines()
    ), "DESIGN.md must have a ## heading that includes 'Scheduling'"


def test_design_md_no_scheduler_module():
    """DESIGN.md must state that agent_sdk.scheduler does not exist."""
    path = _design_md_path()
    content = path.read_text()
    assert "agent_sdk.scheduler" in content, (
        "DESIGN.md scheduling section must mention agent_sdk.scheduler "
        "(to state it does not exist)"
    )
    # The surrounding sentence must be a negative statement
    for line in content.splitlines():
        if "agent_sdk.scheduler" in line:
            assert any(word in line.lower() for word in ("not", "does not", "no such", "never")), (
                f"DESIGN.md line mentioning agent_sdk.scheduler must be a negative "
                f"statement; got: {line!r}"
            )
            break


def test_design_md_lifespan_extras_entry_point():
    """DESIGN.md scheduling section must name lifespan_extras as the entry point."""
    path = _design_md_path()
    content = path.read_text()
    assert "lifespan_extras" in content, (
        "DESIGN.md must name lifespan_extras as the scheduling entry point"
    )


# ---------------------------------------------------------------------------
# AC-3: CHANGELOG entry for GH-41
# ---------------------------------------------------------------------------


def test_changelog_gh41_entry():
    """CHANGELOG.md must contain a GH-41 entry."""
    path = _design_md_path().parent / "CHANGELOG.md"
    assert path.exists(), f"CHANGELOG.md not found at {path}"
    content = path.read_text()
    assert "GH-41" in content, (
        "CHANGELOG.md must have an entry referencing GH-41"
    )


def test_changelog_gh41_lifespan_extras():
    """CHANGELOG.md GH-41 entry must mention lifespan_extras."""
    path = _design_md_path().parent / "CHANGELOG.md"
    content = path.read_text()
    # Find the GH-41 context
    idx = content.find("GH-41")
    assert idx != -1
    surrounding = content[max(0, idx - 200): idx + 400]
    assert "lifespan_extras" in surrounding, (
        "CHANGELOG.md GH-41 entry should mention lifespan_extras"
    )


# ---------------------------------------------------------------------------
# AC-4: No agent_sdk.scheduler module
# ---------------------------------------------------------------------------


def test_no_scheduler_module():
    """agent_sdk.scheduler must not exist — no new public API surface."""
    with pytest.raises((ImportError, ModuleNotFoundError)):
        importlib.import_module("agent_sdk.scheduler")


def test_scheduler_not_in_agent_sdk_namespace():
    """agent_sdk top-level namespace must not expose 'scheduler'."""
    import agent_sdk
    assert not hasattr(agent_sdk, "scheduler"), (
        "agent_sdk.scheduler must not be importable — it would be a new public API surface"
    )
