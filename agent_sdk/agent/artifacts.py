"""ArtifactLoader — prompt artifact management for agents.

Scans ``artifacts_dir`` for ``*.md`` files. Each file is a Jinja2 template
with optional YAML frontmatter (name, description — same convention as skills).
Templates are compiled once at init; ``render()`` substitutes variables at call
time via Jinja2 with StrictUndefined so a missing variable raises immediately
rather than silently emitting an empty string.

Variable syntax: ``{{ variable_name }}``

SDK agents call ``render()`` once at startup (startup-time variables only).
Pre-SDK agents with per-request variables call ``render()`` in their loop.
"""

from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, StrictUndefined, Template


_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class ArtifactLoader:
    """Load and render prompt artifacts from a directory of ``.md`` files.

    SDK agents — startup-time:
        Agent(artifacts_dir=Path(__file__).parent / "artifacts", ...)

    Pre-SDK agents — call-time:
        # module level (compiles templates once)
        _artifacts = ArtifactLoader(Path(__file__).parent.parent / "artifacts")
        # per request
        text = _artifacts.render("system", today=today_iso, user_tz="Asia/Singapore")
    """

    def __init__(self, artifacts_dir: Path | None) -> None:
        self._env = Environment(undefined=StrictUndefined, autoescape=False)
        self._templates: dict[str, Template] = {}
        if artifacts_dir is None or not artifacts_dir.is_dir():
            return
        for path in sorted(artifacts_dir.rglob("*.md")):
            name = path.stem
            text = path.read_text(encoding="utf-8")
            m = _FRONTMATTER.match(text)
            if m:
                text = text[m.end():]
            self._templates[name] = self._env.from_string(text.strip())

    def render(self, name: str = "system", **variables: object) -> str:
        """Render the named artifact with *variables*.

        Raises ``KeyError`` if the artifact does not exist.
        Raises ``jinja2.UndefinedError`` if a required template variable is missing.
        """
        try:
            tmpl = self._templates[name]
        except KeyError:
            available = ", ".join(sorted(self._templates)) or "(none)"
            raise KeyError(
                f"artifact {name!r} not found "
                f"(available: {available})"
            ) from None
        return tmpl.render(**variables)

    @property
    def names(self) -> list[str]:
        """Names of all loaded artifacts."""
        return sorted(self._templates)
