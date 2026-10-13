"""RT-001 (fix round): wave-cycle.js's Parse-phase agent call extracts allCreates/
allModifies by following written prompt instructions, not by invoking Python code — the
extraction runs inside an LLM agent call, not this process. `extract_wave_scope` is a
deterministic reference implementation of the SAME extraction rule the Parse prompt now
describes, mirroring the existing agent_sdk/harness/archive_guard.py pattern (pure,
I/O-free helpers that give the archive gate's own prose instructions a real, testable
spec instead of living only as English text inside a JS template string).

Root cause this guards against: the pre-fix Parse prompt asked for "every 'Creates:'
path listed" / "every 'Modifies:' path listed", but the dominant todo form in this repo
puts every real deliverable inside prose on the Creates: line —
`Creates: (modifies \\`a\\`, \\`b\\`, \\`c\\`); adds \\`d\\`` — with no separate Modifies:
field at all. A literal reading of the old instructions extracts only the FIRST
backticked token (or none), silently dropping every other declared path.

Test-first: this file was written BEFORE harness/wave_scope.py existed (RED), then the
implementation was written to make it GREEN.

RT-009: harness/wave_scope.py lives at repo-level `harness/` (not `agent_sdk/harness/`)
because nothing at runtime imports it — wave-cycle.js's Parse phase runs the extraction
inside an LLM agent call, never importing this module — so it must not ship inside the
`agent_sdk` wheel as unreachable public API. This test file is its only importer.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from harness.wave_scope import (
    _looks_like_path,
    extract_scope_paths,
    extract_wave_scope,
)

FIXTURE = Path(__file__).parent / "fixtures" / "w999-prose-scope.md"


# ---------------------------------------------------------------------------
# extract_scope_paths — classify every backticked token on ONE Creates:/Modifies: line
# ---------------------------------------------------------------------------


def test_bare_creates_line_single_path():
    creates, modifies = extract_scope_paths("Creates: `src/tools/new_tool.py`")
    assert creates == ["src/tools/new_tool.py"]
    assert modifies == []


def test_bare_modifies_line_single_path():
    creates, modifies = extract_scope_paths("Modifies: `src/routes/mcp.py`")
    assert creates == []
    assert modifies == ["src/routes/mcp.py"]


def test_modifies_line_with_trailing_adds_clause_keeps_the_created_path():
    """RT-003: a ``Modifies:`` line can still open a CREATE span with a trailing
    "adds" clause. ``extract_wave_scope`` used to call ``extract_scope_paths`` and
    throw the creates bucket away on this branch (the Creates: branch kept both),
    so a file created by such a todo vanished from allScope entirely — never
    reaching review scope, protocol-surface classification, or the archive gate.
    """
    line = "- Modifies: `a/b.py`; adds `c/d.py`"
    assert extract_scope_paths(line) == (["c/d.py"], ["a/b.py"])
    assert extract_wave_scope(line) == (["c/d.py"], ["a/b.py"])


def test_parenthetical_modifies_with_trailing_adds_clause():
    """The dominant real-world form: every path lives inside prose, not a bare list."""
    line = (
        "Creates: (modifies `agent_sdk/routes/mcp.py`, `agent_sdk/routes/admin.py`, "
        "`agent_sdk/__init__.py`); adds `tests/test_t1.py`"
    )
    creates, modifies = extract_scope_paths(line)
    assert creates == ["tests/test_t1.py"]
    assert modifies == [
        "agent_sdk/routes/mcp.py",
        "agent_sdk/routes/admin.py",
        "agent_sdk/__init__.py",
    ]


def test_parenthetical_modifies_only_no_bare_create():
    line = "Creates: (modifies `agent_sdk/config.py`)"
    creates, modifies = extract_scope_paths(line)
    assert creates == []
    assert modifies == ["agent_sdk/config.py"]


def test_bare_modifies_clause_outside_parenthetical():
    """A "modifies `path`" clause need not sit inside parens to count as a modify."""
    line = (
        "Creates: (modifies `agent_sdk/app.py`); modifies `docs/content-types.md`; "
        "adds `tests/test_t4.py`"
    )
    creates, modifies = extract_scope_paths(line)
    assert creates == ["tests/test_t4.py"]
    assert modifies == ["agent_sdk/app.py", "docs/content-types.md"]


def test_never_stops_at_first_backticked_token():
    """Regression for the exact RT-001 bug: a naive extractor stops at the first token.

    RT-006: path-shaped tokens (not bare single letters) — bare identifiers are
    exactly what RT-006's path-shape filter must reject, so a token list using them
    would pass this test for the wrong reason once that filter exists.

    RT-001 (residual fix): tokens are directory-qualified (`x/a.py`, not bare
    `a.py`) — see test_bare_nested_filenames_without_directory_are_not_scope for
    why a bare, slash-less `.py`/`.js`/`.ts` token no longer counts as a path.
    """
    line = (
        "Creates: (modifies `x/a.py`, `x/b.py`, `x/c.py`, `x/d.py`, `x/e.py`, "
        "`x/f.py`); adds `x/g.py`"
    )
    creates, modifies = extract_scope_paths(line)
    assert len(creates) + len(modifies) == 7


def test_inline_code_snippet_not_mistaken_for_a_path():
    """A backticked function reference or code snippet (parens/quotes/spaces) is not a
    file path — RT-001's fix must not over-harvest non-path prose."""
    line = "Creates: (modifies `agent_sdk/agent/bedrock.py`); adds a regression test covering `_boto_client()`'s bearer-token path"
    creates, modifies = extract_scope_paths(line)
    assert modifies == ["agent_sdk/agent/bedrock.py"]
    assert creates == []


# ---------------------------------------------------------------------------
# RT-006 — path-shape rejection.
#
# _looks_like_path() previously accepted ANY backticked token lacking spaces,
# parens, or quotes — so bare identifiers, dotted attribute chains, and slash
# commands that this repo's real todos routinely wrap in backticks (prose, not
# path declarations) were misclassified as scope. These are the exact tokens
# GH-131/GH-132/GH-133/GH-135's Creates: lines in workspace/todos/active/
# w039-gh-issues.md backtick as prose, verified to falsely land in allScope
# before this fix.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    [
        "_fire",
        "max_retries",
        "timeout",
        "wave.allScope",
        "offendingPaths",
        "peerRepoAnnotations",
        "openai.RateLimitError",
        "openai.AsyncOpenAI.__init__",
        "AGENT_SDK_",
        ".py",
        "/sdk-test",
        "/agent-verify",
        "HARNESS_DIRS",
        "wave",
        "rt:todos",
        "OpenAIModelClient",
    ],
)
def test_bare_identifier_tokens_do_not_look_like_paths(token):
    assert _looks_like_path(token) is False


@pytest.mark.parametrize(
    "token",
    [
        "agent_sdk/agent/bedrock.py",
        # leading segment is dot-prefixed but the FINAL segment is a filename
        ".claude/workflows/wave-cycle.js",
        "docs/content-types.md",
        "tests/fixtures/w999-prose-scope.md",
        # a real repo-root file — bare filenames stay eligible for ROOT-LEVEL
        # extensions only (see test_bare_nested_filenames_without_directory_are_not_scope)
        "pyproject.toml",
    ],
)
def test_real_path_tokens_still_look_like_paths(token):
    assert _looks_like_path(token) is True


# ---------------------------------------------------------------------------
# RT-001 (residual fix) — a bare, slash-less source-file basename is not scope.
#
# `_looks_like_path` accepted ANY slash-less token ending in a known extension,
# including `.py`/`.js`/`.ts`. Real source files in this repo are NEVER bare at
# the repo root (verified: no *.py/*.js/*.ts file lives at repo root) — every
# real deliverable with one of those extensions lives nested under a directory.
# A prose reference to a nested file that drops its directory (`wave-cycle.js`
# instead of `.claude/workflows/wave-cycle.js`; `test_workflow_sync.py` instead
# of `tests/test_workflow_sync.py`) is therefore never a genuine path claim: it
# can never string-match the real dirty path `git status` reports, so accepting
# it either adds noise (when the fully-qualified form is ALSO declared
# elsewhere) or — worse — a silent scope gap (workspace/todos/active/
# w039-gh-issues.md's GH-134 item names `test_mcp_conformance_w9.py` bare, with
# no fully-qualified `tests/test_mcp_conformance_w9.py` anywhere else on the
# wave file, so the real file was never actually declared). Root-level
# config/doc extensions (`.toml`/`.md`/`.json`/`.yaml`/`.yml`) are unaffected —
# `pyproject.toml` genuinely lives at the repo root, so bare tokens with those
# extensions stay eligible.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    ["wave-cycle.js", "test_workflow_sync.py", "test_mcp_conformance_w9.py"],
)
def test_bare_nested_filenames_without_directory_are_not_scope(token):
    assert _looks_like_path(token) is False


def test_gh134_bare_filename_creates_line_declares_no_scope():
    """The real defect this fix closes: workspace/todos/active/w039-gh-issues.md's
    GH-134 item names its real modified test file bare, on a "updates ..."
    clause the keyword regex doesn't even recognise. Before the fix the bare
    token still slipped into allScope as a string that could never match the
    real dirty path `tests/test_mcp_conformance_w9.py`; now it correctly
    declares nothing rather than a misleading non-matching entry."""
    line = (
        "- Creates: (modifies `agent_sdk/agent/registry.py`); updates "
        "`test_mcp_conformance_w9.py`'s openWorldHint assertions; adds a "
        "CHANGELOG entry cross-referencing GH-52/GH-134"
    )
    creates, modifies = extract_scope_paths(line)
    assert "test_mcp_conformance_w9.py" not in creates
    assert "test_mcp_conformance_w9.py" not in modifies


# ---------------------------------------------------------------------------
# RT-001 (round-7 fresh-lens debug) — a scope entry names ONE FILE.
#
# Creates:/Modifies: lines are prose, and prose backticks directories to explain
# things ("(`agent_sdk/` is not a harness dir)") and globs to describe watched
# sets (`agent_sdk/**.py`). Both used to pass the "contains a slash" test, so an
# explanatory aside declared a whole subtree as in-scope — and because the
# archive gate then treated a scope entry as a directory PREFIX of a dirty path,
# the single token `agent_sdk/` marked every dirty file under agent_sdk/ as
# declared and disabled the undeclared-scope gate entirely.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "token",
    [
        "agent_sdk/",
        "docs/",
        ".claude/agents/",
        ".claude/agents/core/",
        ".claude/skills/",
        "harness/agents/",
        "harness/skills/",
    ],
)
def test_directory_tokens_are_not_scope(token):
    assert _looks_like_path(token) is False


@pytest.mark.parametrize(
    "token",
    ["agent_sdk/**.py", "agent_sdk/**/*.py", "src/**.py", "tests/test_*.py", "docs/?.md"],
)
def test_glob_tokens_are_not_scope(token):
    assert _looks_like_path(token) is False


def test_directory_prose_on_real_creates_line_is_excluded_from_scope():
    """The real shape that produced the defect: a Creates: line whose prose
    backticks a directory to make a point about it."""
    line = (
        "- Creates: (modifies `harness/wave_scope.py`) "
        "# note: `agent_sdk/` is not a harness dir, and the gate watches "
        "`agent_sdk/**.py`, not `docs/`"
    )
    creates, modifies = extract_scope_paths(line)
    assert creates == []
    assert modifies == ["harness/wave_scope.py"]


def test_identifier_prose_on_real_creates_line_is_excluded_from_scope():
    """Excerpted verbatim from workspace/todos/active/w039-gh-issues.md's GH-133
    Creates: line (RT-014's inline annotation) — the real prose shape that
    dominates this repo's todos and that the pre-fix filter mis-scoped."""
    line = (
        "Creates: (modifies `agent_sdk/agent/openai_client.py`, `agent_sdk/config.py`, "
        '`agent_sdk/app.py`); adds regression test; modifies `tests/test_gh94_rate_limit_error.py` '
        '(adds `pytest.importorskip("openai")` so the module\'s `import openai` statements '
        "construct real `openai.RateLimitError`/`openai.APIConnectionError` instances instead "
        "of only running when the extra happens to be pre-imported, plus two RT-007 "
        "dependency-floor probes asserting `openai.AsyncOpenAI.__init__`/"
        "`openai.AsyncAzureOpenAI.__init__` still accept `max_retries`/`timeout`)  "
        "# RT-014: landed scope also adds `openai_max_retries`/`openai_timeout` settings "
        "(aliased to `AGENT_SDK_OPENAI_MAX_RETRIES`/`AGENT_SDK_OPENAI_TIMEOUT`, "
        "config.py:71-75 — the `AGENT_SDK_`-prefixed names are deliberate) and rewires "
        "`Agent._build_model_client` (app.py:375-377) to forward them to `OpenAIModelClient` — "
        "both required to make the AC's kwargs reachable via env/settings rather than only "
        "via direct constructor call; previously untracked, so `wave.allScope` missed them."
    )
    creates, modifies = extract_scope_paths(line)
    scope = set(creates) | set(modifies)

    assert scope == {
        "agent_sdk/agent/openai_client.py",
        "agent_sdk/config.py",
        "agent_sdk/app.py",
        "tests/test_gh94_rate_limit_error.py",
    }
    non_paths = {
        "openai.RateLimitError",
        "openai.APIConnectionError",
        "openai.AsyncOpenAI.__init__",
        "openai.AsyncAzureOpenAI.__init__",
        "max_retries",
        "timeout",
        "openai_max_retries",
        "openai_timeout",
        "AGENT_SDK_OPENAI_MAX_RETRIES",
        "AGENT_SDK_OPENAI_TIMEOUT",
        "AGENT_SDK_",
        "Agent._build_model_client",
        "OpenAIModelClient",
        "wave.allScope",
    }
    assert scope.isdisjoint(non_paths)


# ---------------------------------------------------------------------------
# extract_wave_scope — scan a whole wave file fixture end to end
# ---------------------------------------------------------------------------


def test_fixture_wave_file_every_backticked_path_lands_in_creates_or_modifies():
    """RT-001's own regression ask: feed a fixture wave file in the prose form and
    assert every backticked path lands in allCreates ∪ allModifies."""
    text = FIXTURE.read_text()
    creates, modifies = extract_wave_scope(text)
    scope = set(creates) | set(modifies)

    expected = {
        "agent_sdk/routes/mcp.py",
        "agent_sdk/routes/admin.py",
        "agent_sdk/__init__.py",
        "tests/test_t1.py",
        "agent_sdk/config.py",
        "src/tools/new_tool.py",
        "src/routes/mcp.py",
        "agent_sdk/app.py",
        "docs/content-types.md",
        "tests/test_t4.py",
    }
    assert expected <= scope, f"missing from allCreates ∪ allModifies: {expected - scope}"


def test_fixture_wave_file_modify_only_todo_contributes_no_create():
    text = FIXTURE.read_text()
    creates, _modifies = extract_wave_scope(text)
    assert "agent_sdk/config.py" not in creates


def test_fixture_wave_file_creates_and_modifies_are_disjoint_for_same_path():
    text = FIXTURE.read_text()
    creates, modifies = extract_wave_scope(text)
    assert set(creates).isdisjoint(set(modifies))


def test_fixture_t5_identifier_prose_excluded_from_scope():
    """RT-006: T5 interleaves real paths with identifier-in-backticks prose on one
    Creates: line — assert the prose tokens never land in allScope."""
    text = FIXTURE.read_text()
    creates, modifies = extract_wave_scope(text)
    scope = set(creates) | set(modifies)

    assert {
        "agent_sdk/agent/registry.py",
        "agent_sdk/agent/loop.py",
        "agent_sdk/routes/mcp.py",
        "agent_sdk/routes/admin.py",
        "agent_sdk/__init__.py",
        "agent_sdk/contrib/commitments/executor.py",
        "tests/test_contrib_commitments.py",
        "tests/test_rt004_catchall_frame_parity.py",
    } <= scope
    assert scope.isdisjoint({"wave.allScope", "_fire", "offendingUndeclaredScope"})


# ---------------------------------------------------------------------------
# RT-003 (round-5 fresh-lens debug) — PROSE ↔ REFERENCE DRIFT PIN.
#
# This module is a second, independent specification of an algorithm whose
# AUTHORITATIVE copy is English prose inside the Parse-phase prompt of
# .claude/workflows/wave-cycle.js (and its byte-identical harness/ mirror). The
# JS never imports this module — the extraction runs inside an LLM agent call —
# so nothing mechanically ties the two together, and the reference can silently
# stop describing what actually runs (the LRN-065/LRN-131 split-brain class).
#
# These tests fail the build the moment the prompt drops a rule this module
# encodes. They deliberately assert the prompt's RULE TOKENS, not its exact
# wording: rephrasing the prompt is fine, deleting a rule is not.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).parent.parent
_WAVE_CYCLE_COPIES = [
    _REPO_ROOT / ".claude" / "workflows" / "wave-cycle.js",
    _REPO_ROOT / "harness" / "workflows" / "wave-cycle.js",
]
_WAVE_CYCLE_IDS = ["wave-cycle.js(runtime)", "wave-cycle.js(harness)"]


def _parse_prompt(wf_path: Path) -> str:
    """Extract the Parse-phase agent prompt (the `{ schema: WAVE_SCHEMA, ... }`
    call) so a stray mention elsewhere in the file cannot stand in for the real
    instruction text."""
    content = wf_path.read_text(encoding="utf-8")
    match = re.search(
        r"await (?:callAgent|agent)\((.*?)\{\s*schema:\s*WAVE_SCHEMA,",
        content,
        re.DOTALL,
    )
    assert match, f"{wf_path.name}: could not locate the Parse-phase WAVE_SCHEMA agent call"
    return match.group(1)


@pytest.mark.parametrize("wf_path", _WAVE_CYCLE_COPIES, ids=_WAVE_CYCLE_IDS)
def test_parse_prompt_still_describes_the_keywords_this_module_encodes(wf_path: Path) -> None:
    """`_KEYWORD_RE` splits a Creates: line into spans on exactly two keywords —
    "modifies" and "adds". If the prompt stops naming either, this module's
    span-tracking no longer describes the landed rule.
    """
    prompt = _parse_prompt(wf_path)
    for keyword in ("modifies", "adds"):
        assert keyword in prompt, (
            f"{wf_path.name}: the Parse prompt no longer mentions the {keyword!r} "
            "keyword clause that harness/wave_scope.py's _KEYWORD_RE "
            "encodes — the Python reference and the prompt have drifted."
        )


@pytest.mark.parametrize("wf_path", _WAVE_CYCLE_COPIES, ids=_WAVE_CYCLE_IDS)
def test_parse_prompt_still_forbids_stopping_at_the_first_token(wf_path: Path) -> None:
    """The whole point of scanning EVERY backticked token (rather than the first)
    is pinned by test_never_stops_at_first_backticked_token above. The prompt must
    carry the same instruction, or the agent and the reference disagree on the
    dominant todo form in this repo.
    """
    prompt = _parse_prompt(wf_path)
    assert "NEVER stop at the first backticked" in prompt, (
        f"{wf_path.name}: the Parse prompt's 'NEVER stop at the first backticked "
        "token' clause is gone — harness/wave_scope.py still implements "
        "it, so the reference no longer describes what runs."
    )


@pytest.mark.parametrize("wf_path", _WAVE_CYCLE_COPIES, ids=_WAVE_CYCLE_IDS)
def test_parse_prompt_still_routes_parenthetical_modifies_to_all_modifies(wf_path: Path) -> None:
    """`extract_scope_paths` puts a token inside a "(modifies ...)" clause into
    the MODIFIES bucket even on a Creates: line. The prompt must say the same.
    """
    prompt = _parse_prompt(wf_path)
    assert "parenthetical" in prompt and "allModifies" in prompt, (
        f"{wf_path.name}: the Parse prompt no longer routes parenthetical "
        "'(modifies ...)' tokens on a Creates: line into allModifies — "
        "harness/wave_scope.py still does."
    )


# ---------------------------------------------------------------------------
# GH-164: lockfiles and known dotfiles are real deliverables; and Parse must
# deterministically scan Creates:/Modifies: lines instead of trusting the AI alone.
# ---------------------------------------------------------------------------

_GH164_LINE = "Creates: (modifies `uv.lock`, `.env.example`, `src/config.py`)"


def test_gh164_lockfile_dotfile_and_config_all_extracted():
    creates, modifies = extract_scope_paths(_GH164_LINE)
    assert creates == []
    assert modifies == ["uv.lock", ".env.example", "src/config.py"]


@pytest.mark.parametrize(
    "token",
    [
        "uv.lock",
        "package-lock.json",
        "poetry.lock",
        "pnpm-lock.yaml",
        "yarn.lock",
        ".env.example",
        ".gitignore",
        ".gitattributes",
        ".dockerignore",
        ".python-version",
        "template/.gitignore",
        "template/uv.lock",
    ],
)
def test_gh164_known_lockfiles_and_dotfiles_are_scope(token):
    assert _looks_like_path(token)


@pytest.mark.parametrize(
    "token",
    [
        ".py",
        ".lock",
        ".env",
        ".secret",
        "src/.py",
        "agent_sdk/",
        ".claude/",
        "tests/*.lock",
        "*.lock",
        "/uv.lock",
        "/sdk-test",
        "wave.allScope",
        "my.lock.file",
        "src/.hidden",
    ],
)
def test_gh164_still_rejected(token):
    assert not _looks_like_path(token)


@pytest.mark.parametrize(
    "wf_path",
    _WAVE_CYCLE_COPIES + [_REPO_ROOT / ".claude" / "workflows" / "sdk-wave.js"],
    ids=_WAVE_CYCLE_IDS + ["sdk-wave.js"],
)
def test_gh164_parse_has_deterministic_scan_and_widened_rule(wf_path: Path) -> None:
    content = wf_path.read_text(encoding="utf-8")
    assert "SCOPE_SCAN_SCHEMA" in content
    assert "scope-scan-mismatch" in content
    assert "allScope (final" in content
    prompt = _parse_prompt(wf_path)
    assert "uv.lock" in prompt and ".env.example" in prompt
    assert content.find("label: 'parse:scope-scan'") != -1
    assert content.find("scope-scan-mismatch") < content.find("empty-scope")


def test_gh164_workflow_copies_are_byte_identical():
    a = (_REPO_ROOT / "harness" / "workflows" / "wave-cycle.js").read_bytes()
    assert a == (_REPO_ROOT / ".claude" / "workflows" / "wave-cycle.js").read_bytes()
    tpl = _REPO_ROOT / "template" / ".claude" / "workflows" / "wave-cycle.js"
    if tpl.exists():
        assert a == tpl.read_bytes()


def _template_git(*args: str) -> "subprocess.CompletedProcess[bytes]":
    import subprocess

    return subprocess.run(
        ["git", "-C", str(_REPO_ROOT / "template"), *args], capture_output=True, check=False
    )


@pytest.mark.skipif(
    not (_REPO_ROOT / "template" / ".git").exists(), reason="template/ peer repo not checked out"
)
def test_gh164_template_mirror_is_committed_and_pushed():
    """RT-001 (w047 round-5 fresh-lens debug): the template copy is only 'synced' once it is
    PUBLISHED. Comparing the local working tree let an uncommitted, unpushed edit pass as
    synced while agent repos still pulled the old backtick-only scan from origin/main. This
    compares the harness copy against the template's upstream-tracking commit, and fails on a
    dirty mirror or unpushed local commits. Uses the last-fetched tracking ref (no network)."""
    rel = ".claude/workflows/wave-cycle.js"
    harness_copy = (_REPO_ROOT / "harness" / "workflows" / "wave-cycle.js").read_bytes()
    dirty = _template_git("status", "--porcelain", "--", ".claude/workflows/")
    assert dirty.returncode == 0, dirty.stderr
    assert dirty.stdout.strip() == b"", (
        "template/ has uncommitted workflow mirror changes; commit and push them:\n"
        + dirty.stdout.decode()
    )
    ahead = _template_git("rev-list", "--count", "@{upstream}..HEAD")
    assert ahead.returncode == 0, ahead.stderr  # no upstream = cannot prove it is pushed
    assert ahead.stdout.strip() == b"0", "template/ has unpushed commits; run git -C template push"
    published = _template_git("show", f"@{{upstream}}:{rel}")
    assert published.returncode == 0, published.stderr
    assert published.stdout == harness_copy, (
        "template's pushed wave-cycle.js differs from harness/workflows/wave-cycle.js"
    )


def test_gh164_inline_scan_excludes_template_mirror_paths(tmp_path):
    import json
    import subprocess
    import sys

    js = (_REPO_ROOT / "harness" / "workflows" / "wave-cycle.js").read_text(encoding="utf-8")
    start = js.index("'python3 - ' + WAVE_FILE")
    block = js[start : js.index("'PY',", start)]
    lines = re.findall(r"^\s*'(.*)\\n' \+$", block, re.M)
    body = [ln for ln in lines if not ln.startswith("python3 -") and not ln.startswith("python3 ")]
    script = "\n".join(body).replace("\\\\", "\\").replace("\\'", "'")
    wave = tmp_path / "w.md"
    wave.write_text(
        "Modifies: `harness/workflows/wave-cycle.js`, "
        "`template/.claude/workflows/wave-cycle.js`, `tests/test_x.py`\n",
        encoding="utf-8",
    )
    out = subprocess.run(
        [sys.executable, "-", str(wave)], input=script, capture_output=True, text=True, check=True
    ).stdout
    assert json.loads(out) == ["harness/workflows/wave-cycle.js", "tests/test_x.py"]


# ---------------------------------------------------------------------------
# RT-001 (w047 fresh-lens debug): the GH-164 deterministic scan must accept every todo
# format the harness itself writes. The planner agent (harness/agents/core/planner.md)
# writes BARE comma-separated paths, and GH-164's own repro uses a bare
# "(modifies a, b)" clause. The pre-fix scan only read backticked tokens, so on a
# planner-format wave it printed [] and the mismatch gate could never fire — exactly the
# pitchbook w009 case (src/config.py dropped). These tests run the scan script extracted
# verbatim from EVERY workflow copy, so a copy that drifts back to backtick-only fails.
# ---------------------------------------------------------------------------

_SCAN_COPIES = [
    _REPO_ROOT / "harness" / "workflows" / "wave-cycle.js",
    _REPO_ROOT / ".claude" / "workflows" / "wave-cycle.js",
    _REPO_ROOT / ".claude" / "workflows" / "sdk-wave.js",
]
_TEMPLATE_COPY = _REPO_ROOT / "template" / ".claude" / "workflows" / "wave-cycle.js"
if _TEMPLATE_COPY.exists():
    _SCAN_COPIES.append(_TEMPLATE_COPY)

_PLANNER_WAVE = """# Wave w009 — Core data fetch
**Depends:** (none)
**Creates:** src/tools/fetch_data.py, tests/test_fetch_data.py

## Todos

- [ ] `P1-01` Implement data-fetch tool ‖ group:A
  - Creates: src/tools/fetch_data.py, tests/test_fetch_data.py
  - Modifies: src/config.py (modifies uv.lock, .env.example)
  - Reads: src/sources/my_source.py
  - AC: Tool returns MyContentType on success.

- [~] `P1-02` out-of-repo deliverable ‖ group:A
  - Creates: src/elsewhere.py

- [ ] `P1-03` mixed forms ‖ group:B
  * **Modifies:** `src/main.py`, "src/q.py". (see README.md; src/x.py's helper `foo()`)
  - Creates: (modifies `src/routes/mcp.py`); adds tests/test_mcp_x.py  # RT-001: also docs/notes.md
"""

_PLANNER_EXPECTED = {
    "src/tools/fetch_data.py",
    "tests/test_fetch_data.py",
    "src/config.py",
    "uv.lock",
    ".env.example",
    "src/main.py",
    "src/q.py",
    "README.md",
    "src/routes/mcp.py",
    "tests/test_mcp_x.py",
    "docs/notes.md",
}


def _run_inline_scan(wf_path: Path, wave_file: Path) -> list[str]:
    import json
    import subprocess
    import sys

    js = wf_path.read_text(encoding="utf-8")
    start = js.index("'python3 - ' + WAVE_FILE")
    block = js[start : js.index("'PY',", start)]
    lines = re.findall(r"^\s*'(.*)\\n' \+$", block, re.M)
    body = [ln for ln in lines if not ln.startswith("python3 ")]
    script = "\n".join(body).replace("\\\\", "\\").replace("\\'", "'")
    out = subprocess.run(
        [sys.executable, "-", str(wave_file)],
        input=script,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)


@pytest.mark.parametrize("wf_path", _SCAN_COPIES, ids=lambda p: str(p.relative_to(_REPO_ROOT)))
def test_rt001_inline_scan_reads_planner_bare_paths(wf_path: Path, tmp_path: Path) -> None:
    wave = tmp_path / "w009.md"
    wave.write_text(_PLANNER_WAVE, encoding="utf-8")
    found = set(_run_inline_scan(wf_path, wave))
    assert found == _PLANNER_EXPECTED
    assert "src/elsewhere.py" not in found  # [~] todo skipped
    assert "src/sources/my_source.py" not in found  # Reads: is not scope


@pytest.mark.parametrize("wf_path", _SCAN_COPIES, ids=lambda p: str(p.relative_to(_REPO_ROOT)))
def test_rt001_inline_scan_gh164_bare_modifies_clause(wf_path: Path, tmp_path: Path) -> None:
    wave = tmp_path / "w.md"
    wave.write_text("- Creates: (modifies uv.lock, .env.example, src/config.py)\n", encoding="utf-8")
    assert _run_inline_scan(wf_path, wave) == [".env.example", "src/config.py", "uv.lock"]


@pytest.mark.parametrize("wf_path", _SCAN_COPIES, ids=lambda p: str(p.relative_to(_REPO_ROOT)))
def test_rt001_inline_scan_still_reads_backticked_prose_form(wf_path: Path) -> None:
    creates, modifies = extract_wave_scope(FIXTURE.read_text(encoding="utf-8"))
    assert set(_run_inline_scan(wf_path, FIXTURE)) == set(creates) | set(modifies)


def test_rt001_reference_matches_inline_scan_on_planner_format() -> None:
    creates, modifies = extract_wave_scope(_PLANNER_WAVE)
    assert set(creates) | set(modifies) == _PLANNER_EXPECTED
    assert set(modifies) >= {"src/config.py", "uv.lock", ".env.example", "src/routes/mcp.py"}
    assert "src/tools/fetch_data.py" in creates


@pytest.mark.parametrize("token_line", [
    "Creates: src/tools/fetch_data.py, tests/test_fetch_data.py",
    "**Creates:** src/tools/fetch_data.py, tests/test_fetch_data.py",
    "- Creates: `src/tools/fetch_data.py`, `tests/test_fetch_data.py`.",
])
def test_rt001_reference_accepts_bare_bold_and_backticked(token_line: str) -> None:
    creates, modifies = extract_wave_scope(token_line)
    assert creates == ["src/tools/fetch_data.py", "tests/test_fetch_data.py"]
    assert modifies == []


@pytest.mark.parametrize(
    "wf_path",
    _WAVE_CYCLE_COPIES + [_REPO_ROOT / ".claude" / "workflows" / "sdk-wave.js"],
    ids=_WAVE_CYCLE_IDS + ["sdk-wave.js"],
)
def test_rt001_parse_prompt_accepts_bare_paths(wf_path: Path) -> None:
    """The AI parse and the deterministic scan must agree on what a path token is, or
    every planner-format wave aborts Parse with scope-scan-mismatch."""
    prompt = _parse_prompt(wf_path)
    assert "backticked OR BARE" in prompt
    assert "**Creates:**" in prompt
