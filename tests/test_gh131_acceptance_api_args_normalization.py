"""GH-229: acceptance-api.js must normalize string-encoded args like wave-cycle.js (GH-131)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
HARNESS = REPO_ROOT / "harness" / "workflows" / "acceptance-api.js"
TEMPLATE = REPO_ROOT / "template" / ".claude" / "workflows" / "acceptance-api.js"
FILES = [HARNESS, TEMPLATE]
IDS = ["harness", "template"]

GUARD_MARKER = "let normalizedArgs"


def _code_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if not ln.lstrip().startswith("//")]


def _after_guard(text: str) -> str:
    idx = text.index("const missingArgs") if "const missingArgs" in text else 0
    return "\n".join(_code_lines(text[idx:]))


def _guard_block(text: str) -> str:
    start = text.index(GUARD_MARKER)
    end = text.index("const BASE_URL")
    return text[start:end]


@pytest.mark.parametrize("path", FILES, ids=IDS)
def test_guard_present(path: Path) -> None:
    text = path.read_text()
    assert GUARD_MARKER in text
    assert "typeof args === 'string'" in text
    assert "JSON.parse(args)" in text
    assert "normalizedArgs = args || {}" in text
    assert "not valid JSON" in text


@pytest.mark.parametrize("path", FILES, ids=IDS)
def test_no_bare_args_read_after_guard(path: Path) -> None:
    text = path.read_text()
    code = "\n".join(_code_lines(text))
    guard_end = code.index("const BASE_URL")
    tail = code[guard_end:]
    assert not re.search(r"\bargs\b", tail), "bare `args` read after the guard"


@pytest.mark.parametrize("path", FILES, ids=IDS)
def test_fails_fast_on_bad_fields(path: Path) -> None:
    block = _guard_block(path.read_text())
    assert "Array.isArray(normalizedArgs.scenarios)" in block
    assert "badArgs.push('baseUrl')" in block and "badArgs.push('keyFile')" in block
    assert "'scenarios (must be an array)'" in block


@pytest.mark.parametrize("path", FILES, ids=IDS)
def test_error_strings_do_not_echo_values(path: Path) -> None:
    block = _guard_block(path.read_text())
    for m in re.finditer(r"new Error\((.*?)\)\s*\n\s*\}|new Error\((.*?)\n\s*\)", block, re.S):
        body = m.group(1) or m.group(2)
        assert not re.search(r"\b(rawArgs|args|baseUrl|keyFile|BASE_URL|KEY_FILE)\b(?!['\"])", re.sub(r"'[^']*'", "", body)), body
    assert block.count("new Error(") >= 3


def test_template_mirror_identical() -> None:
    assert HARNESS.read_bytes() == TEMPLATE.read_bytes()
