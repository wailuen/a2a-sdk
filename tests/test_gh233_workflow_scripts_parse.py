"""GH-233: every workflow script must parse, wrapped the way the Workflow runtime loads it."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
WORKFLOW_DIRS = [
    REPO_ROOT / "harness" / "workflows",
    REPO_ROOT / ".claude" / "workflows",
    REPO_ROOT / "template" / ".claude" / "workflows",
]


def _scripts() -> list[Path]:
    found: list[Path] = []
    for d in WORKFLOW_DIRS:
        if d.is_dir():
            found.extend(sorted(d.glob("*.js")))
    return found


SCRIPTS = _scripts()


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
@pytest.mark.parametrize(
    "path", SCRIPTS, ids=[str(p.relative_to(REPO_ROOT)) for p in SCRIPTS]
)
def test_workflow_script_parses(path: Path, tmp_path: Path) -> None:
    src = re.sub(r"^\s*export\s+", "", path.read_text(), count=1)
    wrapped = tmp_path / "wrapped.js"
    wrapped.write_text("(async()=>{\n" + src + "\n})")
    result = subprocess.run(
        ["node", "--check", str(wrapped)], capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, f"{path.name} has a JS syntax error"


def test_scripts_discovered() -> None:
    assert any(p.parent == REPO_ROOT / "harness" / "workflows" for p in SCRIPTS)
