import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _runtime_deps() -> set[str]:
    text = (ROOT / "pyproject.toml").read_text()
    block = text.split("dependencies = [", 1)[1].split("\n]", 1)[0]
    names = re.findall(r'^\s*"([A-Za-z0-9_.-]+)', block, re.M)
    return {n.lower().replace("-", "_") for n in names}


def test_testing_imports_are_runtime_dependencies() -> None:
    deps = _runtime_deps()
    stdlib = set(sys.stdlib_module_names)
    for path in (ROOT / "agent_sdk" / "testing").glob("*.py"):
        for node in ast.parse(path.read_text()).body:
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                mods = [node.module]
            for mod in mods:
                top = mod.split(".")[0]
                if top in stdlib or top == "agent_sdk":
                    continue
                assert top.lower() in deps, f"{path.name} imports {top}, not a runtime dependency"
