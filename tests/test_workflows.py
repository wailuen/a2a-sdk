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

RT-007 (w036, post-archive follow-up — same double-blind-spot as the w035 finding above,
recurring on a different file class): a wave landed content changes to
.claude/agents/core/redteam.md, harness/agents/core/redteam.md, and
.claude/skills/wave/SKILL.md (a peerRepoAnnotations addition to the todos-redteam schema
and a severity-floor description update, both genuine deliverables of that wave's work) with
no todo declaring them in Creates:/Modifies: — so they were absent from wave.allScope
(evading offendingPaths) — while the harness-deliverable dir list watched only tests/,
workspace/learning/, workspace/scenarios/results/, workspace/prd/, .claude/workflows/, and
harness/workflows/ — not .claude/agents/, harness/agents/, or */skills/ (evading
offendingHarnessPaths too). Fix: .claude/agents/, harness/agents/, .claude/skills/, and
harness/skills/ were added to the harness-deliverable dir list (HARNESS_DIRS below, and the
matching schema description / prompt step 4 text in all four runners) — the new entries are
covered automatically by test_archive_intent_prompt_contains_harness_dirs and
test_archive_intent_schema_description_contains_harness_dirs below, which already iterate
every HARNESS_DIRS member. Separately, no test pinned
.claude/agents/core/redteam.md byte-identical to harness/agents/core/redteam.md (they
matched only by convention) — test_workflow_sync.py now parametrizes a byte-identity check
across every file shared by .claude/agents/core/ and harness/agents/core/.

RT-012 (post-archive gh-issues review, same double-blind-spot class, a fifth file class):
docs/content-types.md landed 64 net-new lines documenting the GH-130/RT-011 delimiter-safety
contract with no todo declaring it in Creates:/Modifies: (evading offendingPaths) while docs/
was outside the harness-deliverable dir list too (evading offendingHarnessPaths) — and, unlike
every prior variant of this recurring gap, also outside offendingUndeclaredImports (not a .py
file) AND offendingUndeclaredScope (not under agent_sdk/**.py), invisible to all four gate
clauses simultaneously. Fix: docs/ was added to HARNESS_DIRS below (and the matching schema
description / prompt step 4 text in all three archive-gate runners) — covered automatically
by the same two HARNESS_DIRS-iterating tests referenced in the RT-007 paragraph above.

RT-007 (pytest-gate blind spot, same class, a sixth variant): pyproject.toml's
`[tool.pytest.ini_options]` had two filterwarnings entries added that suppressed
PytestUnraisableExceptionWarning for any AF_UNIX socket or unclosed _UnixSelectorEventLoop —
broad enough to also mask a genuine agent_sdk-leaked loop or socket — with no todo declaring
pyproject.toml in Creates:/Modifies: (evading offendingPaths), and pyproject.toml outside
HARNESS_DIRS (evading offendingHarnessPaths), outside agent_sdk/**.py / src/**.py (evading
offendingUndeclaredScope), and not a .py file (evading offendingUndeclaredImports) —
invisible to all four gate clauses simultaneously. The suppression itself was replaced with a
root-cause fix (tests/conftest.py keeps one event loop installed for the session so
pytest-asyncio's per-test bookkeeping never fabricates a throwaway one to begin with — see
that fixture's docstring). Fix here: pyproject.toml was added to HARNESS_DIRS below, as a
single-file entry rather than a directory prefix (and the matching schema description /
prompt step 4 text in all three archive-gate runners) — covered automatically by the same two
HARNESS_DIRS-iterating tests referenced above.

These are static text-parse tests — they verify the schema and prompt text without
running the workflow engine.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
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
    # RT-012 (post-archive gh-issues review): docs/content-types.md landed 64 net-new lines
    # documenting the GH-130/RT-011 delimiter-safety contract with no todo declaring it in
    # Creates:/Modifies: — invisible to offendingPaths (undeclared), offendingHarnessPaths (docs/
    # was not a watched dir), offendingUndeclaredImports (not a .py file), AND
    # offendingUndeclaredScope (not under agent_sdk/**.py) simultaneously: a fifth variant of
    # the RT-003/RT-007 double-blind-spot class documented in the module docstring above.
    "docs/",
    "workspace/learning/",
    "workspace/scenarios/results/",
    "workspace/prd/",
    ".claude/workflows/",
    "harness/workflows/",
    # RT-007 (w036): the same evasion GH-84/w035 closed for workflow files (undeclared in
    # any todo's Creates:/Modifies: AND unwatched by this dir list, at once) recurred for
    # harness agent/skill files — see workspace/learning for the RT-007 LRN and the module
    # docstring above.
    ".claude/agents/",
    "harness/agents/",
    ".claude/skills/",
    "harness/skills/",
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
    # RT-007 (pytest-gate blind spot): pyproject.toml is a single top-level FILE, not a
    # directory — unlike every other entry above, "starts with" matching against it
    # degenerates to an exact match since a top-level file has no children. Added after a
    # pytest.ini_options edit there (two filterwarnings entries broad enough to mask a
    # genuine leaked event loop or AF_UNIX socket, landed with no todo declaring the file)
    # was found invisible to all four archive-gate clauses at once: not a harness dir
    # (offendingHarnessPaths), not under agent_sdk/**.py or src/**.py (offendingUndeclaredScope),
    # not a .py import target (offendingUndeclaredImports), and never named in a todo's
    # Creates:/Modifies: (offendingPaths) — a sixth variant of the double-blind-spot class
    # documented in the module docstring above.
    "pyproject.toml",
]

# RT-003: GH-118's import cross-check now covers both wave runners (see module docstring above)
GH118_FILES = [WAVE_CYCLE_RUNTIME, SDK_WAVE]

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


# RT-003 (fix round): offendingUndeclaredScope's watched-tree glob is dialect-specific,
# like OAUTH_SURFACE_CASES/MIDDLEWARE_SURFACE_CASES above — sdk-wave.js addresses
# agent_sdk/**.py (this SDK repo's own source root), wave-cycle.js addresses src/**.py (a
# downstream agent repo's source root). Reuses GH118_FILES' file set (sdk-wave.js,
# wave-cycle.js runtime only) — the byte-identical harness/workflows/wave-cycle.js mirror
# is covered by test_workflow_sync.py, not re-parametrized here, matching the rest of the
# RT-003 test section below.
UNDECLARED_SCOPE_DIALECT_CASES, UNDECLARED_SCOPE_DIALECT_IDS = _existing_wf_cases(
    [
        (SDK_WAVE, "agent_sdk"),
        (WAVE_CYCLE_RUNTIME, "src"),
    ],
    ["sdk-wave.js", "wave-cycle.js"],
)


# ---------------------------------------------------------------------------
# RT-001 (round-5 fresh-lens debug) — ARCHIVE-GATE SOURCE-ROOT DIALECT.
#
# Root cause of the round-1..5 stall: the dialect was hand-maintained as ~60
# separate `agent_sdk` literals inside prompt prose ported verbatim from
# sdk-wave.js, with no test forbidding the FOREIGN root. Each round re-dialected
# whichever field a reviewer happened to notice (round N: offendingUndeclaredScope,
# step 6) and the next round found another (round N+1: step 5's whole absolute-
# import resolver, plus the offendingUndeclaredImports schema description) — a fix
# loop that cannot converge because nothing fails the build on the literals nobody
# looked at yet.
#
# The archive gate's absolute-import half only resolves imports rooted at the
# repo's OWN source package. sdk-wave.js runs in the a2a-sdk repo (root
# `agent_sdk`); wave-cycle.js is, by its own wrongRunnerForRepoLayout hard-abort,
# the runner for downstream agent repos ONLY (root `src` —
# `from src.config import make_settings`), where `agent_sdk` is an installed
# third-party dependency the step tells the agent to ignore. An agent_sdk-rooted
# resolver there matched nothing, ever: the absolute half of the gate was a
# permanent no-op in every repo that runner can execute in, leaving the LRN-119
# ImportError-at-boot class open.
#
# ARCHIVE_GATE_DIALECT pins BOTH directions per runner — the required root's
# resolver forms present, the foreign root's resolver forms absent — across the
# ARCHIVE_INTENT_SCHEMA block AND the live prompt, so a future verbatim port
# fails the build on the first stray literal instead of on round 6 of a redteam.
# ---------------------------------------------------------------------------

ARCHIVE_GATE_DIALECT: dict[Path, dict[str, str]] = {
    SDK_WAVE: {
        "root": "agent_sdk",
        # worked-example tokens, in this runner's own tree
        "example_dir": "routes",  # a package dir under the source root
        "example_file": "a2a.py",  # a module inside it (the importing file)
        "example_pkg": "credentials",  # package holding the submodule example
        "example_mod": "forwarding",  # the submodule itself
        "example_kind": "route",  # what example_file is, in prose
    },
    WAVE_CYCLE_RUNTIME: {
        "root": "src",
        # the standard downstream agent src/ tree ships tools/sources/artifacts/
        # skills — never src/routes/ or src/credentials/ (see AUTH_SURFACE's comment
        # in either runner), so the worked examples are re-dialected too, not just
        # the root token.
        "example_dir": "tools",
        "example_file": "quote.py",
        "example_pkg": "sources",
        "example_mod": "pricing",
        "example_kind": "tool",
    },
}

ARCHIVE_GATE_DIALECT_CASES, ARCHIVE_GATE_DIALECT_IDS = _existing_wf_cases(
    [(wf, d["root"]) for wf, d in ARCHIVE_GATE_DIALECT.items()],
    ["sdk-wave.js", "wave-cycle.js"],
)


def _dialect(wf_path: Path) -> dict[str, str]:
    assert wf_path in ARCHIVE_GATE_DIALECT, (
        f"{wf_path.name}: no ARCHIVE_GATE_DIALECT entry — every runner carrying the "
        "archive gate must declare its source-root dialect here."
    )
    return ARCHIVE_GATE_DIALECT[wf_path]


def _foreign_root(wf_path: Path) -> str:
    """The OTHER runner's source root — the one that must never appear as a
    resolver form in this runner's archive gate."""
    roots = {d["root"] for d in ARCHIVE_GATE_DIALECT.values()}
    return (roots - {_dialect(wf_path)["root"]}).pop()


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


# RT-002 (this wave, LRN-060/LRN-131): the GH-132 unit/phase redteam loop logic
# (severity floor, debug-replaces-fix-fan-out, batched fix fan-out, LRN capture cap,
# agent-call budget backstop) was ported to sdk-wave.js in this same wave after landing
# in wave-cycle.js alone — the byte-identical wave-cycle.js sync guard never spanned
# sdk-wave.js, so the GH-132 tests below must be parametrized over sdk-wave.js too, not
# only the three wave-cycle.js mirrors.
GH132_LOOP_LOGIC_FILES, GH132_LOOP_LOGIC_IDS = _existing_wf_files(
    [SDK_WAVE, WAVE_CYCLE_RUNTIME, HARNESS_WAVE_CYCLE, TEMPLATE_WAVE_CYCLE],
    ["sdk-wave.js", "wave-cycle.js(runtime)", "wave-cycle.js(harness)", "wave-cycle.js(template)"],
)


# RT-002 (LRN-131, this wave): the RT-004 archive hard-block for a missing template/ checkout
# (ARCHIVE_INTENT_SCHEMA's templateDirExists field, the unconditional step-0 `test -d template`
# instruction, and the declaresTemplateScope hard-block) originally landed only in the three
# wave-cycle.js copies — the RT-004 tests below were parametrized over WAVE_CYCLE_MIRRORS alone,
# so sdk-wave.js (the runner .claude/skills/wave/SKILL.md step 2 actually launches) carried none
# of it and no test caught the gap. Same cross-runner-drift class as GH132_LOOP_LOGIC_FILES
# above (LRN-131): the byte-identical wave-cycle.js sync guard never spans sdk-wave.js. Fix: the
# gate was ported into sdk-wave.js verbatim, and every RT-004 test below is now parametrized
# over all four archive-gate runners, not only the three wave-cycle.js mirrors.
RT004_FILES, RT004_FILES_IDS = _existing_wf_files(
    [SDK_WAVE, WAVE_CYCLE_RUNTIME, HARNESS_WAVE_CYCLE, TEMPLATE_WAVE_CYCLE],
    ["sdk-wave.js", "wave-cycle.js(runtime)", "wave-cycle.js(harness)", "wave-cycle.js(template)"],
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


# wave-cycle.js behaviour (as opposed to sdk-wave.js prompt wording) is pinned by
# tests/test_wave_cycle_behaviour.py, which executes the script; wording tests below that
# use this helper apply to sdk-wave.js only.
def _sdk_wave_only(paths: list[Path], ids: list[str]) -> tuple[list[Path], list[str]]:
    keep = [(p, i) for p, i in zip(paths, ids) if p == SDK_WAVE]
    return [p for p, _ in keep], [i for _, i in keep]

def _read(path: Path) -> str:
    assert path.exists(), f"Workflow file not found: {path}"
    return path.read_text()


# RT-004: substring-anywhere assertions against the whole file pass even when the token
# lives only in a comment rather than the live archiveIntent agent() prompt or schema.
# These helpers anchor extraction to the actual prompt string / schema block so a gutted
# instruction with a lingering comment mention is caught.

_ARCHIVE_INTENT_PROMPT_RE = re.compile(
    r"const archiveIntent\s*=\s*await (?:callAgent|agent)\((.*?)"
    r"\{\s*schema:\s*ARCHIVE_INTENT_SCHEMA,\s*label:\s*'gate:archive-commit'",
    re.DOTALL,
)

_ARCHIVE_INTENT_SCHEMA_BLOCK_RE = re.compile(
    r"const ARCHIVE_INTENT_SCHEMA\s*=\s*\{.*?\n\}\n",
    re.DOTALL,
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


# ---------------------------------------------------------------------------
# Schema field presence: offendingHarnessPaths in ARCHIVE_INTENT_SCHEMA
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Agent prompt: step 4 instructs agent to populate offendingHarnessPaths
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# RT-002 (fix round): step 4b — `git -C template status --short` folding dirty
# template/.claude/workflows/ paths into offendingHarnessPaths — had zero regression
# tests pinning the actual mechanism in any runner. The two tests above only ever
# checked the generic HARNESS_DIRS membership, which happened to pass because the
# literal 'template/.claude/workflows/' substring also appears inside step 4b's prose;
# neither asserted the `git -C template status --short` command itself. These tests
# anchor directly to that mechanism, across all four archive-gate runners.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Dual blocking condition
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# RT-004 (GH-131/GH-132/LRN-071/LRN-085): steps 4/4b (and the RT-003 undeclared-scope step)
# only ever detect a DIRTY template/.claude/workflows/ mirror — they say nothing when
# template/ is not checked out in this working tree at all. GH-131 and GH-132 both declared
# template/.claude/workflows/wave-cycle.js as a deliverable in Modifies:, yet template/ is a
# gitignored peer repo (LRN-071) that can be entirely absent from a checkout — the only guards
# that would have caught the resulting silent-pass (test_workflow_sync.py's two
# xfail(strict=True) tests) never fail the suite; xfail is a test-report signal, not a
# propagation gate. These tests pin the hard pre-archive block that closes the gap:
# templateDirExists is determined unconditionally by the archive-commit gate agent, and a wave
# whose scope declares a template/ path hard-blocks archive (with its own distinct skip
# message) whenever it is false.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("wf_path", RT004_FILES, ids=RT004_FILES_IDS)
def test_rt004_archive_intent_schema_has_template_dir_exists_in_properties(wf_path: Path) -> None:
    """RT-004: ARCHIVE_INTENT_SCHEMA properties must define 'templateDirExists' as a boolean.
    Anchored to the schema block itself (not the whole file) so a comment mentioning the token
    elsewhere can't mask its removal from properties{}.
    """
    content = _read(wf_path)
    schema_block = _archive_intent_schema_block(content, wf_path)
    assert re.search(r"templateDirExists:\s*\{\s*type:\s*'boolean'", schema_block), (
        f"{wf_path.name}: 'templateDirExists' boolean property not found inside "
        "ARCHIVE_INTENT_SCHEMA.properties."
    )


_DECLARES_TEMPLATE_SCOPE_RE = re.compile(r"const declaresTemplateScope\s*=")


def _declares_template_scope_window(content: str, wf_path: Path) -> str:
    match = _DECLARES_TEMPLATE_SCOPE_RE.search(content)
    assert match, (
        f"{wf_path.name}: 'const declaresTemplateScope =' not found — the RT-004 hard-block "
        "check on wave.allScope is missing."
    )
    return _window_around(content, match.start(), match.end())


@pytest.mark.parametrize("wf_path", RT004_FILES, ids=RT004_FILES_IDS)
def test_rt004_declares_template_scope_hard_block_present(wf_path: Path) -> None:
    """RT-004: a wave whose scope (Creates: ∪ Modifies:) declares a template/ path must
    hard-block archive (protocolBlocked = true) whenever archiveIntent.templateDirExists is
    false. Anchored to the declaration site (not a substring-anywhere search) so a
    comment-only mention cannot pass this test.
    """
    content = _read(wf_path)
    window = _declares_template_scope_window(content, wf_path)
    for expected in [
        "startsWith('template/')",
        "archiveIntent.templateDirExists === false",
        "templatePropagationBlocked = true",
        "protocolBlocked = true",
    ]:
        assert expected in window, (
            f"{wf_path.name}: '{expected}' not found near the declaresTemplateScope hard-block "
            f"check — RT-004 gate may be incomplete. Window found: {window!r}"
        )


# ---------------------------------------------------------------------------
# RT-006 (round-7 fresh-lens debug): the archive-gate hard-block above is the LATE
# half of the template/ guard — it fires only after Implement/Redteam/Codify have
# already run and spent the wave's agent-call budget. The Parse-phase fast-abort is
# the half that saves that budget, and it had landed only in the wave-cycle.js
# mirrors, not in sdk-wave.js — the runner this repo actually uses, and the repo
# whose own open deliverable is a template/ propagation. Both halves must exist in
# every runner.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# GH-118 (LRN-119): schema field presence: offendingUndeclaredImports
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# GH-118 (LRN-119): agent prompt instructs the import cross-check
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "wf_path,dialect_root", ARCHIVE_GATE_DIALECT_CASES, ids=ARCHIVE_GATE_DIALECT_IDS
)
def test_rt001_archive_gate_carries_no_foreign_source_root(
    wf_path: Path, dialect_root: str
) -> None:
    """RT-001 (round-5 fresh-lens debug) — the convergence guard.

    Every absolute-import RESOLVER FORM in the archive gate (schema descriptions the
    agent receives + the live prompt) must be rooted at this runner's own source root,
    and the OTHER runner's root must never appear in resolver position. Without this
    negative half, re-dialecting is a per-literal chore no test verifies: rounds 1..5 of
    this fix loop each corrected the one field a reviewer noticed while ~60 other
    `agent_sdk` literals sat untouched in wave-cycle.js's step-5 prose, so the loop could
    not converge.

    Only RESOLVER forms are forbidden — a runner may still NAME the other root in prose
    (wave-cycle.js explicitly tells the agent that `agent_sdk` is an installed
    third-party dependency to ignore, and cites sdk-wave.js's dialect as provenance).
    """
    content = _read(wf_path)
    foreign = _foreign_root(wf_path)
    regions = {
        "ARCHIVE_INTENT_SCHEMA block": _archive_intent_schema_block(content, wf_path),
        "archiveIntent prompt": _archive_intent_prompt(content, wf_path),
    }
    forbidden = [
        f"import {foreign}.",
        f"from {foreign} import <name>",
        f"from {foreign}[",
        f"from {foreign}.",
        f"`{foreign}/<",
        f"rooted at `{foreign}`",
    ]
    for region_name, region in regions.items():
        for token in forbidden:
            assert token not in region, (
                f"{wf_path.name}: the {region_name} still contains the FOREIGN "
                f"source-root resolver form {token!r}. This runner resolves absolute "
                f"intra-package imports at `{dialect_root}`; a `{foreign}`-rooted "
                "resolver matches nothing in the tree this runner runs against, making "
                "the absolute half of the GH-118/LRN-119 gate a silent no-op."
            )


# ---------------------------------------------------------------------------
# RT-003 (w036, post-archive gh-issues review): schema field presence for
# offendingUndeclaredScope — a third blind spot, orthogonal to offendingPaths and
# offendingUndeclaredImports: a file that is TRACKED (already existed pre-wave, so the
# `git ls-files` check offendingUndeclaredImports relies on never flags it), modified
# mid-wave, named only inside a todo's Reuses:/SI: prose (never its own Creates:/Modifies:
# line, so it evades offendingPaths), and outside every harness deliverable dir (so it
# evades offendingHarnessPaths too). GH-135/GH-130 each hit this gap on tracked
# agent_sdk/**.py files (agent_sdk/routes/mcp.py, agent_sdk/routes/admin.py,
# agent_sdk/__init__.py, agent_sdk/common/redact.py). Reuses GH118_FILES: the same two
# runners (wave-cycle.js, sdk-wave.js) implement this archive-gate extension; the
# byte-identical harness/workflows/wave-cycle.js mirror is covered by
# test_workflow_sync.py, not re-parametrized here.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# RT-003 (w036): quadruple blocking condition
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# RT-003 (w036): agent prompt instructs the undeclared-scope check
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# RT-001: import cross-check must resolve RELATIVE intra-package imports too,
# not only absolute agent_sdk.* imports — relative imports are the dominant
# style in agent_sdk/routes/, including the canonical LRN-119 module.
# ---------------------------------------------------------------------------


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


# The resolver-ladder equivalence check across runners was retired: wave-cycle.js resolves
# imports with ast in ARCHIVE_GATE_PY (pinned by tests/test_wave_cycle_behaviour.py), not prose.

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
    # C-014 / GH-152: the OIDC relying-party client mints the user-bound identity.
    "agent_sdk/auth/oidc",
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
    "src/auth/oidc",
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


# ---------------------------------------------------------------------------
# GH-132: severity floor on the unit/phase redteam loop exit condition, batched
# fix fan-out, debug-replaces-fix-fan-out at round 4+/stall, a hard LRN-capture
# cap per wave, and a hard per-wave agent-call budget backstop.
#
# Root cause (independently re-verified against main's actual current code before
# this fix landed): the unit/phase redteam loops exited ONLY on
# `rt.findingsCount === 0` — every severity, including low. An adversarial
# reviewer reliably produces at least one low-severity finding, so the round cap
# (5 unit / 8 phase) was effectively always hit. The round-4+ debug fresh-lens
# escalation SUPPLEMENTED the per-file fix fan-out rather than replacing it,
# compounding agent cost every round debug fired.
# ---------------------------------------------------------------------------

_PHASE5_MARKER = "// ─── phase 5: protocol audit"
_PHASE6_MARKER = "// ─── phase 6: codify"
_PHASE7_MARKER = "// ─── phase 7: archive"
_HELPERS_MARKER = "// ─── helpers "
_STATE_MARKER = "// ─── state "


def _section(content: str, start_marker: str, end_marker: str, wf_path: Path) -> str:
    """Bounded slice of content between two section-header comments — anchors an
    assertion to the section it actually governs, the same anchoring discipline
    _archive_intent_prompt/_archive_intent_schema_block use above."""
    start = content.find(start_marker)
    assert start != -1, f"{wf_path.name}: could not locate section marker {start_marker!r}."
    end = content.find(end_marker, start + len(start_marker))
    assert end != -1 and end > start, (
        f"{wf_path.name}: could not locate section marker {end_marker!r} after {start_marker!r}."
    )
    return content[start:end]


def _helpers_section(content: str, wf_path: Path) -> str:
    return _section(content, _HELPERS_MARKER, _STATE_MARKER, wf_path)


def _codify_section(content: str, wf_path: Path) -> str:
    return _section(content, _PHASE6_MARKER, _PHASE7_MARKER, wf_path)


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_gh132_severity_floor_helpers_defined(wf_path: Path) -> None:
    """blockingFindings/nonBlockingFindings must PARTITION the finding list —
    medium/low never block, and everything else does.

    RT-005 (round-7 fresh-lens debug): this used to pin blockingFindings to an
    allow-list of 'critical'/'high'. Two allow-lists do not partition: a finding
    whose severity was absent, capitalised, or otherwise unexpected fell in
    neither set — it did not block, was never accumulated into the deferred note,
    and produced no log line. Only nonBlockingFindings may be an allow-list.
    """
    helpers = _helpers_section(_read(wf_path), wf_path)
    assert re.search(
        r"function isNonBlockingSeverity\(f\)\s*\{\s*"
        r"return f && \(f\.severity === 'medium' \|\| f\.severity === 'low'\)",
        helpers,
    ), f"{wf_path.name}: the non-blocking allow-list must be medium/low only."
    assert re.search(
        r"function nonBlockingFindings\(findings\)\s*\{\s*"
        r"return findings\.filter\(isNonBlockingSeverity\)",
        helpers,
    ), f"{wf_path.name}: nonBlockingFindings must be exactly the allow-list."
    blocking = re.search(
        r"function blockingFindings\(findings\)\s*\{(.*?)\n\}", helpers, re.S
    )
    assert blocking, f"{wf_path.name}: blockingFindings not found."
    body = blocking.group(1)
    assert "if (isNonBlockingSeverity(f)) return false" in body, (
        f"{wf_path.name}: blockingFindings must be the COMPLEMENT of "
        "nonBlockingFindings — it may only exclude findings the allow-list claims."
    )
    assert "return true" in body, (
        f"{wf_path.name}: blockingFindings must block everything the non-blocking "
        "allow-list does not claim (fail-closed on an unrecognised severity)."
    )
    assert "unrecognised severity" in body, (
        f"{wf_path.name}: an unrecognised severity must be named in a WARNING, not "
        "silently absorbed into the blocking set."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt005_unrecognised_severity_is_blocking(wf_path: Path) -> None:
    """Executable pin for the severity partition, run against the runner's own
    source: a finding with severity 'unknown' (or a missing severity) must land in
    blockingFindings and NOT in nonBlockingFindings, in all three runners.
    """
    helpers = _helpers_section(_read(wf_path), wf_path)
    src = re.search(
        r"(function isNonBlockingSeverity[\s\S]*?function nonBlockingFindings\(findings\)"
        r"\s*\{[\s\S]*?\n\})",
        helpers,
    )
    assert src, f"{wf_path.name}: severity helpers not found."
    if shutil.which("node") is None:
        pytest.skip("node not available — static shape is pinned by the test above")
    harness = (
        "var _warned = [];\n"
        "function log(m) { _warned.push(m) }\n"
        + src.group(1)
        + "\n"
        "var findings = ["
        "  {id:'A', severity:'critical'},"
        "  {id:'B', severity:'High'},"
        "  {id:'C', severity:'unknown'},"
        "  {id:'D'},"
        "  {id:'E', severity:'medium'},"
        "  {id:'F', severity:'low'}"
        "];\n"
        "console.log(JSON.stringify({"
        "  blocking: blockingFindings(findings).map(function(f){return f.id}),"
        "  nonBlocking: nonBlockingFindings(findings).map(function(f){return f.id}),"
        "  warned: _warned"
        "}));\n"
    )
    proc = subprocess.run(
        ["node", "-e", harness], capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, f"{wf_path.name}: node failed: {proc.stderr}"
    out = json.loads(proc.stdout)
    assert out["blocking"] == ["A", "B", "C", "D"], (
        f"{wf_path.name}: every finding that is not explicitly medium/low must "
        f"block — got {out['blocking']}"
    )
    assert out["nonBlocking"] == ["E", "F"], (
        f"{wf_path.name}: only explicit medium/low may be non-blocking — got "
        f"{out['nonBlocking']}"
    )
    assert len(out["warned"]) == 3, (
        f"{wf_path.name}: each unrecognised severity must produce its own WARNING "
        f"naming the finding — got {out['warned']}"
    )
    assert any("B" in w for w in out["warned"]), (
        f"{wf_path.name}: the WARNING must name the offending finding id."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_gh132_lrn_capture_capped_per_wave(wf_path: Path) -> None:
    content = _read(wf_path)
    assert re.search(r"const MAX_LRN_PER_WAVE = \d+", content), (
        f"{wf_path.name}: MAX_LRN_PER_WAVE constant missing."
    )
    codify = _codify_section(content, wf_path)
    assert "const lrnCandidates = toCodeify.slice(0, MAX_LRN_PER_WAVE)" in codify, (
        f"{wf_path.name}: LRN capture must be capped via toCodeify.slice(0, MAX_LRN_PER_WAVE)."
    )
    assert "if (lrnCandidates.length > 0) {" in codify, (
        f"{wf_path.name}: the LRN-write fan-out guard must check the CAPPED lrnCandidates "
        "list, not the full toCodeify list."
    )
    # The fan-out may dispatch one agent per finding, or batch findings per codify agent
    # (lrnAssignments/lrnBatches) — either way its input must be the CAPPED list.
    assert (
        "await parallel(lrnCandidates.map(function(f, i) {" in codify
        or (
            "const lrnAssignments = lrnCandidates.map(function(f, i) {" in codify
            and "await parallel(lrnBatches.map(function(batch) {" in codify
        )
    ), (
        f"{wf_path.name}: the parallel LRN-write fan-out must iterate the capped "
        "lrnCandidates list, not the full toCodeify list."
    )
    assert "toCodeify.map(" not in codify, (
        f"{wf_path.name}: no LRN-write fan-out may iterate the uncapped toCodeify list."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_gh132_agent_call_budget_backstop_present(wf_path: Path) -> None:
    """A hard per-wave agent-call ceiling that stops the wave LOUDLY (throws) when
    exceeded — every dispatched agent() call must route through it."""
    content = _read(wf_path)
    helpers = _helpers_section(content, wf_path)
    # RT-002: AGENT_CALL_BUDGET may be a bare literal or overridable via
    # normalizedArgs.agentBudget (see test_rt002_agent_call_budget_is_overridable, scoped to
    # wave-cycle.js runtime) — either way a numeric ceiling must be present.
    # RT-006: wave-cycle.js's copies declare it `let` (recomputed once wave.groups.length is
    # known — see test_rt006_agent_call_budget_recompute_scales_with_group_count in
    # test_rt_wave_cycle_budget_and_mismatch_fixes.py); sdk-wave.js is out of scope for that
    # fix and stays `const`. Either declaration keyword satisfies this presence check.
    assert re.search(
        r"(?:const|let) AGENT_CALL_BUDGET = (?:Number\(normalizedArgs\.agentBudget\)\s*\|\|\s*)?\d+",
        helpers,
    ), (
        f"{wf_path.name}: AGENT_CALL_BUDGET constant missing."
    )
    assert "async function callAgent(prompt, opts) {" in helpers, (
        f"{wf_path.name}: callAgent wrapper missing."
    )
    assert "agentCallCount > AGENT_CALL_BUDGET" in helpers, (
        f"{wf_path.name}: callAgent must compare the running call count against the budget."
    )
    assert "throw new Error(" in helpers, (
        f"{wf_path.name}: exceeding the budget must throw (stop loudly), not just log."
    )


_BUDGET_BLOCK_RE = re.compile(
    r"agentCallCount > AGENT_CALL_BUDGET\)\s*\{(.*?)throw new Error\(",
    re.DOTALL,
)


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt012_budget_exceeded_writes_deferred_note_before_throw(wf_path: Path) -> None:
    """RT-012: every OTHER terminal exit path in this file writes a deferred note (the
    WC-003 convention — see the null-gate branches pinned elsewhere in this module) before
    stopping the wave, so the operator has a durable artifact recording what failed and how
    to retry. The agent-call budget throw is a terminal exit path too (it can fire from
    inside parallel(fixTasks) or the advisor fan-out, killing the wave mid-phase with
    plan.md unarchived) and must follow the same convention: write
    workspace/todos/deferred/<waveId>-agent-budget-exceeded.md BEFORE the throw, dispatched
    through the raw _dispatchAgent rather than callAgent — routing it through callAgent
    would let the note itself be blocked by the very budget it exists to report on."""
    helpers = _helpers_section(_read(wf_path), wf_path)
    match = _BUDGET_BLOCK_RE.search(helpers)
    assert match, f"{wf_path.name}: could not locate the agent-call budget-exceeded block."
    budget_block = match.group(1)

    assert "-agent-budget-exceeded.md" in budget_block, (
        f"{wf_path.name}: the budget-exceeded branch must write a deferred note "
        "(workspace/todos/deferred/<waveId>-agent-budget-exceeded.md) before throwing."
    )
    assert re.search(r"await _dispatchAgent\(", budget_block), (
        f"{wf_path.name}: the deferred-note write in the budget-exceeded branch must go "
        "through the raw _dispatchAgent, not callAgent, so it cannot be blocked by the "
        "budget it is reporting on."
    )


# RT-016: anchored to a real dispatch (`agent(` / `agent (`) rather than a bare
# substring-anywhere match. The negative lookbehind excludes any preceding
# identifier / `$` / `.` character so `callAgent(`, `_dispatchAgent(`, and
# `someObj.agent(` (a differently-scoped method, not the top-level dispatcher)
# are never mistaken for the bare call site this test hunts for, while
# `await agent (prompt)` — the same bypass with whitespace before the paren,
# which the old plain substring check silently let through — is still caught.
_BARE_AGENT_CALL_RE = re.compile(r"(?<![A-Za-z0-9_$.])agent\s*\(")

# Line comments plus single/double-quoted strings and template literals. A
# `//`-only strip is not enough: this file's own log prose reads "...escalating
# to debug agent (replaces fix fan-out this round)" — a parenthetical remark
# inside a quoted string, not a call — and a whitespace-tolerant call regex
# matches that text verbatim unless quoted content is stripped too.
_JS_NOISE_RE = re.compile(
    r"//[^\n]*"
    r"|'(?:\\.|[^'\\\n])*'"
    r'|"(?:\\.|[^"\\\n])*"'
    r"|`(?:\\.|[^`\\])*`",
    re.DOTALL,
)


def _strip_comments_and_strings(content: str) -> str:
    """Blank out comments and string/template literals so neither a comment
    nor a prompt/log string merely containing the literal text "agent(" (or,
    as in this file, ordinary English prose like "debug agent (replaces...)")
    can spuriously match the call-site scan below. A real `agent(...)` or
    `agent (...)` dispatch is never itself inside quotes, so this cannot hide
    a genuine bypass — only unquoted, uncommented code can match afterwards."""
    return _JS_NOISE_RE.sub(" ", content)


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_gh132_every_agent_call_site_routes_through_budget_wrapper(wf_path: Path) -> None:
    """No bare `agent(...)` dispatch may bypass the budget wrapper — a single
    leftover unwrapped call site would silently escape the hard backstop.

    RT-016: a plain `"agent(" not in content` substring check over the whole
    file (comments and prompt strings included) is both false-positive-prone
    (any future comment or agent prompt containing the literal text fails the
    test) and fail-open (a real bypass spelled `await agent (prompt)`, with a
    space before the paren, is not a substring match and slips through). The
    call-shaped regex below fixes both: it is scanned over comment-and-string
    -stripped code and matches whitespace between the identifier and the paren.
    """
    content = _read(wf_path)
    code = _strip_comments_and_strings(content)
    match = _BARE_AGENT_CALL_RE.search(code)
    assert match is None, (
        f"{wf_path.name}: found a bare `{match.group() if match else ''}` call site that "
        "bypasses the callAgent budget wrapper — every dispatch must go through "
        "callAgent(...) so the hard per-wave agent-call budget actually counts it."
    )
    assert content.count("async function callAgent(prompt, opts) {") == 1, (
        f"{wf_path.name}: expected exactly one callAgent wrapper definition."
    )


# ---------------------------------------------------------------------------
# RT-007: the findingsCount/findings-array reconciliation guard (WC-RT-004) must
# fail closed in BOTH directions.
#
# Root cause: once GH-132 keyed loop-exit on `blocking.length === 0` (derived from
# rt.findings, not rt.findingsCount), the WC-RT-004 guard reconciling ONLY
# `findingsCount === 0 && findings.length > 0` left the opposite mismatch —
# `findingsCount > 0 && findings.length === 0` — as a silent zero-tolerance bypass:
# RT_SCHEMA sets no minItems, so a schema-valid {findingsCount: 5, findings: []}
# response breaks the loop clean at round 1 with real findings unresolved. The fix
# adds the inverse guard, treated exactly like a null redteam response (unknown
# state, fail closed, same round-budget/deferred-note handling).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# RT-003 (this wave): the null-response and findings-mismatch round-budget exits break out
# of the zero-tolerance unit/phase redteam loops without setting any blocking flag — a
# redteam agent returning null (or a findingsCount/findings mismatch) on every round writes
# a deferred note and lets the wave proceed to Protocol Audit and Archive as if clean. An
# UNKNOWN verdict must block archive at least as hard as one where findings survived. Fix:
# `protocolBlocked = true` and a dedicated `redteamUnknownBlocked` flag (LRN-032: kept
# distinct from unitBudgetBlocked/phaseBudgetBlocked so the archive-skip message names the
# real cause) are set before each of the four exits' `break`.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# RT-004 (LRN-131 Prevention clause): the peerRepoAnnotations gate (LRN-085/RT-014)
# was added to wave-cycle.js's PLAN_RT_SCHEMA only. wave-cycle.js executes in
# downstream agent repos, which ship neither harness/workflows/ nor template/ — the
# check can never fire there. sdk-wave.js executes in THIS repo, the one place a todo
# can actually touch .claude/workflows/<file>.js or harness/workflows/<file>.js
# without also declaring the template/.claude/workflows/<file>.js peer-repo mirror
# (LRN-071). Per LRN-131's Prevention clause, a gate-logic refinement made in one
# runner must be ported to every runner in the same wave; these tests pin that parity
# for PLAN_RT_SCHEMA.required and the surrounding todos-redteam prompt/annotate logic.
# ---------------------------------------------------------------------------

_PLAN_RT_SCHEMA_BLOCK_RE = re.compile(
    r"const PLAN_RT_SCHEMA\s*=\s*\{.*?\n\}\n",
    re.DOTALL,
)


def _plan_rt_schema_block(content: str, wf_path: Path) -> str:
    match = _PLAN_RT_SCHEMA_BLOCK_RE.search(content)
    assert match, f"{wf_path.name}: could not locate the PLAN_RT_SCHEMA block."
    return match.group(0)


def _plan_rt_schema_required(content: str, wf_path: Path) -> set[str]:
    schema_block = _plan_rt_schema_block(content, wf_path)
    match = re.search(r"required:\s*\[(.*?)\]", schema_block, re.DOTALL)
    assert match, f"{wf_path.name}: PLAN_RT_SCHEMA has no top-level 'required' array."
    return set(re.findall(r"['\"]([^'\"]+)['\"]", match.group(1)))


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt004_plan_rt_schema_required_includes_peer_repo_annotations(wf_path: Path) -> None:
    required = _plan_rt_schema_required(_read(wf_path), wf_path)
    assert "peerRepoAnnotations" in required, (
        f"{wf_path.name}: PLAN_RT_SCHEMA.required is missing 'peerRepoAnnotations' — "
        "RT-004: the LRN-085/RT-014 peer-repo propagation gate must be ported to every "
        "runner that executes the todos-redteam phase (LRN-131 Prevention clause)."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt004_plan_rt_schema_required_at_parity_with_wave_cycle(wf_path: Path) -> None:
    """No hardcoded membership list on either side — parses PLAN_RT_SCHEMA.required
    directly out of both sides and asserts set-equality, so any future asymmetric add
    or remove between the runners fails CI regardless of which runner was edited."""
    reference = _plan_rt_schema_required(_read(WAVE_CYCLE_RUNTIME), WAVE_CYCLE_RUNTIME)
    actual = _plan_rt_schema_required(_read(wf_path), wf_path)
    assert actual == reference, (
        f"{wf_path.name}: PLAN_RT_SCHEMA.required {sorted(actual)} does not match "
        f"wave-cycle.js's {sorted(reference)} — RT-004: PLAN_RT_SCHEMA.required must "
        "stay identical across every runner (LRN-131)."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt004_peer_repo_annotations_item_shape(wf_path: Path) -> None:
    content = _read(wf_path)
    schema_block = _plan_rt_schema_block(content, wf_path)
    match = re.search(
        r"peerRepoAnnotations:\s*\{.*?items:\s*\{.*?required:\s*\[(.*?)\]",
        schema_block,
        re.DOTALL,
    )
    assert match, (
        f"{wf_path.name}: peerRepoAnnotations property (or its items.required array) "
        "not found inside PLAN_RT_SCHEMA."
    )
    item_required = re.findall(r"['\"]([^'\"]+)['\"]", match.group(1))
    assert item_required == ["todoId", "mirrorPath", "note"], (
        f"{wf_path.name}: peerRepoAnnotations item shape is {item_required}, expected "
        "['todoId', 'mirrorPath', 'note']."
    )


# ---------------------------------------------------------------------------
# RT-002 (redteam finding on this wave's own AGENT_CALL_BUDGET backstop): a hard cost
# ceiling that stops loudly must ship with an operator-reachable override, or the "loud
# stop" is an unrecoverable retry loop — a wave whose honest cost exceeds the default
# throws at the same point on every retry with no escape hatch short of editing this file.
#
# Scoped to WAVE_CYCLE_RUNTIME only (not parametrized over GH132_LOOP_LOGIC_FILES): this
# fix landed in .claude/workflows/wave-cycle.js. The finding's own remediation calls for
# mirroring it into harness/workflows/wave-cycle.js and .claude/workflows/sdk-wave.js too
# (both were already under concurrent, unrelated modification in this working tree at fix
# time) — test_runtime_and_harness_copies_are_identical (test_workflow_sync.py) will fail
# loudly if that mirroring does not land before archive.
# ---------------------------------------------------------------------------


def test_rt002_agent_call_budget_is_overridable() -> None:
    """AGENT_CALL_BUDGET must read from normalizedArgs.agentBudget rather than being a bare
    literal, so an operator can raise the ceiling for a wave with a legitimately higher
    honest cost without editing this file.

    RT-006: AGENT_CALL_BUDGET is now declared `let` (not `const`) so it can be recomputed
    once wave.groups.length is known — see
    test_rt006_agent_call_budget_recompute_scales_with_group_count in
    test_rt_wave_cycle_budget_and_mismatch_fixes.py for the scaling recompute itself. This
    test only pins the pre-Parse default's override-ability, unchanged by that fix.
    """
    helpers = _helpers_section(_read(WAVE_CYCLE_RUNTIME), WAVE_CYCLE_RUNTIME)
    assert re.search(
        r"let AGENT_CALL_BUDGET = Number\(normalizedArgs\.agentBudget\)\s*\|\|\s*\d+",
        helpers,
    ), (
        "wave-cycle.js: AGENT_CALL_BUDGET must be overridable via normalizedArgs.agentBudget "
        "— a bare `let AGENT_CALL_BUDGET = <N>` literal leaves no escape hatch short of "
        "editing this file when a wave's honest cost exceeds the default ceiling."
    )


# ---------------------------------------------------------------------------
# RT-008 (LRN-062/LRN-109 recurrence, compounded by RT-004 ID reuse): the LRN-062 plan.md
# ledger self-heal guard greps on wave.waveId alone. Two independently-authored wave files
# that reuse the same waveId (e.g. workspace/todos/completed/w036-gh-issues.md, archived
# 2026-07-24, and workspace/todos/active/w036-gh-issues.md, GH-129-GH-139 — both literally
# waveId "w036") therefore share one grep target: once the FIRST wave's row lands in
# plan.md, the SECOND wave's presence check vacuously passes against that row, self-heal
# never fires, and the second wave's own row silently never gets appended. Fix: derive
# waveFileTag (this wave's own File-column value) from WAVE_FILE and require BOTH
# wave.waveId AND waveFileTag on the matched line, so a different wave's row — same waveId,
# different File — cannot satisfy this wave's check.
# ---------------------------------------------------------------------------

_PLAN_ROW_GUARD_RE = re.compile(
    r"const waveFileTag = WAVE_FILE\.replace\(.*?"
    r"appended by self-heal guard'\)",
    re.DOTALL,
)


def _plan_row_guard_block(content: str, wf_path: Path) -> str:
    match = _PLAN_ROW_GUARD_RE.search(content)
    assert match, (
        f"{wf_path.name}: RT-008 plan.md ledger self-heal guard block "
        "('const waveFileTag = ...' through the self-heal success log) not found."
    )
    return match.group(0)


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_MIRRORS, ids=WAVE_CYCLE_MIRROR_IDS)
def test_rt008_plan_row_guard_defines_wave_file_tag(wf_path: Path) -> None:
    """waveFileTag must be derived from WAVE_FILE the same way the row-append template
    builds the File column value, so a row written by this guard and a row looked up by
    this guard always agree on what "this wave's file" means.
    """
    content = _read(wf_path)
    block = _plan_row_guard_block(content, wf_path)
    assert "const waveFileTag = WAVE_FILE.replace('workspace/todos/', '')" in block, (
        f"{wf_path.name}: waveFileTag is not derived from WAVE_FILE via the same "
        "'workspace/todos/' strip the row-append template uses for the File column."
    )


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_MIRRORS, ids=WAVE_CYCLE_MIRROR_IDS)
def test_rt008_plan_row_checks_no_longer_grep_wave_id_alone(wf_path: Path) -> None:
    """Negative guard: the old vacuous single-condition grep ('grep -ci "<waveId>"
    workspace/todos/plan.md' with no downstream filter on this wave's own file) must not
    reappear inside the plan-row guard block, or the RT-008 fix has silently regressed.
    """
    content = _read(wf_path)
    block = _plan_row_guard_block(content, wf_path)
    vacuous_grep = 'Run: grep -ci "\' + wave.waveId + \'" workspace/todos/plan.md\\n'
    assert vacuous_grep not in block, (
        f"{wf_path.name}: the plan-row guard still contains the bare waveId-only grep — "
        "RT-008 regression (two waves sharing a waveId can satisfy each other's ledger check)."
    )


def test_rt002_budget_exceeded_note_names_the_override() -> None:
    """The budget-exceeded deferred note's remediation must name the agentBudget override —
    telling the operator to just re-run /wave is misdirection, since a bare retry hits the
    identical ceiling at the identical point every time."""
    helpers = _helpers_section(_read(WAVE_CYCLE_RUNTIME), WAVE_CYCLE_RUNTIME)
    match = _BUDGET_BLOCK_RE.search(helpers)
    assert match, "wave-cycle.js: could not locate the agent-call budget-exceeded block."
    budget_block = match.group(1)
    assert "agentBudget" in budget_block, (
        "wave-cycle.js: the budget-exceeded deferred note must name the agentBudget override "
        "as the remediation, not just instruct a bare /wave retry that will deterministically "
        "hit the same ceiling again."
    )


# ---------------------------------------------------------------------------
# RT-009 (redteam finding on this wave's own GH-132 severity-floor deferred note): the
# medium/low deferred note was written ONLY on the clean loop-exit path (blocking.length
# === 0). The null-gate break, findings-mismatch break, and tests-red break all exit the
# same while(true) loop without ever recording that round's non-blocking findings, and
# medium/low findings from non-final rounds were never carried forward to whichever note
# eventually got written.
#
# RT-002/RT-009 (round-4 debug): these were originally scoped to WAVE_CYCLE_RUNTIME alone,
# which is exactly why the fix could land in the wave-cycle.js mirrors while sdk-wave.js —
# the runner .claude/skills/wave/SKILL.md launches for SDK waves — kept the clean-exit-only
# write and no accumulator at all. The only gate that spanned sdk-wave.js was
# test_gh132_medium_low_findings_deferred_once_not_blocking, whose `"-medium-low.md" in
# unit` substring probe is satisfied by a write nested inside the clean-exit branch, so it
# passed vacuously while the divergence was live. They are now parametrized over every
# runner, and the positional check is structural (brace-depth) rather than anchored on the
# `-tests-red-r` deferred note, which only the wave-cycle.js runners emit.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt009_accumulate_non_blocking_helper_defined(wf_path: Path) -> None:
    helpers = _helpers_section(_read(wf_path), wf_path)
    assert re.search(r"function accumulateNonBlocking\(store, seenSigs, findings\)\s*\{", helpers), (
        f"{wf_path.name}: accumulateNonBlocking helper missing — findings must be accumulated "
        "into a loop-scoped store every round, not computed-and-discarded outside the "
        "clean-exit branch."
    )


# ---------------------------------------------------------------------------
# RT-001 (fix round on this test module): the GH-132 round-cap rework — codify
# accumulation before the round-budget break, a blocking flag, and (for the phase loop)
# a deferred note — landed in both wave-cycle.js mirrors but never in sdk-wave.js, the
# runner .claude/skills/wave/SKILL.md step 2 actually launches for SDK waves. sdk-wave.js's
# phase round-cap exit was a bare log()+break with no deferred note, no archive block, and
# its codify capture sat AFTER the break (unreachable); its unit round-cap wrote a note but
# likewise captured codify AFTER the break and set no blocking flag. unitBudgetBlocked/
# phaseBudgetBlocked did not exist in sdk-wave.js at all. Fix: ported verbatim from
# wave-cycle.js, parametrized over GH132_LOOP_LOGIC_FILES (all runners) below so sdk-wave.js
# can never drift back out of parity.
#
# RT-006 (fix round on this test module): three further fixes had the identical drift —
# landed in the wave-cycle.js mirrors only. (1) the args JSON.parse normalization had no
# try/catch, so a malformed string args payload died with a bare, unattributed SyntaxError —
# the exact GH-131 failure mode, one layer up. (2) AGENT_CALL_BUDGET was a flat `const ... ||
# 150` with no group-count recompute and no rejection of an explicit `agentBudget: 0`. (3)
# the MAX_LRN_PER_WAVE overflow only log()ed — no deferred note — so findings past the cap
# were lost permanently. Fix: ported verbatim from wave-cycle.js, parametrized over
# GH132_LOOP_LOGIC_FILES below.
# ---------------------------------------------------------------------------


def _args_section(content: str, wf_path: Path) -> str:
    return _section(content, "// ─── args ", "// ─── protocol surface paths", wf_path)


def _wf_error_prefix(wf_path: Path) -> str:
    """Each runner's thrown errors are attributed with its own dialect-specific prefix
    ('wave-cycle:' vs 'sdk-wave:') — see test_rt017_json_parse_catch_rethrows_attributed_error
    in test_rt_wave_cycle_budget_and_mismatch_fixes.py for the wave-cycle.js-only precedent
    this generalizes."""
    return "wave-cycle:" if wf_path in WAVE_CYCLE_MIRRORS else "sdk-wave:"


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt001_budget_blocked_flags_declared_and_returned(wf_path: Path) -> None:
    content = _read(wf_path)
    assert re.search(r"let\s+unitBudgetBlocked\s*=\s*false", content), (
        f"{wf_path.name}: unitBudgetBlocked must be declared as wave-level state."
    )
    assert re.search(r"let\s+phaseBudgetBlocked\s*=\s*false", content), (
        f"{wf_path.name}: phaseBudgetBlocked must be declared as wave-level state."
    )
    return_block_idx = content.rfind("return {")
    assert return_block_idx != -1, f"{wf_path.name}: no final return object found."
    return_block = content[return_block_idx:]
    assert "unitBudgetBlocked:" in return_block, (
        f"{wf_path.name}: unitBudgetBlocked must be surfaced on the wave's final return object."
    )
    assert "phaseBudgetBlocked:" in return_block, (
        f"{wf_path.name}: phaseBudgetBlocked must be surfaced on the wave's final return object."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt001_archive_skip_message_distinguishes_budget_block_cause(wf_path: Path) -> None:
    content = _read(wf_path)
    skip_block_idx = content.find("if (protocolBlocked) {")
    assert skip_block_idx != -1, f"{wf_path.name}: archive-skip message block not found."
    skip_block = content[skip_block_idx : skip_block_idx + 4000]
    assert "phaseBudgetBlocked" in skip_block and "unitBudgetBlocked" in skip_block, (
        f"{wf_path.name}: the archive-skip message block must branch on phaseBudgetBlocked / "
        "unitBudgetBlocked — misdirected remediation (e.g. pointing at /agent-verify for a "
        "budget-exhausted block) wastes developer time."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt006_args_json_parse_wrapped_in_try_catch(wf_path: Path) -> None:
    args_section = _args_section(_read(wf_path), wf_path)
    assert "try {" in args_section and "JSON.parse(args)" in args_section, (
        f"{wf_path.name}: args normalization does not wrap JSON.parse(args) in try/catch — a "
        "malformed string args payload dies with a bare, unattributed SyntaxError, the exact "
        "GH-131 failure mode one layer up."
    )
    try_idx = args_section.find("try {")
    parse_idx = args_section.find("JSON.parse(args)")
    catch_idx = args_section.find("} catch", parse_idx)
    assert -1 < try_idx < parse_idx < catch_idx, (
        f"{wf_path.name}: JSON.parse(args) must sit inside a try/catch block, not a bare, "
        "unguarded call."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt006_json_parse_catch_rethrows_attributed_error(wf_path: Path) -> None:
    args_section = _args_section(_read(wf_path), wf_path)
    catch_idx = args_section.find("} catch")
    assert catch_idx != -1, f"{wf_path.name}: no catch block found after JSON.parse(args)."
    catch_block = args_section[catch_idx : catch_idx + 400]
    assert _wf_error_prefix(wf_path) in catch_block and "not valid JSON" in catch_block, (
        f"{wf_path.name}: the JSON.parse catch block must rethrow an attributed error naming "
        f"'{_wf_error_prefix(wf_path)}' and explaining the payload is not valid JSON — a bare "
        "re-throw or a generic message reproduces the exact unactionable failure mode GH-131 "
        "removed, one layer up."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt011_explicit_zero_agent_budget_rejected_via_consolidated_guard(wf_path: Path) -> None:
    """RT-011 (fix round): a dedicated `Number(normalizedArgs.agentBudget) === 0` guard
    used to run before the general finite/positive guard, throwing for the identical 0
    input the finite/positive guard already rejects (0 fails `> 0`) — fully redundant.
    It has been folded away: the standalone `=== 0` check must no longer appear anywhere
    in the file, and the single remaining finite/positive guard must still throw for an
    explicit 0 override.
    """
    content = _read(wf_path)
    assert "Number(normalizedArgs.agentBudget) === 0" not in content, (
        f"{wf_path.name}: the redundant standalone agentBudget===0 guard should have been "
        "removed — it is fully subsumed by the Number.isFinite(...) && ... > 0 guard, "
        "which already rejects 0 (0 is not > 0)."
    )
    finite_check_idx = content.find(
        "!(Number.isFinite(Number(normalizedArgs.agentBudget)) && "
        "Number(normalizedArgs.agentBudget) > 0)"
    )
    assert finite_check_idx != -1, (
        f"{wf_path.name}: the consolidated finite/positive agentBudget guard is missing — "
        "an explicit override of 0 would no longer be rejected at all."
    )
    throw_idx = content.find("throw new Error(", finite_check_idx)
    assert -1 < finite_check_idx < throw_idx < finite_check_idx + 400, (
        f"{wf_path.name}: the consolidated agentBudget guard must throw, not just log."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt006_agent_call_budget_is_mutable_for_recompute(wf_path: Path) -> None:
    content = _read(wf_path)
    assert "let AGENT_CALL_BUDGET" in content, (
        f"{wf_path.name}: AGENT_CALL_BUDGET must be declared with `let`, not `const` — it is "
        "recomputed once wave.groups.length is known."
    )
    assert "const AGENT_CALL_BUDGET" not in content, (
        f"{wf_path.name}: AGENT_CALL_BUDGET must not also be declared `const` anywhere."
    )


@pytest.mark.parametrize("wf_path", _sdk_wave_only(GH132_LOOP_LOGIC_FILES, GH132_LOOP_LOGIC_IDS)[0], ids=_sdk_wave_only(GH132_LOOP_LOGIC_FILES, GH132_LOOP_LOGIC_IDS)[1])
def test_rt006_agent_call_budget_recompute_scales_with_group_count(wf_path: Path) -> None:
    content = _read(wf_path)
    assert (
        "AGENT_CALL_BUDGET = Number(normalizedArgs.agentBudget) || "
        "Math.max(150, 45 * wave.groups.length + 80)"
    ) in content, (
        f"{wf_path.name}: AGENT_CALL_BUDGET must be recomputed from wave.groups.length once "
        "known (explicit override wins; otherwise scale with group count) — a fixed constant "
        "documented as too low for a routine wave is a failure mode, not a guard."
    )
    default_idx = content.find("let AGENT_CALL_BUDGET = Number(normalizedArgs.agentBudget) || 150")
    recompute_idx = content.find(
        "AGENT_CALL_BUDGET = Number(normalizedArgs.agentBudget) || "
        "Math.max(150, 45 * wave.groups.length + 80)"
    )
    wave_groups_norm_idx = content.find("g.scope    = uniq(g.creates.concat(g.modifies))")
    assert -1 < default_idx < wave_groups_norm_idx < recompute_idx, (
        f"{wf_path.name}: the scaled AGENT_CALL_BUDGET recompute must be positioned after "
        "wave.groups has been parsed and normalized, not before."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt006_lrn_cap_overflow_writes_deferred_note(wf_path: Path) -> None:
    codify = _codify_section(_read(wf_path), wf_path)
    cap_check_idx = codify.find("if (toCodeify.length > MAX_LRN_PER_WAVE) {")
    assert cap_check_idx != -1, f"{wf_path.name}: MAX_LRN_PER_WAVE overflow branch not found."
    note_idx = codify.find("-lrn-cap-exceeded.md", cap_check_idx)
    assert note_idx != -1, (
        f"{wf_path.name}: MAX_LRN_PER_WAVE overflow must write a deferred note "
        "(<wave>-lrn-cap-exceeded.md) — a bare log() line loses the overflow findings "
        "permanently."
    )
    close_brace_idx = codify.find("\n}", cap_check_idx)
    assert cap_check_idx < note_idx < close_brace_idx, (
        f"{wf_path.name}: the deferred-note write must be inside the "
        "`if (toCodeify.length > MAX_LRN_PER_WAVE)` branch."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt006_lrn_cap_deferred_note_includes_overflow_findings(wf_path: Path) -> None:
    codify = _codify_section(_read(wf_path), wf_path)
    cap_check_idx = codify.find("if (toCodeify.length > MAX_LRN_PER_WAVE) {")
    assert cap_check_idx != -1, f"{wf_path.name}: MAX_LRN_PER_WAVE overflow branch not found."
    overflow_decl_window = codify[cap_check_idx : cap_check_idx + 300]
    assert "toCodeify.slice(MAX_LRN_PER_WAVE)" in overflow_decl_window, (
        f"{wf_path.name}: the overflow branch must derive the overflow set from "
        "toCodeify.slice(MAX_LRN_PER_WAVE)."
    )
    note_idx = codify.find("-lrn-cap-exceeded.md", cap_check_idx)
    assert note_idx != -1, f"{wf_path.name}: MAX_LRN_PER_WAVE deferred note not found."
    window = codify[note_idx : note_idx + 800]
    assert "JSON.stringify(" in window, (
        f"{wf_path.name}: the LRN-cap deferred note must serialize the overflow findings into "
        "the note body."
    )


# ---------------------------------------------------------------------------
# RT-004 (w039, formerly filed under the reused ID w036 — see
# workspace/todos/completed/w036-gh-issues.md for the unrelated, already-archived RT-004
# this reuses the ID from): a wave ID is not guaranteed unique across active/, completed/,
# and deferred/. The archive step's `mv <wave file> workspace/todos/completed/` (and, on
# wave-cycle.js, the step-4 LRN-100 deferred-marker relocation sweep) both move by
# basename — a wave file whose basename collides with an already-archived wave silently
# overwrites that earlier wave's record, with no error from either runner.
#
# Fix: WAVE_SCHEMA gains a required `completedFileExists` boolean, determined
# UNCONDITIONALLY while parsing (`test -f workspace/todos/completed/<basename>`); Parse
# hard-blocks and returns an error object the moment it is true, before any other
# wave-cycle work starts; and the archive-step prompt's move instruction (plus,
# wave-cycle.js only, the step-4 sweep) is rewritted to check-before-move and refuse to
# overwrite an existing destination even as a defense-in-depth fallback.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# RT-001 (fix round): Parse-phase scope extraction must harvest every backticked path
# token on a Creates:/Modifies: line, including paths named inside a parenthetical
# "(modifies ...)" clause — the pre-fix prompt asked only for "every 'Creates:' path
# listed" / "every 'Modifies:' path listed", a literal reading of which extracts at
# most one path per line and silently drops every other declared deliverable on a wave
# whose todos use the dominant `Creates: (modifies `a`, `b`, `c`); adds `d`` prose form
# (see workspace/todos/completed/w036-gh-issues.md and
# workspace/todos/active/w039-gh-issues.md for real examples). Every downstream gate
# keyed off wave.allScope (phase redteam scope, protocol-surface detection, the
# template hard-block, offendingUndeclaredScope) silently narrows when this under-
# extracts. Reuses RT004_FILES: all four archive-gate runners share the identical
# Parse-prompt Extract wording. See tests/test_wave_scope_extraction.py for a
# deterministic reference implementation of the same rule, run against a real fixture
# wave file.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# RT-011: RT_SCHEMA lists `codify` as OPTIONAL, but the unit/phase redteam loops and the
# protocol-audit findings pipeline all fed allHighFindings through `.filter(f => f.codify)` —
# a critical/high finding whose redteam output omitted the required "Codify:" line was
# silently dropped from allHighFindings entirely, so it never reached the Codify LRN pass NOR
# the SDK issue scan (both iterate the same toCodeify set, derived from allHighFindings).
# GH-132's severity floor made this materially worse: reaching a round cap now means only
# surviving critical/high findings exist, and those are exactly the ones this filter could
# discard. Fix: push every blocking (critical/high) finding into allHighFindings regardless of
# whether it carries a codify string; log a WARNING naming any critical/high finding that
# arrived without one, so the gap stays visible instead of silent. The codify agent already
# receives each finding's full description/fix (JSON.stringify(f, null, 2) in the LRN-write
# prompt) and can synthesise a lesson from those when codify itself is absent.
#
# Scoped to WAVE_CYCLE_MIRRORS (not GH132_LOOP_LOGIC_FILES) — sdk-wave.js carries the same
# defect but is out of scope for this fix.
# ---------------------------------------------------------------------------


def _protocol_audit_section(content: str, wf_path: Path) -> str:
    return _section(content, _PHASE5_MARKER, _PHASE6_MARKER, wf_path)


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_MIRRORS, ids=WAVE_CYCLE_MIRROR_IDS)
def test_rt011_protocol_audit_findings_do_not_require_codify(wf_path: Path) -> None:
    proto_section = _protocol_audit_section(_read(wf_path), wf_path)
    assert "(f.severity === 'critical' || f.severity === 'high') && f.codify" not in proto_section, (
        f"{wf_path.name}: protocol-audit findings feeding allHighFindings must not additionally "
        "require f.codify — a critical/high protocol finding missing a Codify: line would be "
        "silently dropped from the Codify LRN pass and the SDK issue scan, same as RT-011's "
        "unit/phase-loop defect."
    )
    assert "const protoBlocking = allProtoFindings.filter(function(f) {" in proto_section, (
        f"{wf_path.name}: protocol-audit critical/high findings must be computed once "
        "(protoBlocking) independent of whether they carry a codify string."
    )
    assert "missingCodifyProto" in proto_section, (
        f"{wf_path.name}: a critical/high protocol finding missing a Codify: line must still be "
        "logged by name."
    )


# ---------------------------------------------------------------------------
# RT-015: the agentBudget===0 override guard rejects exactly 0 on the stated rationale that
# `0 || default` would hide a typo'd override — but `Number(x) || default` (the very next
# line) does exactly that for ANY non-numeric override: Number('abc') is NaN, which is also
# falsy, so a typo'd string override silently falls back to the default with no error. The
# 0-check does not catch it (Number('abc') === 0 is false). Fix: a second, general guard
# rejects any provided override that is not Number.isFinite AND > 0, positioned before the
# `|| default` fallback line — so that fallback can only ever fire for an omitted override,
# never an invalid one.
#
# Originally scoped to WAVE_CYCLE_MIRRORS only — sdk-wave.js carried the same defect (per
# the finding, at .claude/workflows/sdk-wave.js:485/609) but was out of scope for that fix.
# RT-011 (fix round): folding the now-redundant standalone `=== 0` guard into this one
# general guard was ported to sdk-wave.js too (closing that pre-existing gap as a
# byproduct), so these tests now run over GH132_LOOP_LOGIC_FILES (all four runners) rather
# than WAVE_CYCLE_MIRRORS alone.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt015_non_numeric_agent_budget_override_rejected(wf_path: Path) -> None:
    content = _read(wf_path)
    assert "Number.isFinite(Number(normalizedArgs.agentBudget))" in content, (
        f"{wf_path.name}: a typo'd/non-numeric agentBudget override (e.g. 'abc') must be "
        "rejected via Number.isFinite — Number('abc') is NaN, which the exact-zero check does "
        "not catch, and `Number(x) || default` then silently falls back to the default with no "
        "error at all."
    )
    finite_check_idx = content.find("Number.isFinite(Number(normalizedArgs.agentBudget))")
    throw_idx = content.find("throw new Error(", finite_check_idx)
    assert -1 < finite_check_idx < throw_idx < finite_check_idx + 400, (
        f"{wf_path.name}: the Number.isFinite guard must throw, not just log."
    )
    assert "JSON.stringify(normalizedArgs.agentBudget)" in content[finite_check_idx:throw_idx + 400], (
        f"{wf_path.name}: the thrown error must name the actual received value."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt015_finite_guard_runs_before_fallback(wf_path: Path) -> None:
    """RT-011 (fix round): this used to also assert a standalone `=== 0` guard ran before
    the general finite/positive guard — that guard was folded away as redundant (0 already
    fails `> 0`), so only ordering-before-fallback remains meaningful to assert."""
    content = _read(wf_path)
    finite_check_idx = content.find("Number.isFinite(Number(normalizedArgs.agentBudget))")
    default_idx = content.find("let AGENT_CALL_BUDGET = Number(normalizedArgs.agentBudget) || 150")
    assert -1 < finite_check_idx < default_idx, (
        f"{wf_path.name}: the general Number.isFinite guard must run before the "
        "`let AGENT_CALL_BUDGET = ... || 150` fallback line — it must have a chance to "
        "throw before any override reaches the fallback."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt015_finite_guard_also_covers_negative_and_infinite(wf_path: Path) -> None:
    """The guard's condition must be a conjunction (finite AND positive), not just a
    finiteness check alone — otherwise a negative override (e.g. -5) or one that is finite
    but non-positive would still slip through to the `|| default` fallback undetected."""
    content = _read(wf_path)
    finite_check_idx = content.find("Number.isFinite(Number(normalizedArgs.agentBudget))")
    assert finite_check_idx != -1, f"{wf_path.name}: Number.isFinite guard not found."
    window = content[finite_check_idx : finite_check_idx + 200]
    assert "> 0" in window, (
        f"{wf_path.name}: the general agentBudget guard must also require the value be "
        "positive (> 0), not merely finite — a negative override must be rejected too."
    )


# ---------------------------------------------------------------------------
# RT-001 (round-6 fresh-lens): the protocol-audit advisor fan-out must fail CLOSED
# on a null advisor result.
#
# Root cause this closes: `(await parallel(advisorTasks)).filter(Boolean)` was the only
# agent-result consumer in the wave runners that DISCARDED a null result instead of
# treating it as unknown-and-blocking. Every other site guards `if (!x) { ...blocked }`
# (LRN-019/022/023/024/026/029/030/031/063 all codify this exact fail-open class). A
# crashed or schema-rejected a2a/mcp/ag-ui/a2ui/seam advisor therefore contributed 0 to
# protoCritical/protoHigh, protocolBlocked stayed false, and the wave archived as
# "protocol-clean" on a protocol that was never actually audited.
#
# Why a CLASS guard and not another per-site assertion: rounds 1-5 of this fix loop each
# pinned the one null site they happened to find, which is why the same class kept
# resurfacing somewhere new. The shape check below forbids the construct itself in every
# runner, so a future fan-out cannot reintroduce it silently.
# ---------------------------------------------------------------------------

# Matches a `.filter(Boolean)` applied directly to a parallel() dispatch result, in both
# the parenthesised form `(await parallel(x)).filter(Boolean)` and the bare chained form.
_PARALLEL_FILTER_BOOLEAN_RE = re.compile(
    r"await\s+parallel\s*\([^)]*\)\s*\)?\s*\.filter\(\s*Boolean\s*\)"
)


@pytest.mark.parametrize("wf_path", RT004_FILES, ids=RT004_FILES_IDS)
def test_rt001_parallel_agent_results_never_silently_filter_nulls(wf_path: Path) -> None:
    """No runner may drop a null agent result with `.filter(Boolean)` straight off a
    parallel() dispatch — that converts an UNKNOWN verdict into a clean one.

    Scanned over comment-and-string-stripped code so the rationale comments that quote
    the old shape (deliberately, to explain what was wrong) cannot mask a real regression.
    """
    code = _strip_comments_and_strings(_read(wf_path))
    match = _PARALLEL_FILTER_BOOLEAN_RE.search(code)
    assert match is None, (
        f"{wf_path.name}: found `{match.group() if match else ''}` — a null agent result "
        "dropped by filter(Boolean) is an unknown verdict silently counted as clean. "
        "Count the nulls first and set protocolBlocked = true when any are present."
    )


