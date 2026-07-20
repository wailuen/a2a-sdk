"""GH-84: Static conformance tests for the archive-blocking behavior in wave-cycle.js
and sdk-wave.js.

Expected GH-84 blocking behavior:
  - ARCHIVE_INTENT_SCHEMA requires offendingHarnessPaths in addition to offendingPaths.
  - The dual blocking condition `(offendingPaths || offendingHarnessPaths)` blocks archive
    when either list is non-empty. This means dirty/untracked files under harness deliverable
    directories (tests/, workspace/learning/, workspace/scenarios/results/, workspace/prd/,
    .claude/workflows/, harness/workflows/) will also block archive, even if those paths are
    not in the wave's allScope.
  - The archiveIntent agent prompt (step 4) instructs the agent to populate
    offendingHarnessPaths for paths starting with these harness directories.

GH-118 (LRN-119) extends this on sdk-wave.js AND wave-cycle.js (RT-003: the GH-118 todo
originally scoped wave-cycle.js out — see
workspace/learning/LRN-119-mid-wave-module-extraction-untracked.md — but that left the more
widely-used wave runner exposed to the same failure class, so the fix was ported over):
  - ARCHIVE_INTENT_SCHEMA also requires offendingUndeclaredImports.
  - The archiveIntent agent prompt additionally resolves agent_sdk.* imports of dirty/scope
    .py files to file paths and flags any resolved path that is untracked (`git ls-files`
    empty) AND absent from wave.allScope — catching a module extracted mid-wave that is
    imported by a declared file but never itself declared in Creates:.
  - The blocking condition ORs in offendingUndeclaredImports.length > 0 as a third clause.

RT-001 extends GH-118's import cross-check on both runners: the original wording only
told the agent to resolve ABSOLUTE `agent_sdk.*` imports, but every module in
agent_sdk/routes/ uses RELATIVE intra-package imports (`from ..common.origin import
guard_origin`), including the canonical LRN-119 module — so a literal-compliant agent
skipped the exact case this gate was built for. The fix:
  - The archiveIntent agent prompt now also resolves relative imports (`from . import X`,
    `from .mod import Y`, `from ..pkg.mod import Z`) against the importing file's own
    package directory.
  - The prompt no longer restricts resolution to "agent_sdk.* targets" — it now covers any
    intra-package target, whether spelled absolutely or relatively.
  - The prompt also covers the single-segment absolute form (`import agent_sdk.<module>`)
    and the bare top-level from-import form (`from agent_sdk import <name>`).

RT-002 pins the two false-positive guardrails the GH-118 AC requires (not to be confused
with the RT-002 cross-reference test above, which predates this false-positive-guardrail
finding and reused the same ID): the prompt must instruct the agent to ignore stdlib and
third-party imports, and must state that a resolved path which IS tracked (`git ls-files`
returns it) is never an offender, even if it was also modified — so neither class can be
mis-flagged as an undeclared-import offender.

Post-archive follow-up (w035 gh-issues review, distinct from the in-wave RT-001/RT-002/RT-003
findings above — not renumbered into that sequence to avoid colliding with their existing
IDs): the GH-118 todo's Modifies list named only sdk-wave.js, but RT-003 above ported the fix
into BOTH wave-cycle.js copies (.claude/workflows/ and harness/workflows/) too, leaving them
modified-but-undeclared. Compounding that, the harness-deliverable dir list itself did not
watch .claude/workflows/ or harness/workflows/, so an undeclared workflow-file edit could
evade offendingPaths (undeclared) AND offendingHarnessPaths (dir not watched) simultaneously.
Fix: .claude/workflows/ and harness/workflows/ were added to the harness-deliverable dir list
(HARNESS_DIRS below, and the matching schema description / prompt text in both JS files).

These are static text-parse tests — they verify the schema and prompt text without
running the workflow engine.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent

# The two workflow files that implement GH-84 archive blocking
WAVE_CYCLE_RUNTIME = REPO_ROOT / ".claude" / "workflows" / "wave-cycle.js"
SDK_WAVE = REPO_ROOT / ".claude" / "workflows" / "sdk-wave.js"

# The harness deliverable directories checked by GH-84, plus .claude/workflows/ and
# harness/workflows/ (post-archive w035 follow-up — see module docstring above: workflow
# files themselves must be watched, or an undeclared workflow edit evades this check too).
HARNESS_DIRS = [
    "tests/",
    "workspace/learning/",
    "workspace/scenarios/results/",
    "workspace/prd/",
    ".claude/workflows/",
    "harness/workflows/",
    # RT-002 (round-7 fresh-lens): template/.claude/workflows/ is the third byte-identical
    # mirror of the synced workflow files (test_workflow_sync.py keeps it lock-step with
    # harness/workflows/). The w035 follow-up watched the runtime + harness mirrors but not
    # this one; enumerate ALL mirror dirs of a synced file, not just the two most-edited ones.
    "template/.claude/workflows/",
]

# RT-003: GH-118's import cross-check now covers both wave runners (see module docstring above)
GH118_FILES = [WAVE_CYCLE_RUNTIME, SDK_WAVE]
GH118_FILES_IDS = ["wave-cycle.js", "sdk-wave.js"]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _read(path: Path) -> str:
    assert path.exists(), f"Workflow file not found: {path}"
    return path.read_text()


# RT-004: substring-anywhere assertions against the whole file pass even when the token
# lives only in a comment rather than the live archiveIntent agent() prompt or schema.
# These helpers anchor extraction to the actual prompt string / schema block so a gutted
# instruction with a lingering comment mention is caught.

_ARCHIVE_INTENT_PROMPT_RE = re.compile(
    r"const archiveIntent\s*=\s*await agent\((.*?)"
    r"\{\s*schema:\s*ARCHIVE_INTENT_SCHEMA,\s*label:\s*'gate:archive-commit'",
    re.DOTALL,
)

_ARCHIVE_INTENT_SCHEMA_BLOCK_RE = re.compile(
    r"const ARCHIVE_INTENT_SCHEMA\s*=\s*\{.*?\n\}\n",
    re.DOTALL,
)

# RT-002 (post-archive): the offendingHarnessPaths property's own `description` string
# inside ARCHIVE_INTENT_SCHEMA. The single-quoted value contains no single quotes, so
# [^']* captures it whole; the non-greedy prefix skips the type/items sub-object.
_OFFENDING_HARNESS_PATHS_DESCRIPTION_RE = re.compile(
    r"offendingHarnessPaths:\s*\{.*?description:\s*'([^']*)'",
    re.DOTALL,
)

_UNDECLARED_IMPORTS_CONDITION_RE = re.compile(
    r"archiveIntent\.offendingUndeclaredImports\s*&&\s*"
    r"archiveIntent\.offendingUndeclaredImports\.length\s*>\s*0"
)

# RT-002: how far from a documented site a cross-reference comment is allowed to sit and
# still count as "at" it. Wide enough to reach the comment that actually documents each
# site, narrow enough (vs. the whole file) that a stray mention elsewhere — e.g. this
# module's own docstring, which cites both tokens — cannot substitute for the real comment.
_COMMENT_CROSS_REF_WINDOW = 1000


def _window_around(content: str, start: int, end: int, radius: int = _COMMENT_CROSS_REF_WINDOW) -> str:
    """Bounded context around content[start:end], for anchoring a cross-reference
    assertion to the site it documents instead of searching the whole file."""
    return content[max(0, start - radius): min(len(content), end + radius)]


# RT-005: a negative assertion pinned to one exact JS-source concatenation/indentation
# only ever matches the one serialization it was written against — reformatting the prompt
# (or writing a differently-worded regression of the same bug) trivially escapes it. This
# collapses all whitespace runs to a single space first, so the assertion is anchored to the
# wording, not the source layout, and stays meaningful across reformatting.
def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _archive_intent_prompt(content: str, wf_path: Path) -> str:
    """Extract just the prompt string passed to the archiveIntent agent() call."""
    match = _ARCHIVE_INTENT_PROMPT_RE.search(content)
    assert match, (
        f"{wf_path.name}: could not locate the `const archiveIntent = await agent(...)` "
        "call — cannot anchor prompt-content assertions to it."
    )
    return match.group(1)


def _archive_intent_schema_block(content: str, wf_path: Path) -> str:
    """Extract just the `const ARCHIVE_INTENT_SCHEMA = { ... }` block."""
    match = _ARCHIVE_INTENT_SCHEMA_BLOCK_RE.search(content)
    assert match, f"{wf_path.name}: could not locate the ARCHIVE_INTENT_SCHEMA block."
    return match.group(0)


def _offending_harness_paths_description(content: str, wf_path: Path) -> str:
    """Extract the offendingHarnessPaths property's `description` value from the
    ARCHIVE_INTENT_SCHEMA block — the site the harness deliverable dir list is
    actually enforced from at runtime (the agent only sees the schema description
    + prompt, never HARNESS_DIRS or the inline comment)."""
    schema_block = _archive_intent_schema_block(content, wf_path)
    match = _OFFENDING_HARNESS_PATHS_DESCRIPTION_RE.search(schema_block)
    assert match, (
        f"{wf_path.name}: could not locate the offendingHarnessPaths property "
        "description inside ARCHIVE_INTENT_SCHEMA."
    )
    return match.group(1)


# ---------------------------------------------------------------------------
# Schema field presence: offendingHarnessPaths in ARCHIVE_INTENT_SCHEMA
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("wf_path", [WAVE_CYCLE_RUNTIME, SDK_WAVE], ids=["wave-cycle.js", "sdk-wave.js"])
def test_archive_intent_schema_has_offending_harness_paths_in_required(wf_path: Path) -> None:
    """GH-84: ARCHIVE_INTENT_SCHEMA required array must include 'offendingHarnessPaths'.

    Without this field in the schema the agent is not constrained to return it,
    and the blocking condition silently skips harness-path checking.
    """
    content = _read(wf_path)
    # Find the ARCHIVE_INTENT_SCHEMA block and assert the field appears in required
    schema_match = re.search(
        r"const ARCHIVE_INTENT_SCHEMA\s*=\s*\{.*?required:\s*\[([^\]]*)\]",
        content,
        re.DOTALL,
    )
    assert schema_match, (
        f"{wf_path.name}: ARCHIVE_INTENT_SCHEMA not found or has no 'required' array"
    )
    required_array = schema_match.group(1)
    assert "offendingHarnessPaths" in required_array, (
        f"{wf_path.name}: 'offendingHarnessPaths' is missing from "
        f"ARCHIVE_INTENT_SCHEMA.required — GH-84 blocking will silently not work. "
        f"Required array found: {required_array!r}"
    )


@pytest.mark.parametrize("wf_path", [WAVE_CYCLE_RUNTIME, SDK_WAVE], ids=["wave-cycle.js", "sdk-wave.js"])
def test_archive_intent_schema_has_offending_harness_paths_in_properties(wf_path: Path) -> None:
    """GH-84: ARCHIVE_INTENT_SCHEMA properties must define 'offendingHarnessPaths'."""
    content = _read(wf_path)
    schema_block = _archive_intent_schema_block(content, wf_path)
    # Anchored to the schema block itself (not the whole file) so a comment mentioning the
    # token elsewhere can't mask its removal from required[] / properties{}.
    occurrences = schema_block.count("offendingHarnessPaths")
    assert occurrences >= 2, (
        f"{wf_path.name}: 'offendingHarnessPaths' appears only {occurrences} time(s) inside "
        "ARCHIVE_INTENT_SCHEMA — expected at least 2 (required array + properties "
        "definition). GH-84 schema may be incomplete."
    )


# ---------------------------------------------------------------------------
# Agent prompt: step 4 instructs agent to populate offendingHarnessPaths
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("wf_path", [WAVE_CYCLE_RUNTIME, SDK_WAVE], ids=["wave-cycle.js", "sdk-wave.js"])
def test_archive_intent_prompt_contains_harness_dirs(wf_path: Path) -> None:
    """GH-84 (+ post-archive w035 follow-up): archiveIntent agent prompt must instruct the
    agent to check every harness deliverable directory and populate offendingHarnessPaths.
    """
    content = _read(wf_path)
    prompt = _archive_intent_prompt(content, wf_path)
    for harness_dir in HARNESS_DIRS:
        assert harness_dir in prompt, (
            f"{wf_path.name}: harness directory '{harness_dir}' not found in the "
            f"archiveIntent agent prompt — step 4 (collect offendingHarnessPaths) is "
            f"missing or incomplete. GH-84 will not detect uncommitted harness deliverables."
        )


@pytest.mark.parametrize("wf_path", [WAVE_CYCLE_RUNTIME, SDK_WAVE], ids=["wave-cycle.js", "sdk-wave.js"])
def test_archive_intent_schema_description_contains_harness_dirs(wf_path: Path) -> None:
    """RT-002 (post-archive w035 follow-up): every HARNESS_DIRS entry must also appear
    inside the offendingHarnessPaths *schema description*, not only the prompt text.

    The AC (module docstring above) states the new workflow dirs were added to "the
    matching schema description / prompt text in both JS files". The prompt site is
    pinned by test_archive_intent_prompt_contains_harness_dirs, but before this test no
    assertion pinned the dir LIST inside the schema description — the neighbouring
    test_archive_intent_schema_has_offending_harness_paths_in_properties only counts token
    occurrences of the field NAME, never its documented dir list. So the schema description
    (sdk-wave.js:245 / wave-cycle.js:262) could silently drop '.claude/workflows/' or
    'harness/workflows/' with the whole suite still green, narrowing what the archive-gate
    agent is told to watch. This pins each named dir at that second site too — an AC that
    names multiple co-located sites must pin every one, not just the prompt.
    """
    description = _offending_harness_paths_description(_read(wf_path), wf_path)
    for harness_dir in HARNESS_DIRS:
        assert harness_dir in description, (
            f"{wf_path.name}: harness directory '{harness_dir}' not found in the "
            f"offendingHarnessPaths schema description — the archive-gate agent is not told "
            f"to watch it. Schema description found: {description!r}"
        )


# ---------------------------------------------------------------------------
# Dual blocking condition
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("wf_path", [WAVE_CYCLE_RUNTIME, SDK_WAVE], ids=["wave-cycle.js", "sdk-wave.js"])
def test_dual_blocking_condition_present(wf_path: Path) -> None:
    """GH-84: the archive blocking condition must check BOTH offendingPaths and
    offendingHarnessPaths. A single-field check silently misses harness deliverables.

    RT-003: both wave-cycle.js and sdk-wave.js now also gain a third OR clause for
    offendingUndeclaredImports (see test_gh118_* below) — the GH-118 fix originally landed
    on sdk-wave.js only, but was ported to wave-cycle.js to close the asymmetric-protection
    gap on the more widely-used wave runner.
    """
    content = _read(wf_path)
    # The dual condition must use an OR (||) between offendingPaths and offendingHarnessPaths
    # so that either list alone can block archive. A substring-proximity heuristic is too
    # weak — it would pass if offendingHarnessPaths appeared only in a comment nearby.
    # This regex matches the actual JS boolean condition structure.
    dual_condition_re = re.compile(
        r'offendingPaths\s*&&\s*archiveIntent\.offendingPaths\.length\s*>\s*0'
        r'\s*\)\s*\|\|\s*\('
        r'\s*archiveIntent\.offendingHarnessPaths\s*&&\s*archiveIntent\.offendingHarnessPaths\.length\s*>\s*0',
        re.DOTALL,
    )
    assert dual_condition_re.search(content), (
        f"{wf_path.name}: dual blocking condition with '||' between offendingPaths and "
        f"offendingHarnessPaths not found — the OR leg may have been accidentally removed. "
        "Expected pattern: (archiveIntent.offendingPaths && ... > 0) || "
        "(archiveIntent.offendingHarnessPaths && ... > 0)"
    )

    # RT-003: the third OR clause now applies to every runner that implements GH-118
    # (wave-cycle.js AND sdk-wave.js) — not only sdk-wave.js.
    if wf_path in GH118_FILES:
        # GH-118 / LRN-119: a third OR clause guards against a mid-wave-extracted module
        # (untracked, imported by a declared file, absent from wave.allScope) silently
        # passing the gate.
        triple_condition_re = re.compile(
            dual_condition_re.pattern
            + r'\s*\)\s*\|\|\s*\('
            r'\s*archiveIntent\.offendingUndeclaredImports\s*&&\s*archiveIntent\.offendingUndeclaredImports\.length\s*>\s*0',
            re.DOTALL,
        )
        assert triple_condition_re.search(content), (
            f"{wf_path.name}: GH-118 third OR clause for offendingUndeclaredImports not "
            "found in the blocking condition. Expected pattern: "
            "(archiveIntent.offendingPaths && ... > 0) || "
            "(archiveIntent.offendingHarnessPaths && ... > 0) || "
            "(archiveIntent.offendingUndeclaredImports && ... > 0)"
        )


# ---------------------------------------------------------------------------
# GH-118 (LRN-119): schema field presence: offendingUndeclaredImports
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("wf_path", GH118_FILES, ids=GH118_FILES_IDS)
def test_gh118_archive_intent_schema_has_offending_undeclared_imports_in_required(wf_path: Path) -> None:
    """GH-118: ARCHIVE_INTENT_SCHEMA required array must include 'offendingUndeclaredImports'.

    Without this field in the schema the agent is not constrained to return it, and the
    blocking condition's third OR clause silently always evaluates falsy.
    """
    content = _read(wf_path)
    schema_match = re.search(
        r"const ARCHIVE_INTENT_SCHEMA\s*=\s*\{.*?required:\s*\[([^\]]*)\]",
        content,
        re.DOTALL,
    )
    assert schema_match, (
        f"{wf_path.name}: ARCHIVE_INTENT_SCHEMA not found or has no 'required' array"
    )
    required_array = schema_match.group(1)
    assert "offendingUndeclaredImports" in required_array, (
        f"{wf_path.name}: 'offendingUndeclaredImports' is missing from "
        f"ARCHIVE_INTENT_SCHEMA.required — GH-118 blocking will silently not work. "
        f"Required array found: {required_array!r}"
    )


@pytest.mark.parametrize("wf_path", GH118_FILES, ids=GH118_FILES_IDS)
def test_gh118_archive_intent_schema_has_offending_undeclared_imports_in_properties(wf_path: Path) -> None:
    """GH-118: ARCHIVE_INTENT_SCHEMA properties must define 'offendingUndeclaredImports'."""
    content = _read(wf_path)
    schema_block = _archive_intent_schema_block(content, wf_path)
    # Anchored to the schema block itself (not the whole file) so a comment mentioning the
    # token elsewhere can't mask its removal from required[] / properties{}.
    occurrences = schema_block.count("offendingUndeclaredImports")
    assert occurrences >= 2, (
        f"{wf_path.name}: 'offendingUndeclaredImports' appears only {occurrences} time(s) "
        "inside ARCHIVE_INTENT_SCHEMA — expected at least 2 (required array + properties "
        "definition). GH-118 schema may be incomplete."
    )


# ---------------------------------------------------------------------------
# GH-118 (LRN-119): agent prompt instructs the import cross-check
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("wf_path", GH118_FILES, ids=GH118_FILES_IDS)
def test_gh118_archive_intent_prompt_contains_import_cross_check_instructions(wf_path: Path) -> None:
    """GH-118: archiveIntent agent prompt must instruct the agent to resolve agent_sdk.*
    imports of dirty/scope .py files to file paths, check `git ls-files` on each resolved
    path, and cross-reference against wave.allScope to populate offendingUndeclaredImports.
    """
    content = _read(wf_path)
    prompt = _archive_intent_prompt(content, wf_path)
    for expected in ["agent_sdk", "git ls-files", "offendingUndeclaredImports"]:
        assert expected in prompt, (
            f"{wf_path.name}: '{expected}' not found in the archiveIntent agent prompt — "
            "the GH-118 import cross-check instructions are missing or incomplete."
        )


@pytest.mark.parametrize("wf_path", GH118_FILES, ids=GH118_FILES_IDS)
def test_gh118_inline_comment_cross_references_lrn_and_gh(wf_path: Path) -> None:
    """AC: inline GH-84 comment blocks are updated to document the new import-cross-check
    clause and cross-reference LRN-119 / GH-118, so a future reader of either comment block
    (schema or blocking-condition site) finds the rationale without archaeology.

    RT-002: anchored to the schema block and the blocking-condition site rather than
    substring-anywhere against the whole file — a gutted rationale comment must not be
    masked by an unrelated stray mention elsewhere (e.g. this module's own docstring).
    """
    content = _read(wf_path)

    schema_block = _archive_intent_schema_block(content, wf_path)
    for token in ("LRN-119", "GH-118"):
        assert token in schema_block, (
            f"{wf_path.name}: '{token}' not found inside the ARCHIVE_INTENT_SCHEMA block — "
            "GH-118 AC requires the schema's offendingUndeclaredImports description to "
            "cite it there."
        )

    condition_match = _UNDECLARED_IMPORTS_CONDITION_RE.search(content)
    assert condition_match, (
        f"{wf_path.name}: could not locate the offendingUndeclaredImports blocking "
        "condition — cannot anchor cross-reference assertions to it."
    )
    condition_window = _window_around(content, condition_match.start(), condition_match.end())
    for token in ("LRN-119", "GH-118"):
        assert token in condition_window, (
            f"{wf_path.name}: '{token}' not found near the offendingUndeclaredImports "
            "blocking condition — GH-118 AC requires the blocking-condition comment block "
            "to cite it there."
        )


# ---------------------------------------------------------------------------
# RT-001: import cross-check must resolve RELATIVE intra-package imports too,
# not only absolute agent_sdk.* imports — relative imports are the dominant
# style in agent_sdk/routes/, including the canonical LRN-119 module.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("wf_path", GH118_FILES, ids=GH118_FILES_IDS)
def test_rt001_archive_intent_prompt_contains_relative_import_forms(wf_path: Path) -> None:
    """RT-001: the archiveIntent agent prompt must instruct the agent to parse and resolve
    relative intra-package imports (`from . import X`, `from .mod import Y`,
    `from ..pkg.mod import Z`), not only absolute `agent_sdk.*`-spelled imports.

    Every module in agent_sdk/routes/ (oauth.py, a2a.py, ag_ui.py, mcp.py) uses relative
    imports exclusively — a prompt that only resolves absolute imports skips the exact case
    GH-118/LRN-119 exists to catch (agent_sdk/common/origin.py, imported as
    `from ..common.origin import guard_origin`).
    """
    content = _read(wf_path)
    prompt = _archive_intent_prompt(content, wf_path)
    for expected in [
        "from . import",
        "from .mod import",
        "from ..pkg.mod import",
        "RELATIVE",
    ]:
        assert expected in prompt, (
            f"{wf_path.name}: '{expected}' not found in the archiveIntent agent prompt — "
            "RT-001 relative-import resolution instructions are missing or incomplete."
        )


@pytest.mark.parametrize("wf_path", GH118_FILES, ids=GH118_FILES_IDS)
def test_rt001_archive_intent_prompt_resolves_dots_against_importing_file_directory(wf_path: Path) -> None:
    """RT-001: the prompt must anchor relative-import resolution to the directory containing
    the importing file (not to some fixed root), and walk up one parent per extra dot —
    otherwise a resolved path for a deeply-relative import (`from ..pkg.mod import Z`) is
    wrong and the git ls-files check runs against a nonexistent path.
    """
    content = _read(wf_path)
    prompt = _archive_intent_prompt(content, wf_path)
    for expected in [
        "directory that CONTAINS the importing file",
        "walks up one more parent directory",
    ]:
        assert expected in prompt, (
            f"{wf_path.name}: '{expected}' not found in the archiveIntent agent prompt — "
            "RT-001 dot-resolution instructions are missing or incomplete."
        )


@pytest.mark.parametrize("wf_path", GH118_FILES, ids=GH118_FILES_IDS)
def test_rt001_archive_intent_prompt_not_restricted_to_agent_sdk_only_wording(wf_path: Path) -> None:
    """RT-001: the old 'only resolve agent_sdk.* targets' wording scoped the agent to
    absolute imports only. The prompt must now explicitly cover intra-package targets
    'whether spelled absolutely OR relatively' so a literal-compliant agent does not skip
    relative imports again.
    """
    content = _read(wf_path)
    prompt = _archive_intent_prompt(content, wf_path)
    assert "only resolve agent_sdk.* targets" not in prompt, (
        f"{wf_path.name}: the old absolute-only wording 'only resolve agent_sdk.* targets' "
        "is still present in the archiveIntent prompt — RT-001 requires it be broadened to "
        "cover relative imports too."
    )
    assert "absolutely OR relatively" in prompt or "absolutely or relatively" in prompt, (
        f"{wf_path.name}: the archiveIntent prompt does not explicitly state that both "
        "absolute and relative import forms are in scope — RT-001 wording is missing."
    )


@pytest.mark.parametrize("wf_path", GH118_FILES, ids=GH118_FILES_IDS)
def test_rt001_archive_intent_prompt_covers_single_segment_and_top_level_absolute_forms(wf_path: Path) -> None:
    """RT-001: the prompt must also cover the single-segment absolute form
    (`import agent_sdk.<module>`, e.g. `import agent_sdk.foo`) and the bare top-level
    from-import form (`from agent_sdk import <name>`), which the original two-form wording
    (which assumed at least a `<pkg>.<submodule>` split) did not literally include.
    """
    content = _read(wf_path)
    prompt = _archive_intent_prompt(content, wf_path)
    for expected in [
        "import agent_sdk.foo",
        "from agent_sdk import <name>",
        "SINGLE segment",
    ]:
        assert expected in prompt, (
            f"{wf_path.name}: '{expected}' not found in the archiveIntent agent prompt — "
            "RT-001 single-segment / top-level absolute-import coverage is missing."
        )


@pytest.mark.parametrize("wf_path", GH118_FILES, ids=GH118_FILES_IDS)
def test_rt001_relative_from_import_disambiguates_submodule(wf_path: Path) -> None:
    """RT-001 (round-4): the RELATIVE from-import form `from ..pkg import submodule`
    must be disambiguated the SAME way the ABSOLUTE from-import form is — a first
    check of `<pkg-path>/<name>.py` on disk — not resolved straight to `<pkg-path>.py`.

    `from ..credentials import forwarding` (present in agent_sdk/routes/{a2a,ag_ui,mcp}.py)
    names the submodule agent_sdk/credentials/forwarding.py, where `credentials` is a
    PACKAGE. A rule that resolves it straight to the nonexistent `agent_sdk/credentials.py`
    (git ls-files empty, out of scope) flags a false-positive undeclared-import archive
    block on every wave scoping a route file — the exact regression this gate must not
    have. The prompt must therefore instruct the submodule-existence check and pin the
    concrete credentials/forwarding worked example.
    """
    content = _read(wf_path)
    prompt = _archive_intent_prompt(content, wf_path)
    # The submodule-existence disambiguation must be instructed for the relative form,
    # not a straight resolve-to-`<pkg-path>.py`.
    assert "<pkg-path>/<name>.py" in prompt, (
        f"{wf_path.name}: the relative from-import form does not instruct a "
        "`<pkg-path>/<name>.py` submodule-existence check — `from ..pkg import submodule` "
        "will mis-resolve to a nonexistent `<pkg>.py` and false-positive the archive gate."
    )
    # The concrete RT-001 false-positive import and its CORRECT resolution target must
    # both appear as the pinning worked example.
    assert "from ..credentials import forwarding" in prompt, (
        f"{wf_path.name}: the RT-001 `from ..credentials import forwarding` worked example "
        "is missing — the relative-import submodule disambiguation is unspecified."
    )
    assert "agent_sdk/credentials/forwarding.py" in prompt, (
        f"{wf_path.name}: the correct resolution target agent_sdk/credentials/forwarding.py "
        "is missing — the relative from-import still resolves `from ..pkg import submodule` "
        "to the wrong `<pkg>.py`."
    )


@pytest.mark.parametrize("wf_path", GH118_FILES, ids=GH118_FILES_IDS)
def test_rt001_undeclared_import_offender_must_exist_on_disk(wf_path: Path) -> None:
    """RT-001 (round-4) defense-in-depth: step 5c must only flag a resolved path as an
    undeclared-import offender when it actually EXISTS on disk (untracked-but-present).

    The LRN-119 failure mode is a module present locally but untracked; a resolved path
    that does not exist on disk is a mis-resolution (or a genuine broken import the RED
    pre-archive gate already blocks) and must never be flagged — otherwise a single
    mis-resolved import false-positives the whole archive gate.
    """
    content = _read(wf_path)
    prompt = _archive_intent_prompt(content, wf_path)
    assert "EXISTS on disk" in prompt, (
        f"{wf_path.name}: step 5c does not require an offender to actually EXIST on disk — "
        "a mis-resolved (nonexistent) path can still be flagged, false-positiving archive."
    )
    assert "mis-resolution" in prompt, (
        f"{wf_path.name}: step 5c does not state that a non-existent resolved path is a "
        "mis-resolution to be ignored — the existence guard rationale is missing."
    )


@pytest.mark.parametrize("wf_path", GH118_FILES, ids=GH118_FILES_IDS)
def test_rt002_archive_intent_prompt_ignores_stdlib_and_third_party_imports(wf_path: Path) -> None:
    """RT-002: the archiveIntent prompt must instruct the agent to ignore stdlib and
    third-party imports when resolving intra-package targets, so a stdlib/third-party
    import (which never resolves to a tracked-or-untracked repo path) cannot be
    mis-flagged as an undeclared-import offender and false-positive the archive gate.
    """
    content = _read(wf_path)
    prompt = _archive_intent_prompt(content, wf_path)
    assert "Ignore stdlib and third-party imports" in prompt, (
        f"{wf_path.name}: 'Ignore stdlib and third-party imports' not found in the "
        "archiveIntent agent prompt — RT-002 requires this guardrail to prevent the agent "
        "from resolving/flagging stdlib or third-party imports as undeclared-import "
        "offenders."
    )


@pytest.mark.parametrize("wf_path", GH118_FILES, ids=GH118_FILES_IDS)
def test_rt002_archive_intent_prompt_tracked_resolved_path_never_an_offender(wf_path: Path) -> None:
    """RT-002: the archiveIntent prompt must state that a resolved path which IS tracked
    (git ls-files returns it) is never an offender, even if it was also modified — so a
    tracked-but-modified module is not mis-flagged as an undeclared-import offender and
    false-positive the archive gate.
    """
    content = _read(wf_path)
    prompt = _archive_intent_prompt(content, wf_path)
    for expected in [
        "A resolved path that IS tracked",
        "is never an offender either, even if it was also",
    ]:
        assert expected in prompt, (
            f"{wf_path.name}: '{expected}' not found in the archiveIntent agent prompt — "
            "RT-002 requires the tracked-but-modified-is-never-an-offender guardrail to "
            "prevent the archive gate from false-positiving on tracked, modified modules."
        )


@pytest.mark.parametrize("wf_path", GH118_FILES, ids=GH118_FILES_IDS)
def test_rt001_cross_referenced_at_schema_and_prompt(wf_path: Path) -> None:
    """RT-001: 'RT-001' must appear both inside the ARCHIVE_INTENT_SCHEMA block (schema
    description) and inside the live archiveIntent prompt itself — anchored the same way as
    the RT-002 cross-reference test above — so a future reader of either site finds the
    rationale (relative imports are the dominant style in agent_sdk/routes/) without
    archaeology, and a stray mention elsewhere in the file (e.g. the module docstring)
    cannot mask its removal from the live sites.
    """
    content = _read(wf_path)

    schema_block = _archive_intent_schema_block(content, wf_path)
    assert "RT-001" in schema_block, (
        f"{wf_path.name}: 'RT-001' not found inside the ARCHIVE_INTENT_SCHEMA block — "
        "the offendingUndeclaredImports description must cite it there."
    )

    prompt = _archive_intent_prompt(content, wf_path)
    assert "RT-001" in prompt, (
        f"{wf_path.name}: 'RT-001' not found inside the archiveIntent agent prompt — "
        "the relative-import-resolution step must cite it there."
    )


@pytest.mark.parametrize("wf_path", GH118_FILES, ids=GH118_FILES_IDS)
def test_rt001_from_import_disambiguates_subpackage(wf_path: Path) -> None:
    """RT-001 (round-5): the ABSOLUTE and RELATIVE-bare from-import rules must add a
    THIRD disambiguation branch — checking `<pkg-path>/<name>/__init__.py` (ABSOLUTE) /
    `<base-dir>/<name>/__init__.py` (RELATIVE bare) — before falling back to the
    ENCLOSING package's `__init__.py` as a re-exported symbol. Without it, a mid-wave-
    extracted untracked sub-package (`from agent_sdk import newpkg`, or relative
    `from . import newpkg`) resolves to the always-tracked parent __init__.py and is
    never flagged as an undeclared import — a false-negative in exactly the gate GH-118
    was built to close.
    """
    content = _read(wf_path)
    prompt = _archive_intent_prompt(content, wf_path)
    for expected in [
        "agent_sdk/<pkg-path>/<name>/__init__.py",
        "<base-dir>/<name>/__init__.py",
        "SUB-PACKAGE",
    ]:
        assert expected in prompt, (
            f"{wf_path.name}: '{expected}' not found in the archiveIntent agent prompt — "
            "RT-001 (round-5) sub-package disambiguation is missing or incomplete."
        )


@pytest.mark.parametrize("wf_path", GH118_FILES, ids=GH118_FILES_IDS)
def test_rt001_absolute_worked_example_resolves_routes_to_package_init(wf_path: Path) -> None:
    """RT-001 (round-5): the prompt's own worked example was factually wrong about the
    repo layout — it claimed `from agent_sdk import routes` resolves by checking for
    `agent_sdk/routes.py`, but that file does not exist (agent_sdk/routes/ is a
    package). The corrected example must resolve to `agent_sdk/routes/__init__.py`,
    and `agent_sdk/routes.py` must never appear as a resolution TARGET — only as the
    "does NOT exist" foil that motivates falling through to the package `__init__.py`.

    RT-005: the negative half is a semantic, whitespace-normalized check rather than a
    pin to one exact JS-source concatenation/indentation. That exact serialization only
    ever existed transiently in the round-4 working tree and can never match current or
    future (differently formatted, differently worded) content, so a literal-string
    negative here is vacuous — it would silently pass even if the same bug reappeared in
    slightly different phrasing.
    """
    content = _read(wf_path)
    prompt = _archive_intent_prompt(content, wf_path)
    assert "agent_sdk/routes/__init__.py" in prompt, (
        f"{wf_path.name}: the corrected worked example resolving `from agent_sdk import "
        "routes` to `agent_sdk/routes/__init__.py` is missing."
    )

    normalized = _normalize_ws(prompt)
    assert "check for `agent_sdk/routes.py`. if the submodule file exists" not in normalized.lower(), (
        f"{wf_path.name}: the old factually-wrong worked example (`from agent_sdk import "
        "routes` resolved by checking for the nonexistent `agent_sdk/routes.py` as a "
        "resolution TARGET) is still present."
    )
    # `agent_sdk/routes.py` may legitimately appear as the "does NOT exist" foil that
    # motivates falling through to the package `__init__.py` — but every occurrence must be
    # immediately qualified as nonexistent, never stated as the actual resolution target.
    for match in re.finditer(re.escape("agent_sdk/routes.py"), normalized):
        trailing = normalized[match.end(): match.end() + 40].lower()
        assert "does not exist" in trailing, (
            f"{wf_path.name}: `agent_sdk/routes.py` appears at offset {match.start()} in the "
            "prompt without being immediately qualified as nonexistent — it may be "
            "mis-stated as a resolution target again."
        )


# ---------------------------------------------------------------------------
# RT-004 (round-5 fresh-lens debug) — the pkg-path-as-MODULE branch, and
# cross-runner equivalence of the import-resolver ladder.
#
# Root cause of the round-1..4 stall: the RT-004 four-way disambiguation
# (submodule -> sub-package -> pkg-path-as-MODULE -> enclosing package) landed
# in sdk-wave.js only. wave-cycle.js (x3 byte-identical copies) carried a
# strictly-weaker resolver — its ABSOLUTE from-import stopped at three-way (no
# pkg-path-as-MODULE branch) and its RELATIVE from-import collapsed to a
# two-way that resolved straight to `<pkg-path>.py` while falsely claiming it
# disambiguated "EXACTLY as the ABSOLUTE from-import form does". That ships the
# exact LRN-119 false negative the gate exists to prevent:
# `from agent_sdk.common.origin import guard_origin` (origin.py extracted
# mid-wave, untracked) mis-resolved to the nonexistent
# agent_sdk/common/origin/__init__.py, which step 5c then silently drops.
#
# The prior tests asserted only per-file token presence and never compared the
# two runners, so the strictly-weaker port passed CI green. These tests pin the
# pkg-path-as-MODULE branch on BOTH from-import forms of BOTH runners AND assert
# the resolver ladder is byte-equivalent across sdk-wave.js and wave-cycle.js —
# the only guard that fails the moment either runner is refined without the
# other (the byte-identical sync guard in test_workflow_sync.py covers only
# wave-cycle.js's three copies, never sdk-wave.js <-> wave-cycle.js).
# ---------------------------------------------------------------------------

_LADDER_START = "Four forms, resolved differently:"
_LADDER_END = "Ignore stdlib and third-party imports"


def _import_resolver_ladder(content: str, wf_path: Path) -> str:
    """Extract the four-form disambiguation ladder from the archiveIntent prompt.

    Anchored inside the live prompt (not the whole file) so a lingering comment
    mention cannot substitute for the real instruction text.
    """
    prompt = _archive_intent_prompt(content, wf_path)
    start = prompt.find(_LADDER_START)
    end = prompt.find(_LADDER_END, start)
    assert start != -1 and end != -1 and end > start, (
        f"{wf_path.name}: could not locate the import-resolver ladder "
        f"({_LADDER_START!r} .. {_LADDER_END!r}) inside the archiveIntent prompt."
    )
    return prompt[start:end]


@pytest.mark.parametrize("wf_path", GH118_FILES, ids=GH118_FILES_IDS)
def test_rt004_pkg_path_as_module_branch_present(wf_path: Path) -> None:
    """RT-004: BOTH the ABSOLUTE and the RELATIVE-with-module-path from-import
    forms must carry the pkg-path-as-MODULE branch ("<pkg-path> itself names a
    MODULE and <name> is a symbol inside it") — the third of the four resolution
    branches, checking `agent_sdk/<pkg-path>.py` / `<pkg-path>.py` on disk.

    Without it, `from agent_sdk.common.origin import guard_origin` (origin.py a
    module extracted mid-wave, untracked, out of scope) mis-resolves to the
    nonexistent agent_sdk/common/origin/__init__.py, which step 5c drops as a
    mis-resolution and never flags — the exact LRN-119 boot-ImportError false
    negative this gate exists to prevent. The prior token-presence tests passed
    on a strictly-weaker port that omitted this branch; these pin it.
    """
    ladder = _import_resolver_ladder(_read(wf_path), wf_path)

    # The branch must appear on BOTH from-import forms (absolute + relative).
    occurrences = ladder.count("itself names a MODULE and")
    assert occurrences == 2, (
        f"{wf_path.name}: the pkg-path-as-MODULE branch ('itself names a MODULE "
        f"and') must appear in BOTH the ABSOLUTE and RELATIVE from-import forms; "
        f"found {occurrences}. A strictly-weaker three-/two-way port is present."
    )

    # ABSOLUTE-form worked example: the symbol-from-module case resolves to the
    # module .py, NEVER to the nonexistent enclosing package __init__.py.
    assert "NEVER to the nonexistent `agent_sdk/common/origin/__init__.py`" in ladder, (
        f"{wf_path.name}: the RT-004 ABSOLUTE worked example (guard_origin resolves "
        "to agent_sdk/common/origin.py, never the enclosing __init__.py) is missing "
        "— the pkg-path-as-MODULE branch is not exercised on the absolute form."
    )

    # RT-004 sub-package worked example on the RELATIVE form — proves the RELATIVE
    # form is a genuine four-way ladder, not the old straight-to-`<pkg-path>.py`.
    assert "from ..common import newsubpkg" in ladder, (
        f"{wf_path.name}: the RT-004 RELATIVE sub-package worked example "
        "(`from ..common import newsubpkg` -> agent_sdk/common/newsubpkg/__init__.py) "
        "is missing — the relative form may still collapse to a two-way resolve."
    )

    # The strictly-weaker RELATIVE-form wording ("EXACTLY as the ABSOLUTE
    # from-import form does", which preceded a two-way collapse) must be gone.
    assert "EXACTLY as the ABSOLUTE from-import form" not in ladder, (
        f"{wf_path.name}: the strictly-weaker RELATIVE-form wording 'EXACTLY as the "
        "ABSOLUTE from-import form does' (which fronted a two-way straight-to-"
        "`<pkg-path>.py` collapse) is still present — port the four-way order."
    )


def test_import_resolver_ladder_identical_across_runners() -> None:
    """RT-004 root-cause guard: the import-resolver ladder is shared behavioral
    logic that MUST stay identical between sdk-wave.js and wave-cycle.js.

    Prior rounds asserted only per-file token presence, never cross-runner
    equivalence — so the RT-004 four-way refinement landing in sdk-wave.js alone
    silently diverged from wave-cycle.js and passed CI green. This whitespace-
    normalized equivalence assertion fails the moment either runner's ladder is
    edited without the other, closing the sdk-wave.js <-> wave-cycle.js drift
    axis that test_workflow_sync.py (wave-cycle.js's three copies only) does not
    cover.
    """
    sdk_ladder = _import_resolver_ladder(_read(SDK_WAVE), SDK_WAVE)
    wc_ladder = _import_resolver_ladder(_read(WAVE_CYCLE_RUNTIME), WAVE_CYCLE_RUNTIME)
    assert _normalize_ws(sdk_ladder) == _normalize_ws(wc_ladder), (
        "import-resolver ladder diverges between sdk-wave.js and wave-cycle.js — "
        "the four-way disambiguation (submodule -> sub-package -> pkg-path-as-"
        "MODULE -> enclosing package) must be identical across both runners. Any "
        "refinement to one MUST be ported to the other; the byte-identical sync "
        "guard covers only wave-cycle.js's three copies, never this axis."
    )
