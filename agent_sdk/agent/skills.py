"""SkillsRegistry — SKILL.md progressive disclosure.

Scans ``skills_dir`` (anchored by the caller, never cwd-relative) for
``**/SKILL.md`` and bare ``*.md``. The catalog (name + description from
frontmatter or first heading) is folded into the system prompt; full bodies
load on demand through the built-in ``load_skill`` tool.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(slots=True)
class Skill:
    name: str
    description: str
    body: str


_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse(path: Path, default_name: str) -> Skill:
    text = path.read_text(encoding="utf-8")
    name, description = default_name, ""
    m = _FRONTMATTER.match(text)
    if m:
        for line in m.group(1).splitlines():
            key, _, value = line.partition(":")
            key, value = key.strip().lower(), value.strip()
            if key == "name" and value:
                name = value
            elif key == "description" and value:
                description = value
        text = text[m.end():]
    if not description:
        for line in text.splitlines():
            stripped = line.strip().lstrip("# ")
            if stripped:
                description = stripped[:200]
                break
    return Skill(name=name, description=description, body=text.strip())


class SkillsRegistry:
    def __init__(self, skills_dir: Path | None) -> None:
        self.skills: dict[str, Skill] = {}
        if skills_dir is None or not skills_dir.is_dir():
            return
        for path in sorted(skills_dir.rglob("*.md")):
            default = (
                path.parent.name if path.name == "SKILL.md" else path.stem
            )
            skill = _parse(path, default)
            self.skills[skill.name] = skill

    def catalog_text(self, exclude: Iterable[str] | None = None) -> str:
        """Render the catalog, omitting any skill whose name is in ``exclude``.

        Excluded skills stay fully loadable via :meth:`load` — exclusion
        only removes them from the advertised catalog text, e.g. an
        always-on/guardrail skill inlined via ``persona``/``artifacts_dir``
        (see ``Agent(exclude_from_catalog=...)``).
        """
        excluded = set(exclude) if exclude else set()
        entries = [s for s in self.skills.values() if s.name not in excluded]
        if not entries:
            return ""
        lines = ["Available skills (use the load_skill tool to read one in full):"]
        lines += [f"- {s.name}: {s.description}" for s in entries]
        return "\n".join(lines)

    def load(self, name: str) -> str | None:
        skill = self.skills.get(name)
        return skill.body if skill else None
