"""GH-229: acceptance-api.js must normalize string-encoded args like wave-cycle.js (GH-131)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
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
    helpers = code[: code.index("let normalizedArgs")]
    helper_code = re.sub(r"'(?:[^'\\\n]|\\.)*'", "''", helpers)
    assert not re.search(r"(?<![\w.])args\b", helper_code), "bare `args` in helper above the guard"


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
        assert not re.search(r"\be\.message\b|JSON\.stringify\(\s*normalizedArgs", body), body
    assert block.count("new Error(") >= 3


def test_template_mirror_identical() -> None:
    assert HARNESS.read_bytes() == TEMPLATE.read_bytes()


RUN_SEGMENT_END = "log('Running"


def _run_guard(path: Path, args_json: str) -> dict:
    text = path.read_text(encoding="utf-8")
    seg = text[text.index(GUARD_MARKER) : text.index(RUN_SEGMENT_END)]
    prog = (
        "const args = " + args_json + ";\n"
        "try {\n" + seg + "\n"
        "console.log(JSON.stringify({ids: scenarios.map(s => s.id), transports}));\n"
        "} catch (e) { console.log(JSON.stringify({error: e.message})); }\n"
    )
    out = subprocess.run(["node", "-e", prog], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def _args(**extra: object) -> str:
    base = {
        "scenarios": [{"id": "S-1"}, {"id": "S-10"}, {"id": "S-2"}],
        "baseUrl": "http://x",
        "keyFile": "/secret/keyfile-path",
    }
    base.update(extra)
    return json.dumps(base)


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")


@needs_node
@pytest.mark.parametrize("path", FILES, ids=IDS)
@pytest.mark.parametrize("field", ["transports", "onlyIds"])
@pytest.mark.parametrize("bad", ['"a2a"', "5", "{}", "true"])
def test_non_array_rejected_without_echo(path: Path, field: str, bad: str) -> None:
    res = _run_guard(path, _args(**{field: json.loads(bad)}))
    assert field in res["error"]
    assert "/secret/keyfile-path" not in res["error"]
    assert bad.strip('"') not in res["error"].replace(field, "")


@needs_node
@pytest.mark.parametrize("path", FILES, ids=IDS)
def test_only_ids_whole_id_match(path: Path) -> None:
    res = _run_guard(path, _args(onlyIds=["S-1"]))
    assert res["ids"] == ["S-1"]


@needs_node
@pytest.mark.parametrize("path", FILES, ids=IDS)
def test_string_only_ids_does_not_substring_match(path: Path) -> None:
    res = _run_guard(path, _args(onlyIds="S-1"))
    assert "error" in res


@needs_node
@pytest.mark.parametrize("path", FILES, ids=IDS)
def test_valid_arrays_still_work(path: Path) -> None:
    res = _run_guard(path, _args(transports=["a2a"], onlyIds=[]))
    assert res["transports"] == ["a2a"] and len(res["ids"]) == 3
