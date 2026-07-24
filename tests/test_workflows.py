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

RT-002 (fix round, redteam finding on this test module): the round-5 RT-001 archive-gate
hardening — step 4b running `git -C template status --short` and folding dirty
template/.claude/workflows/ paths into offendingHarnessPaths, because template/ is gitignored
in THIS repo and a dirty path inside it can never surface via step 1's plain top-level
`git status --short` — landed in all four archive-gate runners with zero regression tests
pinning the actual mechanism. The HARNESS_DIRS membership assertions only passed because the
literal substring 'template/.claude/workflows/' happens to also appear inside step 4b's prose
(the worked example and the schema description's parenthetical); they never asserted the
`git -C template status --short` command itself, so deleting step 4b's real mechanism while an
incidental mention of the path lingered elsewhere would keep those assertions green. Fix:
STEP4B_FILES-parametrized tests below pin the literal `git -C template status --short`
instruction in the archiveIntent prompt and the 'step 4b' folding language in the
offendingHarnessPaths schema description, across all four runners. The HARNESS_DIRS entry's
comment was also corrected — template/.claude/workflows/ was never a step-4 main-repo
dirty-path directory the way its neighbours are; it rides along in that list only because its
path string also appears inside the separate step 4b prose.

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
    # RT-002 (round-7 fresh-lens; comment corrected by the RT-002 fix-round finding on this
    # test module): unlike every other entry above, template/.claude/workflows/ is NOT watched
    # via step 4's plain top-level `git status --short` cross-reference — template/ is
    # gitignored in THIS repo, so a dirty path inside it can never appear in that scan. It is
    # folded into offendingHarnessPaths exclusively via the separate step 4b mechanism
    # (`git -C template status --short`, run against the nested template/ peer repo — pinned by
    # the STEP4B_FILES-parametrized tests below). It remains in this flat list only because the
    # generic prompt/schema-description membership tests below also happen to touch step 4b's
    # prose through it; it is not itself a step-4 main-repo dirty-path directory.
    "template/.claude/workflows/",
]

# RT-003: GH-118's import cross-check now covers both wave runners (see module docstring above)
GH118_FILES = [WAVE_CYCLE_RUNTIME, SDK_WAVE]
GH118_FILES_IDS = ["wave-cycle.js", "sdk-wave.js"]

# LRN-132/GH-123: the three byte-identical wave-cycle.js mirrors (test_workflow_sync.py
# keeps harness/ and template/ lock-step with the runtime copy).
HARNESS_WAVE_CYCLE = REPO_ROOT / "harness" / "workflows" / "wave-cycle.js"
TEMPLATE_WAVE_CYCLE = REPO_ROOT / "template" / ".claude" / "workflows" / "wave-cycle.js"


# RT-003: template/.claude/workflows/wave-cycle.js lives under the fully gitignored
# template/ nested peer repo (.gitignore:38) — a checkout without it populated must
# skip cases referencing it rather than fail opaquely inside `_read()`'s "Workflow
# file not found" assertion. Mirrors test_workflow_sync.py's Axis-2
# `if TEMPLATE_DIR.exists() else set()` guard.
def _existing_wf_cases(
    cases: list[tuple[Path, str]], ids: list[str]
) -> tuple[list[tuple[Path, str]], list[str]]:
    kept = [(case, case_id) for case, case_id in zip(cases, ids) if case[0].exists()]
    return [case for case, _ in kept], [case_id for _, case_id in kept]


# (workflow file, expected oauth-surface path string in that file's dialect) — sdk-wave.js
# addresses paths as agent_sdk/..., wave-cycle.js and its mirrors as src/...
OAUTH_SURFACE_CASES, OAUTH_SURFACE_CASES_IDS = _existing_wf_cases(
    [
        (SDK_WAVE, "agent_sdk/routes/oauth"),
        (WAVE_CYCLE_RUNTIME, "src/routes/oauth"),
        (HARNESS_WAVE_CYCLE, "src/routes/oauth"),
        (TEMPLATE_WAVE_CYCLE, "src/routes/oauth"),
    ],
    [
        "sdk-wave.js",
        "wave-cycle.js(runtime)",
        "wave-cycle.js(harness)",
        "wave-cycle.js(template)",
    ],
)

# RT-001: agent_sdk/auth/middleware.py (src/auth/middleware.py in the wave-cycle.js
# dialect) is the file that actually DEFINES require_identity — routes/oauth only backs
# it. Same shared-surface membership requirement as OAUTH_SURFACE_CASES above.
MIDDLEWARE_SURFACE_CASES, MIDDLEWARE_SURFACE_CASES_IDS = _existing_wf_cases(
    [
        (SDK_WAVE, "agent_sdk/auth/middleware"),
        (WAVE_CYCLE_RUNTIME, "src/auth/middleware"),
        (HARNESS_WAVE_CYCLE, "src/auth/middleware"),
        (TEMPLATE_WAVE_CYCLE, "src/auth/middleware"),
    ],
    [
        "sdk-wave.js",
        "wave-cycle.js(runtime)",
        "wave-cycle.js(harness)",
        "wave-cycle.js(template)",
    ],
)


# RT-001 (this wave): the three wave-cycle.js mirrors only, for the seam-gate
# regression test below — sdk-wave.js never had the SEAM_ROUTE_MARKERS gating bug
# (it dispatches the seam task unconditionally), so it is out of scope for that test.
def _existing_wf_files(paths: list[Path], ids: list[str]) -> tuple[list[Path], list[str]]:
    kept = [(p, i) for p, i in zip(paths, ids) if p.exists()]
    return [p for p, _ in kept], [i for _, i in kept]


WAVE_CYCLE_MIRRORS, WAVE_CYCLE_MIRROR_IDS = _existing_wf_files(
    [WAVE_CYCLE_RUNTIME, HARNESS_WAVE_CYCLE, TEMPLATE_WAVE_CYCLE],
    ["wave-cycle.js(runtime)", "wave-cycle.js(harness)", "wave-cycle.js(template)"],
)


# RT-002 (fix round): the round-5 RT-001 step 4b archive-gate hardening (`git -C template
# status --short`, folding dirty template/.claude/workflows/ paths into
# offendingHarnessPaths) applies to every runner that implements the archive gate —
# sdk-wave.js plus all three wave-cycle.js mirrors — not only the two GH118_FILES entries,
# so its regression coverage spans all four.
STEP4B_FILES, STEP4B_FILES_IDS = _existing_wf_files(
    [SDK_WAVE, WAVE_CYCLE_RUNTIME, HARNESS_WAVE_CYCLE, TEMPLATE_WAVE_CYCLE],
    ["sdk-wave.js", "wave-cycle.js(runtime)", "wave-cycle.js(harness)", "wave-cycle.js(template)"],
)


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
# RT-002 (fix round): step 4b — `git -C template status --short` folding dirty
# template/.claude/workflows/ paths into offendingHarnessPaths — had zero regression
# tests pinning the actual mechanism in any runner. The two tests above only ever
# checked the generic HARNESS_DIRS membership, which happened to pass because the
# literal 'template/.claude/workflows/' substring also appears inside step 4b's prose;
# neither asserted the `git -C template status --short` command itself. These tests
# anchor directly to that mechanism, across all four archive-gate runners.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("wf_path", STEP4B_FILES, ids=STEP4B_FILES_IDS)
def test_rt002_step4b_prompt_contains_git_dash_c_template_instruction(wf_path: Path) -> None:
    """RT-002 (fix round): the archiveIntent prompt must instruct the agent to separately
    run `git -C template status --short` (guarded by an `if a template/ directory exists`
    check) and fold any resulting dirty .claude/workflows/ path into offendingHarnessPaths.

    template/ is gitignored in THIS repo, so a dirty path inside it can never surface via
    step 1's plain top-level `git status --short` — step 4b is the ONLY way this gate can
    see an uncommitted template/.claude/workflows/ mirror. A future edit that deletes step
    4b (or its `if a template/ directory exists` guard) while leaving the literal
    'template/.claude/workflows/' substring intact elsewhere in the prompt would keep the
    generic HARNESS_DIRS membership tests above green while silently reopening the
    dead-guard this mechanism exists to close. Pinning the command text directly closes
    that gap.
    """
    content = _read(wf_path)
    prompt = _archive_intent_prompt(content, wf_path)
    for expected in [
        "git -C template status --short",
        "If a `template/` directory exists",
    ]:
        assert expected in prompt, (
            f"{wf_path.name}: '{expected}' not found in the archiveIntent agent prompt — "
            "RT-002 (fix round): the step 4b template-mirror folding instruction is missing "
            "or incomplete."
        )


@pytest.mark.parametrize("wf_path", STEP4B_FILES, ids=STEP4B_FILES_IDS)
def test_rt002_step4b_schema_description_documents_template_folding(wf_path: Path) -> None:
    """RT-002 (fix round): the offendingHarnessPaths schema description — the site the
    archive-gate agent is actually constrained against at runtime, per
    _offending_harness_paths_description's own docstring — must document the step 4b
    folding mechanism (the 'step 4b' label and the `git -C template status --short`
    command) itself, not merely happen to contain the literal
    'template/.claude/workflows/' path substring incidentally.
    """
    description = _offending_harness_paths_description(_read(wf_path), wf_path)
    for expected in ["step 4b", "git -C template status --short"]:
        assert expected in description, (
            f"{wf_path.name}: '{expected}' not found in the offendingHarnessPaths schema "
            "description — RT-002 (fix round): the step 4b template-mirror folding "
            "mechanism is not documented at the site the archive-gate agent is actually "
            f"constrained by. Schema description found: {description!r}"
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


def _surface_array_body(content: str, name: str, wf_path: Path) -> str:
    """Extract the literal contents between `[` and `]` of `const <name> = [...]`,
    plus the body of any array folded in via a trailing `.concat(<OTHER_ARRAY>)`
    (e.g. RT-001's `AUTH_SURFACE` folded into A2A_SURFACE/MCP_SURFACE/AGUI_SURFACE) —
    so a membership check sees the fully-resolved surface, not just the literal's
    own bracket contents."""
    match = re.search(rf"const {name}\s*=\s*(\[.*?\](?:\.concat\(\w+\))*)", content, re.DOTALL)
    assert match is not None, f"{wf_path.name}: could not find `const {name} = [...]` array"
    declaration = match.group(1)
    body = "".join(re.findall(r"\[(.*?)\]", declaration, re.DOTALL))
    for concat_name in re.findall(r"\.concat\((\w+)\)", declaration):
        concat_match = re.search(rf"const {concat_name}\s*=\s*\[(.*?)\]", content, re.DOTALL)
        assert concat_match is not None, (
            f"{wf_path.name}: `const {name}` references `.concat({concat_name})` but no "
            f"`const {concat_name} = [...]` array was found"
        )
        body += concat_match.group(1)
    return body


@pytest.mark.parametrize("wf_path,oauth_path", OAUTH_SURFACE_CASES, ids=OAUTH_SURFACE_CASES_IDS)
def test_lrn132_oauth_present_in_all_three_protocol_surfaces(
    wf_path: Path, oauth_path: str
) -> None:
    """LRN-132/GH-123: OAuthTokenStore.verify (routes/oauth) backs require_identity
    (auth/middleware.py), which every protected A2A, AG-UI, and MCP route depends on via
    Depends() — not an MCP-only surface. oauth must appear in A2A_SURFACE and AGUI_SURFACE
    alongside its pre-existing MCP_SURFACE membership in every wave runner that classifies
    protocol surfaces, so a wave touching only oauth.py still dispatches a2a-advisor and
    ag-ui-advisor, not mcp-advisor alone. Locks the membership so a future edit can't
    silently narrow oauth back to a single protocol without failing CI.
    """
    content = _read(wf_path)
    for surface_name in ("A2A_SURFACE", "MCP_SURFACE", "AGUI_SURFACE"):
        body = _surface_array_body(content, surface_name, wf_path)
        assert oauth_path in body, (
            f"{wf_path.name}: {surface_name} does not include {oauth_path!r} — "
            "LRN-132/GH-123: oauth backs require_identity for A2A, AG-UI, and MCP "
            "routes alike, so it must appear in all three protocol-surface arrays, "
            "not just MCP_SURFACE."
        )


@pytest.mark.parametrize("wf_path,middleware_path", MIDDLEWARE_SURFACE_CASES, ids=MIDDLEWARE_SURFACE_CASES_IDS)
def test_rt001_middleware_present_in_all_three_protocol_surfaces(
    wf_path: Path, middleware_path: str
) -> None:
    """RT-001: routes/oauth only BACKS require_identity — auth/middleware.py is the file
    that actually DEFINES it (middleware.py:96) and is consumed via Depends() by all four
    route files (a2a, ag_ui, mcp, agent_card). The GH-123 fix added oauth to all three
    protocol-surface arrays but omitted middleware.py, leaving it in ZERO surfaces: a wave
    that modifies only middleware.py (e.g. an audience-binding or WWW-Authenticate
    resource_metadata regression in require_identity) dispatched no protocol advisor at
    all — the same-class blind spot GH-123/LRN-132 exists to close, on the more
    security-sensitive shared auth gate. Locks middleware.py membership the same way
    test_lrn132_oauth_present_in_all_three_protocol_surfaces locks oauth's.
    """
    content = _read(wf_path)
    for surface_name in ("A2A_SURFACE", "MCP_SURFACE", "AGUI_SURFACE"):
        body = _surface_array_body(content, surface_name, wf_path)
        assert middleware_path in body, (
            f"{wf_path.name}: {surface_name} does not include {middleware_path!r} — "
            "RT-001: middleware.py DEFINES require_identity for A2A, AG-UI, and MCP "
            "routes alike, so it must appear in all three protocol-surface arrays, "
            "same as routes/oauth."
        )


# ---------------------------------------------------------------------------
# RT-001 (this wave): seam leg must not be gated on a second, independently
# maintained marker list — a file promoted into a protocol-surface array (e.g.
# src/auth/middleware) must not be able to skip the seam audit.
# ---------------------------------------------------------------------------

_SEAM_INITIAL_BLOCK_RE = re.compile(
    r"const SEAM_ROUTE_MARKERS.*?const protoResults = \(await parallel\(advisorTasks\)\)",
    re.DOTALL,
)

_SEAM_RECHECK_BLOCK_RE = re.compile(
    r"// Seam recheck:.*?const recheckResults = \(await parallel\(recheckTasks\)\)",
    re.DOTALL,
)


def _seam_initial_block(content: str, wf_path: Path) -> str:
    match = _SEAM_INITIAL_BLOCK_RE.search(content)
    assert match, (
        f"{wf_path.name}: could not locate the seam-check block "
        "(const SEAM_ROUTE_MARKERS ... const protoResults = ...)."
    )
    return match.group(0)


def _seam_recheck_block(content: str, wf_path: Path) -> str:
    match = _SEAM_RECHECK_BLOCK_RE.search(content)
    assert match, (
        f"{wf_path.name}: could not locate the seam-recheck block "
        "(// Seam recheck: ... const recheckResults = ...)."
    )
    return match.group(0)


# RT-002 (this wave): substring checks like `"if (seamPaths.length === 0)" not in block`
# only catch the ONE gating spelling that was actually removed — a future refactor that
# re-guards the seam push with different syntax (`if (!seamPaths.length)`,
# `if (seamPaths.length < 1)`, or any other wrapper) would reintroduce the exact GH-123
# seam-skip bug while such a check stays green, because it never inspects the push's
# actual nesting. `_leading_indent` gives a syntax-independent structural signal instead:
# wrapping a statement in ANY `if (...) {` adds one indent level to everything inside the
# braces, regardless of the condition's spelling. Comparing the seam push's indent to an
# unconditional sibling statement's indent (one that runs whenever the enclosing block
# runs at all) catches every re-gating shape, not just the one this wave removed.
def _leading_indent(content: str, anchor_pattern: str, wf_path: Path, label: str) -> int:
    match = re.search(r"^( *)" + anchor_pattern, content, re.MULTILINE | re.DOTALL)
    assert match is not None, (
        f"{wf_path.name}: could not find {label} (pattern: {anchor_pattern!r})"
    )
    return len(match.group(1))


# RT-003 (round-5 fresh-lens): indentation parity (`_leading_indent`) is NOT a reliable
# proxy for "unconditional dispatch" in this codebase, because it uses non-indented
# conditional bodies — `if (!protocolBlocked) {` (wave-cycle.js recheck guard) keeps its
# whole body at the SAME 4-space indent as the `if (` line. A future edit re-gating the
# seam push with a matching non-indented `if (!seamPaths.length) { recheckTasks.push(...) }`
# would keep push-indent == sibling-indent AND evade the substring check (which only
# forbids one literal spelling), false-passing while re-gating the seam audit. The
# syntax-independent structural fix is to assert NO `if (` conditional textually precedes
# the seam push within its own block — a wrapper cannot dispatch the push without a
# preceding `if (`, regardless of how the body is indented.
def _text_before_anchor(block: str, anchor_pattern: str, wf_path: Path, label: str) -> str:
    match = re.search(anchor_pattern, block, re.DOTALL)
    assert match is not None, (
        f"{wf_path.name}: could not find {label} (pattern: {anchor_pattern!r})"
    )
    return block[: match.start()]


# RT-002 (round-7 fresh-lens): returns the text of `block` from the anchor onward — used to
# isolate the seam push's own prompt from sibling per-protocol pushes that also appear in
# the same block (sdk-wave.js's recheck block, and the sdk-wave initial block, carry the
# per-protocol pushes ahead of the seam push). Asserting a scope-list invariant on the
# whole block would false-pass when a sibling push carries the scope but the seam push has
# lost it; slicing from the seam anchor pins the invariant to the seam prompt itself.
def _text_from_anchor(block: str, anchor_pattern: str, wf_path: Path, label: str) -> str:
    match = re.search(anchor_pattern, block, re.DOTALL)
    assert match is not None, (
        f"{wf_path.name}: could not find {label} (pattern: {anchor_pattern!r})"
    )
    return block[match.start():]


# Shared seam-push anchors: `<tasks>.push(function() {` immediately followed (within 160
# chars) by the seam prompt's opening line. Reused by the ungating tests above and the
# RT-002 scope-list tests below.
_SEAM_INITIAL_PUSH_ANCHOR = (
    r"advisorTasks\.push\(function\(\) \{.{0,160}?Cross-protocol seam audit"
)
_SEAM_RECHECK_PUSH_ANCHOR = (
    r"recheckTasks\.push\(function\(\) \{.{0,160}?Cross-protocol seam re-audit"
)


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_MIRRORS, ids=WAVE_CYCLE_MIRROR_IDS)
def test_rt001_seam_task_not_gated_on_seam_route_markers(wf_path: Path) -> None:
    """RT-001 (this wave): this wave's own RT-001 change added src/auth/middleware into
    A2A_SURFACE/MCP_SURFACE/AGUI_SURFACE, but SEAM_ROUTE_MARKERS (['routes', 'a2a', 'mcp',
    'agent_card', 'ag_ui', 'a2ui'] — matched as WHOLE path segments since RT-001 round-7,
    so no auth segment ever matches: 'oauth'/'oauth_tokens' are not one of these markers)
    contains no auth-path fragment.
    A wave touching only src/auth/middleware.py therefore set runProtocol=true and
    dispatched the three per-protocol advisors, but seamPaths was empty so the seam leg
    — the only leg that checks 'Auth mode enforced uniformly: no surface accepts a token
    type another rejects' — was silently SKIPPED. The seam task must be dispatched
    whenever this block runs at all (it only runs inside `if (runProtocol)`), never gated
    on a second, independently-maintained marker list. Matches sdk-wave.js, which has
    never gated its seam task on any marker list.

    RT-002: beyond the substring checks below (which only catch the exact spelling this
    wave removed), also structurally verifies the seam push is UNGATED by comparing its
    indentation to the unconditional `const seamPaths = wave.allScope.filter(...)`
    statement in the same block — any `if (...) {` wrapper, spelled any way, adds an
    indent level and fails this check regardless of the guard's exact syntax.
    """
    content = _read(wf_path)
    block = _seam_initial_block(content, wf_path)
    assert "proto:seam" in block, (
        f"{wf_path.name}: the seam-check block does not contain the proto:seam agent() call."
    )
    assert "if (seamPaths.length === 0)" not in block, (
        f"{wf_path.name}: the seam task is still gated on `if (seamPaths.length === 0)` — "
        "RT-001: a protocol-surface member absent from SEAM_ROUTE_MARKERS (e.g. "
        "src/auth/middleware) can skip the seam audit entirely. Dispatch on runProtocol "
        "instead (this block already only runs inside the `if (runProtocol)` branch)."
    )
    seam_push_indent = _leading_indent(
        block, r"advisorTasks\.push\(function\(\) \{.{0,160}?Cross-protocol seam audit",
        wf_path, "the seam advisorTasks.push(...) call",
    )
    seam_const_indent = _leading_indent(
        block, r"const seamPaths = wave\.allScope\.filter\(",
        wf_path, "the unconditional `const seamPaths = ...` statement",
    )
    assert seam_push_indent == seam_const_indent, (
        f"{wf_path.name}: the seam advisorTasks.push(...) is indented {seam_push_indent} "
        f"spaces but the unconditional `const seamPaths = wave.allScope.filter(...)` "
        f"sibling statement in the same block is indented {seam_const_indent} spaces — "
        "RT-002: a deeper indent means the push has been re-wrapped in a NEW conditional "
        "guard (any spelling — `if (!seamPaths.length)`, `if (seamPaths.length < 1)`, "
        "etc.), reintroducing the GH-123 seam-skip bug under syntax the plain substring "
        "check above cannot see. The seam push must sit at the same nesting level as "
        "`const seamPaths`, a statement that unconditionally runs whenever this block does."
    )
    # RT-003 (round-5): indentation parity is defeated by a non-indented conditional body
    # (this codebase uses one at `if (!protocolBlocked) {`). Also assert no `if (` textually
    # precedes the seam push within the block — a wrapper cannot re-gate the push without a
    # preceding `if (`, regardless of how its body is indented.
    seam_push_prefix = _text_before_anchor(
        block, r"advisorTasks\.push\(function\(\) \{.{0,160}?Cross-protocol seam audit",
        wf_path, "the seam advisorTasks.push(...) call",
    )
    assert "if (" not in seam_push_prefix, (
        f"{wf_path.name}: an `if (` conditional textually precedes the seam "
        "advisorTasks.push(...) within the seam block — RT-003: the push has been wrapped "
        "in a guard. Indentation parity alone does not catch this, because the codebase "
        "uses non-indented conditional bodies (e.g. `if (!protocolBlocked) {`) that keep a "
        "wrapped push at the same indent as its unconditional siblings. The seam push must "
        "not be wrapped in any conditional; it runs whenever this block does."
    )


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_MIRRORS, ids=WAVE_CYCLE_MIRROR_IDS)
def test_rt001_seam_recheck_task_not_gated_on_seam_paths(wf_path: Path) -> None:
    """RT-001 (this wave), recheck-path counterpart of
    test_rt001_seam_task_not_gated_on_seam_route_markers: the recheck dispatch mirrored
    the same seamPaths.length > 0 gate, so a middleware-only wave with critical protocol
    findings would also skip the seam RE-audit after the fix.

    RT-002: also structurally verifies the recheck push is UNGATED, the same way as the
    initial-dispatch counterpart above — see that test's docstring for why an indentation
    comparison catches re-gating under any syntax, not just the one substring this wave
    removed.
    """
    content = _read(wf_path)
    block = _seam_recheck_block(content, wf_path)
    assert "proto:recheck:seam" in block, (
        f"{wf_path.name}: the seam-recheck block does not contain the proto:recheck:seam "
        "agent() call."
    )
    assert "if (seamPaths.length > 0)" not in block, (
        f"{wf_path.name}: the seam recheck task is still gated on "
        "`if (seamPaths.length > 0)` — RT-001: same gap as the initial seam task, on the "
        "recheck path."
    )
    recheck_push_indent = _leading_indent(
        block, r"recheckTasks\.push\(function\(\) \{.{0,160}?Cross-protocol seam re-audit",
        wf_path, "the seam recheckTasks.push(...) call",
    )
    # `const recheckTasks = []` sits just before the `if (runA2A) { ... }` legs, outside
    # this test's `block` (which starts at `// Seam recheck:`) — search the FULL file
    # content for it instead. The indent value is intrinsic to the matched line itself,
    # not to the substring it was found within, so this is equally valid as a same-level
    # sibling anchor: both it and the ungated seam push are direct children of the
    # enclosing `if (!protocolBlocked) {` body, one level above the `if (runA2A) {`-gated
    # per-protocol recheck legs.
    recheck_const_indent = _leading_indent(
        content, r"const recheckTasks = \[\]",
        wf_path, "the unconditional `const recheckTasks = []` statement",
    )
    assert recheck_push_indent == recheck_const_indent, (
        f"{wf_path.name}: the seam recheckTasks.push(...) is indented {recheck_push_indent} "
        f"spaces but the unconditional `const recheckTasks = []` sibling statement is "
        f"indented {recheck_const_indent} spaces — RT-002: a deeper indent means the "
        "recheck push has been re-wrapped in a NEW conditional guard, reintroducing the "
        "GH-123 seam-recheck-skip bug under syntax the plain substring check above cannot "
        "see."
    )
    # RT-003 (round-5): the recheck push's enclosing `if (!protocolBlocked) {` block body is
    # deliberately NOT indented (its body sits at the same 4-space level as the `if (` line),
    # so `if (!seamPaths.length) { recheckTasks.push(...) }` written in that same non-indented
    # style would keep recheck_push_indent == recheck_const_indent AND evade the substring
    # check above. Assert no `if (` textually precedes the seam recheck push within the
    # recheck block — the syntax- and indent-independent signal that no conditional wraps it.
    recheck_push_prefix = _text_before_anchor(
        block, r"recheckTasks\.push\(function\(\) \{.{0,160}?Cross-protocol seam re-audit",
        wf_path, "the seam recheckTasks.push(...) call",
    )
    assert "if (" not in recheck_push_prefix, (
        f"{wf_path.name}: an `if (` conditional textually precedes the seam "
        "recheckTasks.push(...) within the seam-recheck block — RT-003: the recheck push has "
        "been wrapped in a guard. Because the enclosing `if (!protocolBlocked) {` body is "
        "non-indented, an equally non-indented `if (!seamPaths.length) {` wrapper would pass "
        "the indentation-parity check above while re-gating the seam re-audit. The recheck "
        "push must not be wrapped in any conditional; it runs whenever the recheck block does."
    )


# ---------------------------------------------------------------------------
# RT-002 (round-5 fresh-lens): the round-4 removal of '/oauth' from SEAM_ROUTE_MARKERS
# — which had substring-matched the credential-verification store src/auth/oauth_tokens
# (an AUTH_SURFACE member, NOT a route file) at the '.../auth/oauth_tokens' boundary and
# listed it under the seam hint's route heading while its sibling auth members fell
# through to the placeholder — carried NO regression test. The ungating tests above only
# assert the seam push is DISPATCHED; none asserts SEAM_ROUTE_MARKERS is free of an
# auth-path fragment. A future edit re-adding '/oauth' (or any 'auth' fragment) would
# silently reintroduce the mislabel. src/routes/oauth, the one genuine OAuth route, is
# already caught by the 'routes' segment marker, so no 'auth' fragment is ever needed here.
# ---------------------------------------------------------------------------

_SEAM_ROUTE_MARKERS_RE = re.compile(r"const SEAM_ROUTE_MARKERS\s*=\s*\[([^\]]*)\]")


def _seam_route_markers(content: str, wf_path: Path) -> list[str]:
    match = _SEAM_ROUTE_MARKERS_RE.search(content)
    assert match is not None, (
        f"{wf_path.name}: could not locate the `const SEAM_ROUTE_MARKERS = [...]` array."
    )
    return re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_MIRRORS, ids=WAVE_CYCLE_MIRROR_IDS)
def test_rt002_seam_route_markers_contain_no_auth_fragment(wf_path: Path) -> None:
    """RT-002 (round-5): pin the round-4 symmetry fix — SEAM_ROUTE_MARKERS must contain
    no auth-path fragment. A marker like '/oauth' or 'auth/' substring-matches
    AUTH_SURFACE members (src/routes/oauth, src/auth/oauth_tokens, src/auth/middleware,
    src/auth/api_keys, src/auth/identity), listing SOME of them under the seam hint's
    route heading while the rest fall through to the placeholder — the exact asymmetric
    mislabel round-4 removed by dropping '/oauth'. The genuine OAuth route src/routes/oauth
    is caught by the 'routes' segment marker, so no 'auth' fragment is ever required here.

    Pins the removal the same way AUTH_SURFACE membership is pinned (positive-membership
    tests); an ungated-dispatch test does not protect a hint-content invariant.
    """
    markers = _seam_route_markers(_read(wf_path), wf_path)
    assert markers, (
        f"{wf_path.name}: parsed SEAM_ROUTE_MARKERS is empty — the array shape changed; "
        "update _seam_route_markers."
    )
    offenders = [m for m in markers if "auth" in m.lower()]
    assert not offenders, (
        f"{wf_path.name}: SEAM_ROUTE_MARKERS contains auth-path fragment(s) {offenders!r} "
        "— RT-002: such a marker substring-matches AUTH_SURFACE members (e.g. '/oauth' "
        "matches src/auth/oauth_tokens), listing them under the seam prompt's route "
        "heading while sibling auth members fall through to the placeholder — the round-4 "
        "asymmetric mislabel. The OAuth route src/routes/oauth is already caught by the "
        "'routes' segment marker; drop the auth fragment."
    )


# ---------------------------------------------------------------------------
# RT-002 (round-7 fresh-lens): the seam prompt must pass the FULL wave.allScope.join()
# scope list, not only the derived seamPaths hint. For an AUTH_SURFACE-only wave seamPaths
# is empty (the prompt shows placeholder text), so the full scope list is the SOLE signal
# telling the seam agent which auth file changed — exactly the change class w036/GH-123
# exists to protect. The ungating tests above assert the seam task is DISPATCHED and check
# the marker/hint content, but none asserts the scope list reaches the prompt: a future
# edit dropping `wave.allScope.join` from the seam prompt would silently blind the seam
# audit for the auth-only case with the whole suite green. Pinned on both the initial and
# recheck seam pushes, across all four runners (three wave-cycle.js mirrors + sdk-wave.js).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_MIRRORS, ids=WAVE_CYCLE_MIRROR_IDS)
def test_rt002_seam_initial_prompt_passes_full_scope(wf_path: Path) -> None:
    """RT-002: the seam INITIAL prompt must include `wave.allScope.join(...)`. seamPaths is
    empty for an AUTH_SURFACE-only wave, so the full scope list is the only signal naming
    the changed auth file; without it the seam audit is blind to the exact change class it
    exists to protect."""
    block = _seam_initial_block(_read(wf_path), wf_path)
    seam_prompt = _text_from_anchor(
        block, _SEAM_INITIAL_PUSH_ANCHOR, wf_path, "the seam advisorTasks.push(...) call",
    )
    assert "wave.allScope.join" in seam_prompt, (
        f"{wf_path.name}: the seam initial prompt does not pass `wave.allScope.join(...)` — "
        "RT-002: seamPaths is empty for an AUTH_SURFACE-only wave, so the full scope list is "
        "the sole signal identifying the changed auth file; without it the seam audit is "
        "blind to exactly the change class it exists to protect."
    )


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_MIRRORS, ids=WAVE_CYCLE_MIRROR_IDS)
def test_rt002_seam_recheck_prompt_passes_full_scope(wf_path: Path) -> None:
    """RT-002: the seam RECHECK prompt (post-fix re-audit) must likewise include
    `wave.allScope.join(...)` — same auth-only blind spot as the initial seam prompt, on
    the recheck leg."""
    block = _seam_recheck_block(_read(wf_path), wf_path)
    seam_prompt = _text_from_anchor(
        block, _SEAM_RECHECK_PUSH_ANCHOR, wf_path, "the seam recheckTasks.push(...) call",
    )
    assert "wave.allScope.join" in seam_prompt, (
        f"{wf_path.name}: the seam recheck prompt does not pass `wave.allScope.join(...)` — "
        "RT-002: same auth-only blind spot as the initial seam prompt, on the recheck leg."
    )


# ---------------------------------------------------------------------------
# RT-001 (fix round, post-round-7): every SEAM_ROUTE_MARKERS test above is a static
# text-parse of the marker ARRAY CONTENTS (no-auth-fragment, full-scope-passed,
# ungated-dispatch) — none pins the matching ALGORITHM. The round-7 fix moved
# SEAM_ROUTE_MARKERS from leading-slash substring matching (`p.indexOf(m) !== -1`,
# where a leading '/' anchors only a segment's START, not its END — so '/mcp' still
# prefix-matched 'mcptools.py' and '/a2a' still matched 'pseudoa2a.py') to whole-path-
# segment matching (`p.split('/').some(seg => MARKERS.indexOf(seg.replace(ext,'')) !==
# -1)`). A regression back to the substring predicate — e.g. "simplifying" seamPaths to
# match the plain `X_SURFACE.some(pp => p.indexOf(pp) !== -1)` idiom used everywhere
# else in this file for A2A_SURFACE/MCP_SURFACE/AGUI_SURFACE/A2UI_SURFACE — would leave
# every marker-array-contents test above green while silently reopening the exact
# false-positive class round-7 closed. A disconnected Python re-implementation of the
# "correct" algorithm, asserted against markers parsed out of the file, CANNOT catch
# that regression (proven while building this test: reverting seamPaths to the old
# substring predicate left such a port green, because the port never inspects which
# algorithm the source actually uses). So this pins the algorithm SHAPE directly in the
# source text, then exercises representative paths through a port that is only
# meaningful once the shape assertions hold.
# ---------------------------------------------------------------------------

_SEAM_PATHS_FILTER_RE = re.compile(
    r"const seamPaths = wave\.allScope\.filter\(function\(p\) \{(.*?)\n  \}\)\n",
    re.DOTALL,
)


def _seam_paths_filter_body(content: str, wf_path: Path) -> str:
    match = _SEAM_PATHS_FILTER_RE.search(content)
    assert match is not None, (
        f"{wf_path.name}: could not locate the `const seamPaths = "
        "wave.allScope.filter(...)` statement."
    )
    return match.group(1)


def _seam_marker_matches(markers: list[str], path: str) -> bool:
    """Python port of: p.split('/').some(seg => MARKERS.indexOf(seg.replace(/\\.[^./]+$/, '')) !== -1)

    Only a faithful port once test_rt001_seam_paths_filter_matches_whole_segments_not_substrings
    (below) confirms the source actually implements this algorithm — see that test's
    docstring for why a disconnected port alone cannot pin the algorithm.
    """
    for seg in path.split("/"):
        stripped = re.sub(r"\.[^./]+$", "", seg)
        if stripped in markers:
            return True
    return False


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_MIRRORS, ids=WAVE_CYCLE_MIRROR_IDS)
def test_rt001_seam_paths_filter_matches_whole_segments_not_substrings(wf_path: Path) -> None:
    """RT-001 (fix round): pins the round-7 whole-segment-matching fix at the algorithm
    level. Asserts the seamPaths filter body (a) splits the path into segments and looks
    up an extension-stripped SEGMENT in SEAM_ROUTE_MARKERS, and (b) does not contain the
    original leading-slash substring predicate (SEAM_ROUTE_MARKERS.some(m => p.indexOf(m)
    !== -1)) that round-7 replaced.
    """
    body = _seam_paths_filter_body(_read(wf_path), wf_path)
    assert "p.split('/')" in body, (
        f"{wf_path.name}: the seamPaths filter no longer splits the path into segments "
        "(p.split('/')) — RT-001: without per-segment matching, SEAM_ROUTE_MARKERS falls "
        "back to substring matching against the RAW path, reopening the leading-slash "
        "false-positive class ('/mcp' matching 'mcptools.py', '/a2a' matching "
        "'pseudoa2a.py')."
    )
    assert re.search(r"SEAM_ROUTE_MARKERS\.indexOf\(seg\.replace\(", body), (
        f"{wf_path.name}: the seamPaths filter no longer looks up the extension-stripped "
        "SEGMENT in SEAM_ROUTE_MARKERS.indexOf(...) — RT-001: matching markers against "
        "anything other than a whole, extension-stripped path segment reopens the "
        "false-positive/negative class this fix closed."
    )
    assert not re.search(r"SEAM_ROUTE_MARKERS\.some\(function\(m\)\s*\{\s*return p\.indexOf\(m\)", body), (
        f"{wf_path.name}: the seamPaths filter has regressed to the original leading-slash "
        "substring predicate (SEAM_ROUTE_MARKERS.some(m => p.indexOf(m) !== -1)) — RT-001: "
        "a leading slash anchors a marker's START but not its END, so '/mcp' prefix-matches "
        "'mcptools.py' and '/a2a' matches 'pseudoa2a.py'."
    )


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_MIRRORS, ids=WAVE_CYCLE_MIRROR_IDS)
def test_rt001_seam_route_markers_use_whole_segment_matching(wf_path: Path) -> None:
    """RT-001 (fix round): behavioral companion to the structural test above — exercises
    representative paths through the algorithm the structural test just confirmed is
    live, documenting the intended semantics (route files caught via 'routes', the
    intentional non-route 'a2a'/'a2ui' shared-surface matches, the false positives
    round-7 eliminated) as concrete cases.
    """
    markers = _seam_route_markers(_read(wf_path), wf_path)
    cases: list[tuple[str, bool]] = [
        # Genuine route file, under src/routes/ — caught by the 'routes' segment.
        ("src/routes/mcptools.py", True),
        # NOT under routes/ and not the 'mcp' segment itself — substring matching
        # against a leading-slash '/mcp' marker used to catch this; segment matching
        # must not.
        ("src/tools/mcpthing.py", False),
        # NOT under routes/ and not the 'a2a' segment itself — substring matching
        # against a leading-slash '/a2a' marker used to catch this; segment matching
        # must not.
        ("src/utils/pseudoa2a.py", False),
        # Intentional non-route shared-surface match: the 'a2a' segment exactly.
        ("src/models/a2a.py", True),
        # Genuine route, 'a2a' segment exactly.
        ("src/routes/a2a.py", True),
        # Genuine OAuth route, caught via the 'routes' segment (no 'oauth' marker
        # needed — RT-002 regression guard above).
        ("src/routes/oauth.py", True),
        # AUTH_SURFACE credential store, not a route — must stay excluded (RT-002).
        ("src/auth/oauth_tokens.py", False),
    ]
    for path, expected in cases:
        actual = _seam_marker_matches(markers, path)
        assert actual == expected, (
            f"{wf_path.name}: seam-marker match for {path!r} was {actual}, expected "
            f"{expected} — RT-001: SEAM_ROUTE_MARKERS must use whole-path-segment "
            "matching, not substring matching, or this false-positive/negative class "
            "(mcptools.py / pseudoa2a.py) reopens silently."
        )


# ---------------------------------------------------------------------------
# RT-001 (fix wave, post-w036/GH-123): the two structural seam-ungating tests above
# are parametrized over WAVE_CYCLE_MIRRORS ONLY — _existing_wf_files's own comment
# says sdk-wave.js "never had the SEAM_ROUTE_MARKERS gating bug ... so it is out of
# scope for that test". True for the ORIGINAL gating bug, but that leaves the generic
# "wrap the push in an if" regression completely unguarded on sdk-wave.js: its
# unconditional seam push (`advisorTasks.push(...)` containing 'proto:seam', ~line 807)
# and recheck push (`recheckTasks.push(...)` containing 'proto:recheck:seam', ~line 915)
# carry zero regression coverage, so a future edit wrapping either in a conditional
# would pass CI undetected. sdk-wave.js has no SEAM_ROUTE_MARKERS/seamPaths of its own
# (it was never gated on a derived subset), so the wave-cycle.js block matcher above
# (anchored on `const SEAM_ROUTE_MARKERS`) cannot locate its seam block. These use an
# sdk-wave-appropriate sibling anchor instead: `const advisorTasks = []` / `const
# recheckTasks = []`, the first statements in their respective blocks, which run
# whenever the seam push itself can run.
# ---------------------------------------------------------------------------

_SDK_WAVE_SEAM_INITIAL_BLOCK_RE = re.compile(
    r"const advisorTasks = \[\].*?const protoResults = \(await parallel\(advisorTasks\)\)",
    re.DOTALL,
)

_SDK_WAVE_SEAM_RECHECK_BLOCK_RE = re.compile(
    r"const recheckTasks = \[\].*?const recheckResults = \(await parallel\(recheckTasks\)\)",
    re.DOTALL,
)


def _sdk_wave_seam_initial_block(content: str) -> str:
    match = _SDK_WAVE_SEAM_INITIAL_BLOCK_RE.search(content)
    assert match, (
        "sdk-wave.js: could not locate the seam-check block "
        "(const advisorTasks = [] ... const protoResults = ...)."
    )
    return match.group(0)


def _sdk_wave_seam_recheck_block(content: str) -> str:
    match = _SDK_WAVE_SEAM_RECHECK_BLOCK_RE.search(content)
    assert match, (
        "sdk-wave.js: could not locate the seam-recheck block "
        "(const recheckTasks = [] ... const recheckResults = ...)."
    )
    return match.group(0)


# RT-003 (fix round, on THIS finding): `_text_before_anchor`'s whole-block prefix (used
# unmodified by the wave-cycle.js seam tests above) works there because their block
# starts right at the seam-only `SEAM_ROUTE_MARKERS`/`seamPaths` declaration, with
# nothing else preceding the push. sdk-wave.js's seam pushes instead sit after several
# legitimate sibling `if (runA2A) { ... }` / `if (runMCP) { ... }` / `if (runAGUI) { ... }`
# / `if (runA2UI) { ... }` blocks in the SAME block — sdk-wave.js has no seam-only
# declaration to start from — so a literal "if (" not in prefix" check would false-fail
# on those pre-existing, unrelated conditionals. Narrow the window instead: find the last
# standalone closing brace at the anchor's own indentation (the end of the nearest
# preceding sibling statement, whether or not a blank line separates it from the push —
# the recheck block has none) and check only the text after it. A new wrapper around the
# push, spelled any way and indented any way, must appear in that window with no sibling
# text to hide behind.
def _immediate_prefix_before_anchor(
    block: str, anchor_pattern: str, indent: int, wf_path: Path, label: str
) -> str:
    prefix = _text_before_anchor(block, anchor_pattern, wf_path, label)
    sibling_close_re = re.compile(r"^" + " " * indent + r"\}\s*$", re.MULTILINE)
    matches = list(sibling_close_re.finditer(prefix))
    if not matches:
        return prefix
    return prefix[matches[-1].end():]


def test_rt001_sdk_wave_seam_task_not_gated_on_seam_route_markers() -> None:
    """RT-001 (fix wave): structural counterpart of
    test_rt001_seam_task_not_gated_on_seam_route_markers, for sdk-wave.js. Verifies the
    seam advisorTasks.push(...) call sits at the same indentation as the unconditional
    `const advisorTasks = []` sibling statement — any `if (...) {` wrapper, spelled any
    way, adds an indent level and fails this check regardless of the guard's syntax.
    """
    content = _read(SDK_WAVE)
    block = _sdk_wave_seam_initial_block(content)
    assert "proto:seam" in block, (
        "sdk-wave.js: the seam-check block does not contain the proto:seam agent() call."
    )
    seam_push_indent = _leading_indent(
        block, r"advisorTasks\.push\(function\(\) \{.{0,160}?Cross-protocol seam audit",
        SDK_WAVE, "the seam advisorTasks.push(...) call",
    )
    # Searched against the FULL file content, not `block` — `block` itself starts at
    # `const advisorTasks = []`, so matching that same anchor within `block` would find
    # it at string-offset 0 with its leading whitespace already stripped off by the
    # block-start match, always reporting indent 0. Same technique the wave-cycle.js
    # recheck test above uses for `const recheckTasks = []`.
    advisor_tasks_const_indent = _leading_indent(
        content, r"const advisorTasks = \[\]",
        SDK_WAVE, "the unconditional `const advisorTasks = []` statement",
    )
    assert seam_push_indent == advisor_tasks_const_indent, (
        f"sdk-wave.js: the seam advisorTasks.push(...) is indented {seam_push_indent} "
        f"spaces but the unconditional `const advisorTasks = []` sibling statement in "
        f"the same block is indented {advisor_tasks_const_indent} spaces — a deeper "
        "indent means the push has been wrapped in a NEW conditional guard, "
        "reintroducing a seam-skip bug on this runner."
    )
    # RT-003 (fix round): indentation parity is defeated by a non-indented conditional
    # body — this file's own `if (runA2A) { ... }` / `if (runMCP) { ... }` siblings keep
    # their whole body at the SAME indent as the `if (` line, so a matching
    # `if (!seamPaths.length) { advisorTasks.push(...) }` wrapper would pass the
    # indentation check above too. Assert no `if (` conditional immediately precedes the
    # seam push (i.e. appears after the nearest preceding sibling's closing brace) —
    # the syntax- and indent-independent signal that no wrapper guards it.
    seam_push_prefix = _immediate_prefix_before_anchor(
        block, r"advisorTasks\.push\(function\(\) \{.{0,160}?Cross-protocol seam audit",
        seam_push_indent, SDK_WAVE, "the seam advisorTasks.push(...) call",
    )
    assert "if (" not in seam_push_prefix, (
        "sdk-wave.js: an `if (` conditional immediately precedes the seam "
        "advisorTasks.push(...) call — RT-003: the push has been wrapped in a guard. "
        "Indentation parity alone does not catch a wrapper using this file's existing "
        "non-indented `if (runA2A) { ... }`-style body convention; the seam push must "
        "not be wrapped in any conditional."
    )


def test_rt001_sdk_wave_seam_recheck_task_not_gated_on_seam_paths() -> None:
    """RT-001 (fix wave), recheck-path counterpart of
    test_rt001_sdk_wave_seam_task_not_gated_on_seam_route_markers — same coverage gap,
    same fix, on sdk-wave.js's `proto:recheck:seam` dispatch.
    """
    content = _read(SDK_WAVE)
    block = _sdk_wave_seam_recheck_block(content)
    assert "proto:recheck:seam" in block, (
        "sdk-wave.js: the seam-recheck block does not contain the proto:recheck:seam "
        "agent() call."
    )
    recheck_push_indent = _leading_indent(
        block, r"recheckTasks\.push\(function\(\) \{.{0,160}?Cross-protocol seam re-audit",
        SDK_WAVE, "the seam recheckTasks.push(...) call",
    )
    # Full content, not `block` — same reason as the initial-dispatch counterpart above:
    # `block` starts at `const recheckTasks = []` itself, so its leading indent would be
    # stripped by the block-start match and always read back as 0.
    recheck_tasks_const_indent = _leading_indent(
        content, r"const recheckTasks = \[\]",
        SDK_WAVE, "the unconditional `const recheckTasks = []` statement",
    )
    assert recheck_push_indent == recheck_tasks_const_indent, (
        f"sdk-wave.js: the seam recheckTasks.push(...) is indented {recheck_push_indent} "
        f"spaces but the unconditional `const recheckTasks = []` sibling statement is "
        f"indented {recheck_tasks_const_indent} spaces — a deeper indent means the "
        "recheck push has been wrapped in a NEW conditional guard, reintroducing a "
        "seam-recheck-skip bug on this runner."
    )
    # RT-003 (fix round): the recheck block's sibling `if (runA2A) { ... }` /
    # `if (runMCP) { ... }` / etc. blocks keep their whole body at the SAME indent as the
    # `if (` line, with no blank line separating them — a matching non-indented
    # `if (!seamPaths.length) { recheckTasks.push(...) }` wrapper right before the push
    # would pass the indentation-parity check above too. Assert no `if (` conditional
    # immediately precedes the recheck push (i.e. appears after the nearest preceding
    # sibling's closing brace) — the syntax- and indent-independent signal that no
    # wrapper guards it.
    recheck_push_prefix = _immediate_prefix_before_anchor(
        block, r"recheckTasks\.push\(function\(\) \{.{0,160}?Cross-protocol seam re-audit",
        recheck_push_indent, SDK_WAVE, "the seam recheckTasks.push(...) call",
    )
    assert "if (" not in recheck_push_prefix, (
        "sdk-wave.js: an `if (` conditional immediately precedes the seam "
        "recheckTasks.push(...) call — RT-003: the recheck push has been wrapped in a "
        "guard. Indentation parity alone does not catch a wrapper using this file's "
        "existing non-indented `if (runA2A) { ... }`-style body convention; the recheck "
        "push must not be wrapped in any conditional."
    )


def test_rt002_sdk_wave_seam_initial_prompt_passes_full_scope() -> None:
    """RT-002 (round-7): sdk-wave.js counterpart — the seam INITIAL prompt must include
    `wave.allScope.join(...)`. sdk-wave.js has no seamPaths hint at all, so the full scope
    list is the ONLY thing the seam agent receives; dropping it blinds the audit entirely.
    Sliced from the seam anchor so the per-protocol pushes that precede it in the same block
    (whose `wave.allScope.filter(...)` file lists are a different signal) cannot mask a
    seam-prompt regression."""
    block = _sdk_wave_seam_initial_block(_read(SDK_WAVE))
    seam_prompt = _text_from_anchor(
        block, _SEAM_INITIAL_PUSH_ANCHOR, SDK_WAVE, "the seam advisorTasks.push(...) call",
    )
    assert "wave.allScope.join" in seam_prompt, (
        "sdk-wave.js: the seam initial prompt does not pass `wave.allScope.join(...)` — "
        "RT-002: with no seamPaths hint on this runner, the full scope list is the only "
        "signal the seam agent gets; without it the seam audit is blind."
    )


def test_rt002_sdk_wave_seam_recheck_prompt_passes_full_scope() -> None:
    """RT-002 (round-7): sdk-wave.js counterpart for the seam RECHECK prompt. Sliced from
    the seam recheck anchor so the per-protocol recheck pushes that precede it — which also
    carry `wave.allScope.join` — cannot mask a seam-recheck-prompt regression."""
    block = _sdk_wave_seam_recheck_block(_read(SDK_WAVE))
    seam_prompt = _text_from_anchor(
        block, _SEAM_RECHECK_PUSH_ANCHOR, SDK_WAVE, "the seam recheckTasks.push(...) call",
    )
    assert "wave.allScope.join" in seam_prompt, (
        "sdk-wave.js: the seam recheck prompt does not pass `wave.allScope.join(...)` — "
        "RT-002: same blind spot as the initial seam prompt, on the recheck leg."
    )


# ---------------------------------------------------------------------------
# RT-002 (this wave): sdk-wave.js's AUTH_SURFACE lists two SDK-internal
# credential-verification backends beyond the routes/oauth + auth/middleware pair —
# pin them so they cannot be silently deleted.
# ---------------------------------------------------------------------------

SDK_WAVE_AUTH_INTERNAL_MEMBERS = [
    "agent_sdk/auth/oauth_tokens",
    "agent_sdk/auth/api_keys",
    # RT-003 (round 5): both verify() backends above `from .identity import Identity` and
    # return an Identity — the object require_identity yields to every protected route.
    # Same "trace transitive require_identity consumers" rule that added the two members
    # above.
    "agent_sdk/auth/identity",
]


@pytest.mark.parametrize("member_path", SDK_WAVE_AUTH_INTERNAL_MEMBERS)
def test_rt002_sdk_wave_auth_surface_includes_sdk_internal_verifiers(member_path: str) -> None:
    """RT-002: sdk-wave.js's AUTH_SURFACE traces the transitive require_identity
    consumers middleware.py delegates to — OAuthTokenStore.verify
    (agent_sdk/auth/oauth_tokens.py) and ApiKeyStore.verify (agent_sdk/auth/api_keys.py) —
    beyond the routes/oauth + auth/middleware pair wave-cycle.js's AUTH_SURFACE shares
    with it (the round-2 'trace all transitive require_identity consumers' finding).
    Nothing previously pinned this, so it could be silently deleted with no CI failure.
    Locks membership the same way test_lrn132_oauth_present_in_all_three_protocol_surfaces
    locks oauth's. As of RT-001 (round-4 fresh-lens) wave-cycle.js mirrors these two as
    well, at full parity — see test_rt001_wave_cycle_auth_surface_at_parity_with_sdk_wave
    (each runner keeps its own path dialect: agent_sdk/auth/* here, src/auth/* there).
    RT-003 (round 5) adds agent_sdk/auth/identity to this same list — the dataclass both
    verify() backends return, one hop further down the same transitive chain.
    """
    content = _read(SDK_WAVE)
    for surface_name in ("A2A_SURFACE", "MCP_SURFACE", "AGUI_SURFACE"):
        body = _surface_array_body(content, surface_name, SDK_WAVE)
        assert member_path in body, (
            f"sdk-wave.js: {surface_name} does not include {member_path!r} — RT-002: "
            "this SDK-internal credential-verification module backs require_identity "
            "for A2A, AG-UI, and MCP routes alike, so it must remain in all three "
            "protocol-surface arrays."
        )


# ---------------------------------------------------------------------------
# RT-001 (round-4 fresh-lens): AUTH_SURFACE parity across runners. The prior 2-vs-4
# divergence was defended by a "no equivalent file in a downstream agent's src/ tree"
# comment that is factually false — the standard agent src/ tree ships NEITHER src/auth/
# NOR src/routes/ (only src/tools, src/sources, src/artifacts, src/skills), so
# src/routes/oauth and src/auth/middleware are as absent downstream as
# oauth_tokens/api_keys; the criterion never distinguished the KEPT members from the
# DROPPED ones. wave-cycle.js now mirrors all four members (over-triggering the protocol
# audit is fail-safe; under-triggering reopens the GH-123/LRN-132 blind spot). This pins
# that parity so a future edit cannot silently re-narrow it back to the unsound split.
# The old test here (test_rt002_wave_cycle_auth_surface_comment_documents_omission)
# asserted the comment documented an "intentional" omission — it pinned the unsound
# rationale into CI, blocking correction. Replaced by the parity assertion below.
# ---------------------------------------------------------------------------

WAVE_CYCLE_AUTH_SURFACE_MEMBERS = [
    "src/routes/oauth",
    "src/auth/middleware",
    "src/auth/oauth_tokens",
    "src/auth/api_keys",
    # RT-003 (round 5): src/auth/identity — the dataclass both verify() backends above
    # return, one hop further down the same "trace transitive require_identity
    # consumers" chain. Mirrors SDK_WAVE_AUTH_INTERNAL_MEMBERS's agent_sdk/auth/identity.
    "src/auth/identity",
]


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_MIRRORS, ids=WAVE_CYCLE_MIRROR_IDS)
def test_rt001_wave_cycle_auth_surface_at_parity_with_sdk_wave(wf_path: Path) -> None:
    """RT-001 (round-4 fresh-lens): wave-cycle.js's AUTH_SURFACE must carry all four
    members of sdk-wave.js's auth surface — routes/oauth, auth/middleware, and the two
    credential-verification backends auth/oauth_tokens + auth/api_keys — each folded into
    A2A_SURFACE, MCP_SURFACE, and AGUI_SURFACE (via `.concat(AUTH_SURFACE)`).
    RT-003 (round 5) extends this same list/assertion to a fifth member, src/auth/identity.

    The prior 2-member list dropped oauth_tokens/api_keys on the rationale that they were
    "SDK internals with no equivalent file in a downstream agent's src/ tree". That
    criterion is false: the standard agent src/ tree ships NEITHER src/auth/ NOR
    src/routes/ (only src/tools, src/sources, src/artifacts, src/skills), so the two KEPT
    members were equally absent downstream — the split never had a distinguishing basis,
    yet the old test pinned the comment documenting it, locking the unsound rationale into
    CI. A downstream agent that overrides its credential store at src/auth/oauth_tokens.py
    must dispatch the protocol advisors; over-triggering the audit is fail-safe,
    under-triggering reopens the GH-123/LRN-132 blind spot. Parity removes the asymmetry
    rather than defending it. (sdk-wave.js's own four members are pinned by
    test_rt002_sdk_wave_auth_surface_includes_sdk_internal_verifiers.)
    """
    content = _read(wf_path)
    for member_path in WAVE_CYCLE_AUTH_SURFACE_MEMBERS:
        for surface_name in ("A2A_SURFACE", "MCP_SURFACE", "AGUI_SURFACE"):
            body = _surface_array_body(content, surface_name, wf_path)
            assert member_path in body, (
                f"{wf_path.name}: {surface_name} does not include {member_path!r} — "
                "RT-001 (round-4): wave-cycle.js's AUTH_SURFACE must be at full parity "
                "with sdk-wave.js (all four auth members folded into every protocol "
                "surface), not the unsound 2-member split."
            )


# ---------------------------------------------------------------------------
# RT-001 (fix round, redteam finding on this test module): the two membership tests
# above each check ONE runner's real AUTH_SURFACE array against a hand-maintained
# constant list local to that same test — SDK_WAVE_AUTH_INTERNAL_MEMBERS for sdk-wave.js,
# WAVE_CYCLE_AUTH_SURFACE_MEMBERS for wave-cycle.js — and the two lists are never
# cross-checked against each other. An asymmetric edit (e.g. a 6th AUTH_SURFACE member —
# one more transitive require_identity consumer, the "trace one more hop" pattern this
# wave already repeated three times: middleware -> oauth_tokens/api_keys -> identity —
# landed in only one runner's real array) leaves both tests green as long as each
# runner's own hardcoded list is edited in step with its own array, even if the OTHER
# runner's array and list are left untouched. The test below closes that gap: it parses
# AUTH_SURFACE directly out of both sdk-wave.js and each wave-cycle.js mirror (no
# hardcoded membership list on either side), normalizes away the agent_sdk/ <-> src/
# path-prefix dialect, and asserts set-equality, so any asymmetric add or remove between
# the two runners' actual source fails CI regardless of whether either hardcoded test
# list above was kept in sync. The membership tests above remain as a floor pinning the
# known-good members explicitly.
# ---------------------------------------------------------------------------


def _auth_surface_members(content: str, wf_path: Path) -> list[str]:
    match = re.search(r"const AUTH_SURFACE\s*=\s*\[(.*?)\]", content, re.DOTALL)
    assert match is not None, f"{wf_path.name}: could not find `const AUTH_SURFACE = [...]` array"
    return re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))


def _normalize_auth_surface_dialect(members: list[str]) -> set[str]:
    normalized = set()
    for member in members:
        for prefix in ("agent_sdk/", "src/"):
            if member.startswith(prefix):
                normalized.add(member[len(prefix) :])
                break
        else:
            normalized.add(member)
    return normalized


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_MIRRORS, ids=WAVE_CYCLE_MIRROR_IDS)
def test_rt001_wave_cycle_auth_surface_parsed_set_equality_with_sdk_wave(
    wf_path: Path,
) -> None:
    """RT-001 (fix round): parses AUTH_SURFACE directly out of sdk-wave.js and this
    wave-cycle.js mirror (rather than checking each side against its own hardcoded
    membership-test constant) and asserts set-equality after normalizing the
    agent_sdk/ <-> src/ path-prefix dialect. Guards the actual cross-runner parity that
    test_rt001_wave_cycle_auth_surface_at_parity_with_sdk_wave and
    test_rt002_sdk_wave_auth_surface_includes_sdk_internal_verifiers only guard
    indirectly (each against its own hand-maintained list, never against each other).
    """
    sdk_wave_members = _normalize_auth_surface_dialect(
        _auth_surface_members(_read(SDK_WAVE), SDK_WAVE)
    )
    wave_cycle_members = _normalize_auth_surface_dialect(
        _auth_surface_members(_read(wf_path), wf_path)
    )
    assert sdk_wave_members == wave_cycle_members, (
        f"{wf_path.name}: AUTH_SURFACE (normalized) is {sorted(wave_cycle_members)} but "
        f"sdk-wave.js's AUTH_SURFACE (normalized) is {sorted(sdk_wave_members)} — RT-001 "
        "(fix round): the two runners' AUTH_SURFACE arrays have drifted out of parity. "
        f"Only in sdk-wave.js: {sorted(sdk_wave_members - wave_cycle_members)}. Only in "
        f"{wf_path.name}: {sorted(wave_cycle_members - sdk_wave_members)}."
    )


# ---------------------------------------------------------------------------
# RT-003 (round-6 fresh-lens): every test above is a static text-parse over the
# .js source (array membership, prompt wording, indentation parity). None EXECUTES
# the GH-123/LRN-132 fix, which is a RUNTIME predicate:
#
#     const runA2A = wave.allScope.some(p => A2A_SURFACE.some(pp => p.indexOf(pp) !== -1))
#
# folded over `A2A_SURFACE = [...].concat(AUTH_SURFACE)` (and the MCP/AG-UI/A2UI
# equivalents). A defect in the `.concat(AUTH_SURFACE)` fold or the `indexOf`
# membership test would leave every membership assertion green while silently
# reopening the exact LRN-132 blind spot this wave exists to close — an auth-only
# wave dispatching no protocol advisor. These tests port the predicate faithfully
# (`p.indexOf(pp) !== -1` is exactly `pp in p`) and run it against representative
# scopes, pinned against the arrays parsed LIVE out of each runner via
# _surface_array_body (which expands `.concat`), so removing AUTH_SURFACE from any
# protocol array's fold — or breaking the predicate — fails here, not just in prod.
# ---------------------------------------------------------------------------

# (wf_path, path-dialect prefix, id). sdk-wave.js addresses agent_sdk/...,
# the wave-cycle.js copies src/...; filtered to runners present on disk (the
# template mirror lives under the gitignored nested peer repo — may be absent).
_DISPATCH_RUNNER_CASES = [
    (SDK_WAVE, "agent_sdk", "sdk-wave.js"),
    (WAVE_CYCLE_RUNTIME, "src", "wave-cycle.js(runtime)"),
    (HARNESS_WAVE_CYCLE, "src", "wave-cycle.js(harness)"),
    (TEMPLATE_WAVE_CYCLE, "src", "wave-cycle.js(template)"),
]
DISPATCH_RUNNERS = [(p, pre) for p, pre, _ in _DISPATCH_RUNNER_CASES if p.exists()]
DISPATCH_RUNNER_IDS = [i for p, _, i in _DISPATCH_RUNNER_CASES if p.exists()]


def _surface_members(content: str, name: str, wf_path: Path) -> list[str]:
    """Parse the quoted string fragments of a surface array (with `.concat`
    expansion) into a list — the members the runtime predicate scans."""
    body = _surface_array_body(content, name, wf_path)
    return re.findall(r"'([^']*)'", body)


def _dispatch_flags(content: str, wf_path: Path, scope: list[str]) -> dict[str, bool]:
    """Faithful Python port of the workflow's protocol-surface detection:

        runX = wave.allScope.some(p => X_SURFACE.some(pp => p.indexOf(pp) !== -1))

    `p.indexOf(pp) !== -1` is exactly `pp in p` (the surface fragment is a substring
    of the scope path). runProtocol = runA2A || runMCP || runAGUI || runA2UI, and the
    seam leg is pushed unconditionally inside `if (runProtocol)` in every runner, so
    seamDispatched == runProtocol.
    """
    def run(name: str) -> bool:
        members = _surface_members(content, name, wf_path)
        return any(any(pp in p for pp in members) for p in scope)

    run_a2a = run("A2A_SURFACE")
    run_mcp = run("MCP_SURFACE")
    run_agui = run("AGUI_SURFACE")
    run_a2ui = run("A2UI_SURFACE")
    return {
        "runA2A": run_a2a,
        "runMCP": run_mcp,
        "runAGUI": run_agui,
        "runA2UI": run_a2ui,
        "seamDispatched": run_a2a or run_mcp or run_agui or run_a2ui,
    }


@pytest.mark.parametrize("wf_path,prefix", DISPATCH_RUNNERS, ids=DISPATCH_RUNNER_IDS)
def test_rt003_surface_detection_predicate_runtime_dispatch(wf_path: Path, prefix: str) -> None:
    """RT-003 (round-6 fresh-lens): execute the surface-detection predicate end-to-end
    against representative scopes and assert the resulting
    {runA2A, runMCP, runAGUI, runA2UI, seamDispatched} set — the runtime behavior no
    other test in this module covers.

    The auth-only cases are the LRN-132 regression guard: middleware.py / oauth.py /
    identity.py are folded into A2A_SURFACE, MCP_SURFACE, and AGUI_SURFACE via
    `.concat(AUTH_SURFACE)`, so a wave touching only one of them must dispatch all three
    per-protocol advisors AND the seam leg. Drop AUTH_SURFACE from any protocol array's
    fold (or break the `indexOf` predicate) and these flip to False here — failing CI
    instead of silently shipping the blind spot.
    """
    content = _read(wf_path)
    auth_all_three = {
        "runA2A": True, "runMCP": True, "runAGUI": True,
        "runA2UI": False, "seamDispatched": True,
    }
    cases: list[tuple[list[str], dict[str, bool]]] = [
        # Auth surfaces — folded into all three transport arrays, not A2UI. (LRN-132 guard.)
        ([f"{prefix}/auth/middleware.py"], auth_all_three),   # DEFINES require_identity
        ([f"{prefix}/routes/oauth.py"], auth_all_three),      # backs require_identity
        ([f"{prefix}/auth/identity.py"], auth_all_three),     # Identity yielded to every route
        # MCP route only — matches MCP_SURFACE's own routes/mcp, no other array. Proves the
        # AUTH fold does NOT over-trigger A2A/AG-UI for a non-auth single-protocol file.
        ([f"{prefix}/routes/mcp.py"],
         {"runA2A": False, "runMCP": True, "runAGUI": False, "runA2UI": False, "seamDispatched": True}),
        # A2UI surface only — A2UI_SURFACE deliberately omits AUTH_SURFACE, so ONLY runA2UI;
        # seam still fires because runProtocol is true.
        ([f"{prefix}/a2ui/catalog.py"],
         {"runA2A": False, "runMCP": False, "runAGUI": False, "runA2UI": True, "seamDispatched": True}),
        # Non-surface scope — no advisor, no seam (runProtocol false).
        ([f"{prefix}/tools/something.py"],
         {"runA2A": False, "runMCP": False, "runAGUI": False, "runA2UI": False, "seamDispatched": False}),
    ]
    for scope, expected in cases:
        actual = _dispatch_flags(content, wf_path, scope)
        assert actual == expected, (
            f"{wf_path.name}: surface-detection predicate over scope {scope} produced "
            f"{actual}, expected {expected} — the runtime protocol-advisor dispatch set is "
            "wrong. If the auth-only cases regressed to runA2A/runMCP/runAGUI=False, "
            "AUTH_SURFACE was dropped from a protocol array's `.concat` fold (the LRN-132 "
            "blind spot); if the A2UI case gained an auth advisor, AUTH_SURFACE was wrongly "
            "folded into A2UI_SURFACE."
        )
