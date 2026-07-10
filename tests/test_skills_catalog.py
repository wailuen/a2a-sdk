"""GH-100: exclude_from_catalog — always-on/guardrail skills inlined via
persona/artifacts_dir, kept out of the advertised skill catalog, still
directly loadable via the load_skill tool.

Covers both layers named in the AC:
  - SkillsRegistry.catalog_text(exclude=...) omits matching entries.
  - Agent(exclude_from_catalog=[...]) validates names at build_app() time
    and keeps excluded names out of the frozen system_prompt, while
    app.state.skills.load(<excluded name>) still succeeds.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_sdk import Agent, BaseAgentSettings
from agent_sdk.agent.skills import SkillsRegistry
from agent_sdk.testing import FakeModelClient

ALPHA_SKILL = """---
name: alpha-skill
description: How to handle alpha requests
---

# Alpha skill

Do alpha things.
"""

GUARDRAIL_SKILL = """---
name: guardrail-skill
description: Always-on safety guardrail
---

# Guardrail skill

Never do the dangerous thing.
"""


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    d = tmp_path / "skills"
    d.mkdir()
    (d / "alpha-skill.md").write_text(ALPHA_SKILL, encoding="utf-8")
    (d / "guardrail-skill.md").write_text(GUARDRAIL_SKILL, encoding="utf-8")
    return d


def _make_agent(settings_tmp_path: Path, skills_dir: Path, **agent_kwargs: Any) -> Agent:
    settings = BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(settings_tmp_path / "data"),
        AGENT_NAME="skills-catalog-test-agent",
    )
    return Agent(
        settings=settings,
        persona="You are a test agent.",
        skills_dir=skills_dir,
        model_client=FakeModelClient(),
        **agent_kwargs,
    )


# ── SkillsRegistry.catalog_text(exclude=...) — unit level ──────────────────


def test_catalog_text_without_exclude_lists_all_skills(skills_dir: Path) -> None:
    registry = SkillsRegistry(skills_dir)
    catalog = registry.catalog_text()
    assert "alpha-skill" in catalog
    assert "guardrail-skill" in catalog


def test_catalog_text_exclude_omits_named_skill(skills_dir: Path) -> None:
    registry = SkillsRegistry(skills_dir)
    catalog = registry.catalog_text(exclude=["guardrail-skill"])
    assert "alpha-skill" in catalog
    assert "guardrail-skill" not in catalog


def test_catalog_text_exclude_all_returns_empty_string(skills_dir: Path) -> None:
    registry = SkillsRegistry(skills_dir)
    catalog = registry.catalog_text(exclude=["alpha-skill", "guardrail-skill"])
    assert catalog == ""


def test_catalog_text_exclude_none_is_equivalent_to_no_exclusions(skills_dir: Path) -> None:
    registry = SkillsRegistry(skills_dir)
    assert registry.catalog_text(exclude=None) == registry.catalog_text()


# ── Agent(exclude_from_catalog=...) — build_app() integration ──────────────


def test_build_app_excludes_named_skill_from_system_prompt(tmp_path: Path, skills_dir: Path) -> None:
    agent = _make_agent(tmp_path, skills_dir, exclude_from_catalog=["guardrail-skill"])
    app = agent.build_app()
    try:
        assert "alpha-skill" in app.state.system_prompt
        assert "guardrail-skill" not in app.state.system_prompt
    finally:
        app.state.credential_store.close()


def test_excluded_skill_still_loadable_via_registry(tmp_path: Path, skills_dir: Path) -> None:
    agent = _make_agent(tmp_path, skills_dir, exclude_from_catalog=["guardrail-skill"])
    app = agent.build_app()
    try:
        body = app.state.skills.load("guardrail-skill")
        assert body is not None
        assert "Never do the dangerous thing" in body
    finally:
        app.state.credential_store.close()


def test_no_exclude_from_catalog_keeps_all_skills_advertised(tmp_path: Path, skills_dir: Path) -> None:
    agent = _make_agent(tmp_path, skills_dir)
    app = agent.build_app()
    try:
        assert "alpha-skill" in app.state.system_prompt
        assert "guardrail-skill" in app.state.system_prompt
    finally:
        app.state.credential_store.close()


def test_exclude_from_catalog_unknown_name_raises_at_build_app(tmp_path: Path, skills_dir: Path) -> None:
    agent = _make_agent(tmp_path, skills_dir, exclude_from_catalog=["does-not-exist"])
    with pytest.raises(ValueError, match="does-not-exist"):
        agent.build_app()


def test_exclude_from_catalog_does_not_raise_in_init(tmp_path: Path, skills_dir: Path) -> None:
    """Validation happens at build_app() (boot), not eagerly in __init__ —
    skills_dir isn't scanned until build_app() constructs SkillsRegistry."""
    agent = _make_agent(tmp_path, skills_dir, exclude_from_catalog=["does-not-exist"])
    assert agent.exclude_from_catalog == ["does-not-exist"]
