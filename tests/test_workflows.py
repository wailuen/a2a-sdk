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


def _normalize_ladder_dialect(ladder: str, wf_path: Path) -> str:
    """Replace this runner's source-root/worked-example tokens with neutral
    placeholders so two runners' ladders can be compared for LOGIC equivalence
    without pinning them to a shared (and therefore necessarily wrong-for-one)
    path dialect. Mirrors _normalize_auth_surface_dialect's approach for the
    AUTH_SURFACE arrays. Order matters: longer/more specific tokens first, root
    last, so `agent_sdk/routes/a2a.py` and `src/tools/quote.py` both normalize to
    `<ROOT>/<EXDIR>/<EXFILE>`.
    """
    d = _dialect(wf_path)
    for key, placeholder in (
        ("example_file", "<EXFILE>"),
        ("example_mod", "<EXMOD>"),
        ("example_pkg", "<EXPKG>"),
        ("example_dir", "<EXDIR>"),
        ("example_kind", "<EXKIND>"),
        ("root", "<ROOT>"),
    ):
        ladder = ladder.replace(d[key], placeholder)
    return ladder


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

# RT-003 (w036): mirrors _UNDECLARED_IMPORTS_CONDITION_RE for offendingUndeclaredScope.
_UNDECLARED_SCOPE_CONDITION_RE = re.compile(
    r"archiveIntent\.offendingUndeclaredScope\s*&&\s*"
    r"archiveIntent\.offendingUndeclaredScope\.length\s*>\s*0"
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
def test_rt004_archive_intent_schema_has_template_dir_exists_in_required(wf_path: Path) -> None:
    """RT-004: ARCHIVE_INTENT_SCHEMA required array must include 'templateDirExists' — without
    it in the schema the agent is not constrained to report it, and the hard-block below has
    no signal to act on.
    """
    content = _read(wf_path)
    schema_match = re.search(
        r"const ARCHIVE_INTENT_SCHEMA\s*=\s*\{.*?required:\s*\[([^\]]*)\]",
        content,
        re.DOTALL,
    )
    assert schema_match, f"{wf_path.name}: ARCHIVE_INTENT_SCHEMA not found or has no 'required' array"
    required_array = schema_match.group(1)
    assert "templateDirExists" in required_array, (
        f"{wf_path.name}: 'templateDirExists' is missing from ARCHIVE_INTENT_SCHEMA.required — "
        f"RT-004 hard-block cannot be evaluated without it. Required array found: {required_array!r}"
    )


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


@pytest.mark.parametrize("wf_path", RT004_FILES, ids=RT004_FILES_IDS)
def test_rt004_prompt_checks_template_dir_unconditionally(wf_path: Path) -> None:
    """RT-004: the archiveIntent prompt must instruct the agent to determine templateDirExists
    UNCONDITIONALLY (regardless of git status), not only when template/ happens to exist —
    step 4b's existing 'If a `template/` directory exists' guard cannot power this check,
    since it never fires at all when template/ is absent.
    """
    content = _read(wf_path)
    prompt = _archive_intent_prompt(content, wf_path)
    for expected in ["test -d template", "UNCONDITIONALLY", "templateDirExists"]:
        assert expected in prompt, (
            f"{wf_path.name}: '{expected}' not found in the archiveIntent agent prompt — "
            "RT-004's unconditional template/ existence check is missing or incomplete."
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


@pytest.mark.parametrize("wf_path", RT004_FILES, ids=RT004_FILES_IDS)
def test_rt006_template_dir_check_schema_defined(wf_path: Path) -> None:
    """Every runner must carry the cheap single-fact schema the Parse gate uses —
    reusing ARCHIVE_INTENT_SCHEMA here would demand git status output this early
    check has no use for."""
    content = _read(wf_path)
    match = re.search(
        r"const TEMPLATE_DIR_CHECK_SCHEMA\s*=\s*\{(.*?)\n\}", content, re.DOTALL
    )
    assert match, (
        f"{wf_path.name}: TEMPLATE_DIR_CHECK_SCHEMA not found — this runner has no "
        "Parse-phase template-dir gate, so a wave declaring an unlandable template/ "
        "propagation burns its whole agent-call budget before finding out."
    )
    assert "templateDirExists" in match.group(1), (
        f"{wf_path.name}: TEMPLATE_DIR_CHECK_SCHEMA does not carry templateDirExists."
    )


@pytest.mark.parametrize("wf_path", RT004_FILES, ids=RT004_FILES_IDS)
def test_rt006_parse_phase_aborts_before_any_expensive_phase(wf_path: Path) -> None:
    """The gate must run in the Parse phase and RETURN, not merely warn — and it must
    fail closed on a null agent response, like every other gate in these runners."""
    content = _read(wf_path)
    assert "const parseDeclaresTemplateScope" in content, (
        f"{wf_path.name}: no parseDeclaresTemplateScope derivation — the Parse-phase "
        "template-dir abort is missing."
    )
    match = re.search(
        r"if \(parseDeclaresTemplateScope\) \{(.*?)\n\}\n", content, re.DOTALL
    )
    assert match, f"{wf_path.name}: parseDeclaresTemplateScope block not found."
    block = match.group(1)
    assert "phase: 'Parse'" in block, (
        f"{wf_path.name}: the template-dir check must be dispatched in the Parse phase — "
        "running it later defeats the point of the fast abort."
    )
    assert "!templateCheck || templateCheck.templateDirExists === false" in block, (
        f"{wf_path.name}: the Parse template gate must fail CLOSED — a null response is "
        "unknown state, not proof that template/ is present."
    )
    assert "return { error: 'template-dir-missing'" in block, (
        f"{wf_path.name}: the Parse template gate must ABORT the wave, not just log — "
        "otherwise the budget it exists to save is still spent."
    )


_PROTOCOL_BLOCKED_MESSAGE_SECTION_RE = re.compile(
    r"if \(protocolBlocked\) \{(.*?)\n\} else \{\n  await callAgent\(\n    'Archive wave",
    re.DOTALL,
)


def _protocol_blocked_message_section(content: str, wf_path: Path) -> str:
    match = _PROTOCOL_BLOCKED_MESSAGE_SECTION_RE.search(content)
    assert match, (
        f"{wf_path.name}: could not locate the final `if (protocolBlocked) {{ ... }}` "
        "archive-skip message section."
    )
    return match.group(1)


@pytest.mark.parametrize("wf_path", RT004_FILES, ids=RT004_FILES_IDS)
def test_rt004_archive_skip_message_distinguishes_template_propagation_block(wf_path: Path) -> None:
    """RT-004 (RT-003 principle: 'use the actual block cause in the message'): a wave blocked
    by the templatePropagationBlocked gate must not fall into the generic 'blocked by critical
    protocol findings' / '/agent-verify' branch — that remediation is wrong for this cause.
    """
    section = _protocol_blocked_message_section(_read(wf_path), wf_path)
    assert "templatePropagationBlocked" in section, (
        f"{wf_path.name}: the final protocolBlocked message section has no distinct branch for "
        "templatePropagationBlocked — a template-propagation block would fall through to the "
        "generic 'blocked by critical protocol findings' / '/agent-verify' message, which is "
        "the wrong remediation for this cause."
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

@pytest.mark.parametrize(
    "wf_path,dialect_root", ARCHIVE_GATE_DIALECT_CASES, ids=ARCHIVE_GATE_DIALECT_IDS
)
def test_gh118_archive_intent_prompt_contains_import_cross_check_instructions(
    wf_path: Path, dialect_root: str
) -> None:
    """GH-118: archiveIntent agent prompt must instruct the agent to resolve absolute
    intra-package imports of dirty/scope .py files to file paths, check `git ls-files` on
    each resolved path, and cross-reference against wave.allScope to populate
    offendingUndeclaredImports.

    RT-001 (round-5): the absolute root asserted here is THIS runner's own source root
    (ARCHIVE_GATE_DIALECT), not the literal 'agent_sdk' for both. The old form pinned
    'agent_sdk' in wave-cycle.js too, actively cementing a resolver root that cannot exist
    in the only repo layout that runner is allowed to run in.
    """
    content = _read(wf_path)
    prompt = _archive_intent_prompt(content, wf_path)
    for expected in [
        f"import {dialect_root}.",
        f"from {dialect_root} import <name>",
        "git ls-files",
        "offendingUndeclaredImports",
    ]:
        assert expected in prompt, (
            f"{wf_path.name}: '{expected}' not found in the archiveIntent agent prompt — "
            "the GH-118 import cross-check instructions are missing or incomplete."
        )


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

@pytest.mark.parametrize("wf_path", GH118_FILES, ids=GH118_FILES_IDS)
def test_rt003_archive_intent_schema_has_offending_undeclared_scope_in_required(wf_path: Path) -> None:
    """RT-003 (w036): ARCHIVE_INTENT_SCHEMA required array must include
    'offendingUndeclaredScope'. Without this field in the schema the agent is not
    constrained to return it, and the blocking condition's fourth OR clause silently
    always evaluates falsy.
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
    assert "offendingUndeclaredScope" in required_array, (
        f"{wf_path.name}: 'offendingUndeclaredScope' is missing from "
        f"ARCHIVE_INTENT_SCHEMA.required — RT-003 (w036) blocking will silently not work. "
        f"Required array found: {required_array!r}"
    )


@pytest.mark.parametrize("wf_path", GH118_FILES, ids=GH118_FILES_IDS)
def test_rt003_archive_intent_schema_has_offending_undeclared_scope_in_properties(wf_path: Path) -> None:
    """RT-003 (w036): ARCHIVE_INTENT_SCHEMA properties must define 'offendingUndeclaredScope'."""
    content = _read(wf_path)
    schema_block = _archive_intent_schema_block(content, wf_path)
    # Anchored to the schema block itself so a comment mentioning the token elsewhere
    # can't mask its removal from required[] / properties{}.
    occurrences = schema_block.count("offendingUndeclaredScope")
    assert occurrences >= 2, (
        f"{wf_path.name}: 'offendingUndeclaredScope' appears only {occurrences} time(s) "
        "inside ARCHIVE_INTENT_SCHEMA — expected at least 2 (required array + properties "
        "definition). RT-003 (w036) schema may be incomplete."
    )


@pytest.mark.parametrize(
    "wf_path,dialect_root", UNDECLARED_SCOPE_DIALECT_CASES, ids=UNDECLARED_SCOPE_DIALECT_IDS
)
def test_rt003_offending_undeclared_scope_description_names_tracked_and_dialect_root(
    wf_path: Path, dialect_root: str
) -> None:
    """RT-003 (fix round): the offendingUndeclaredScope property description must name
    THIS RUNNER's own watched-tree dialect ('agent_sdk' for sdk-wave.js, 'src' for
    wave-cycle.js — see UNDECLARED_SCOPE_DIALECT_CASES) and 'tracked' (the discriminator
    that distinguishes it from offendingUndeclaredImports, which only inspects untracked
    .py files). The RT-003 fix-round bug this pins: the glob was ported byte-identical
    from sdk-wave.js into wave-cycle.js, watching agent_sdk/**.py in a runner whose real
    audience is a downstream agent repo laid out under src/ — a permanent no-op there.
    """
    content = _read(wf_path)
    schema_block = _archive_intent_schema_block(content, wf_path)
    match = re.search(
        r"offendingUndeclaredScope:\s*\{.*?description:\s*'([^']*)'",
        schema_block,
        re.DOTALL,
    )
    assert match, (
        f"{wf_path.name}: could not locate the offendingUndeclaredScope property "
        "description inside ARCHIVE_INTENT_SCHEMA."
    )
    description = match.group(1)
    dialect_glob = dialect_root + "/**.py"
    assert f"dirty paths under {dialect_glob} that ARE TRACKED" in description, (
        f"{wf_path.name}: the offendingUndeclaredScope description does not name this "
        f"runner's own dialect ({dialect_glob!r}) as the watched tree. Description "
        f"found: {description!r}"
    )
    for expected in ["tracked", "wave.allScope"]:
        assert expected in description, (
            f"{wf_path.name}: '{expected}' not found in the offendingUndeclaredScope schema "
            f"description. Description found: {description!r}"
        )


# ---------------------------------------------------------------------------
# RT-003 (w036): quadruple blocking condition
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("wf_path", GH118_FILES, ids=GH118_FILES_IDS)
def test_rt003_quadruple_blocking_condition_present(wf_path: Path) -> None:
    """RT-003 (w036): the archive blocking condition must OR in a fourth clause for
    offendingUndeclaredScope, on top of the existing triple condition (offendingPaths,
    offendingHarnessPaths, offendingUndeclaredImports) — a source file modified but
    declared nowhere must block archive exactly like the other three offender classes.
    """
    content = _read(wf_path)
    triple_condition_re = re.compile(
        r'offendingPaths\s*&&\s*archiveIntent\.offendingPaths\.length\s*>\s*0'
        r'\s*\)\s*\|\|\s*\('
        r'\s*archiveIntent\.offendingHarnessPaths\s*&&\s*archiveIntent\.offendingHarnessPaths\.length\s*>\s*0'
        r'\s*\)\s*\|\|\s*\('
        r'\s*archiveIntent\.offendingUndeclaredImports\s*&&\s*archiveIntent\.offendingUndeclaredImports\.length\s*>\s*0',
        re.DOTALL,
    )
    quad_condition_re = re.compile(
        triple_condition_re.pattern
        + r'\s*\)\s*\|\|\s*\('
        r'\s*archiveIntent\.offendingUndeclaredScope\s*&&\s*archiveIntent\.offendingUndeclaredScope\.length\s*>\s*0',
        re.DOTALL,
    )
    assert quad_condition_re.search(content), (
        f"{wf_path.name}: RT-003 (w036) fourth OR clause for offendingUndeclaredScope not "
        "found in the blocking condition. Expected pattern: "
        "(archiveIntent.offendingPaths && ... > 0) || "
        "(archiveIntent.offendingHarnessPaths && ... > 0) || "
        "(archiveIntent.offendingUndeclaredImports && ... > 0) || "
        "(archiveIntent.offendingUndeclaredScope && ... > 0)"
    )


# ---------------------------------------------------------------------------
# RT-003 (w036): agent prompt instructs the undeclared-scope check
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "wf_path,dialect_root", UNDECLARED_SCOPE_DIALECT_CASES, ids=UNDECLARED_SCOPE_DIALECT_IDS
)
def test_rt003_archive_intent_prompt_contains_undeclared_scope_check_instructions(
    wf_path: Path, dialect_root: str
) -> None:
    """RT-003 (w036; RT-003 fix round: dialect-parametrized, see
    UNDECLARED_SCOPE_DIALECT_CASES): archiveIntent agent prompt must instruct the agent
    to check dirty, TRACKED <dialect_root>/**.py paths against wave.allScope and populate
    offendingUndeclaredScope.
    """
    content = _read(wf_path)
    prompt = _archive_intent_prompt(content, wf_path)
    for expected in [dialect_root + "/**", "git ls-files", "offendingUndeclaredScope", "TRACKED"]:
        assert expected in prompt, (
            f"{wf_path.name}: '{expected}' not found in the archiveIntent agent prompt — "
            "the RT-003 (w036) undeclared-scope check instructions are missing or "
            "incomplete."
        )


@pytest.mark.parametrize("wf_path", GH118_FILES, ids=GH118_FILES_IDS)
def test_rt003_prompt_return_fields_count_updated_to_six(wf_path: Path) -> None:
    """RT-003 (w036): the prompt's final 'Return all N fields' instruction and the
    clean-tree default-value list must both be updated from five to six fields —
    otherwise an agent following stale instructions may omit offendingUndeclaredScope
    entirely.

    RT-004 both gained a SEVENTH field (templateDirExists) on top of RT-003's six:
    wave-cycle.js first, then sdk-wave.js (RT-002/LRN-131 — the RT-004 hard-block had
    landed only in the three wave-cycle.js copies, leaving sdk-wave.js undetected by the
    RT-004 tests, which were themselves parametrized over WAVE_CYCLE_MIRRORS alone). Both
    GH118_FILES entries now expect "seven".
    """
    content = _read(wf_path)
    prompt = _archive_intent_prompt(content, wf_path)
    expected_count_words = "seven"
    assert "Return all " + expected_count_words + " fields" in prompt, (
        f"{wf_path.name}: prompt does not say 'Return all {expected_count_words} fields' — "
        f"field-count instruction is stale or was not updated in lockstep with the schema."
    )
    assert "offendingUndeclaredScope is []" in prompt, (
        f"{wf_path.name}: the clean-tree default-value list does not mention "
        "'offendingUndeclaredScope is []' — an agent following it on a clean tree may "
        "omit the field from its response."
    )


@pytest.mark.parametrize("wf_path", GH118_FILES, ids=GH118_FILES_IDS)
def test_rt003_inline_comment_cross_references_gh_issues(wf_path: Path) -> None:
    """RT-003 (w036): inline comment blocks (schema + blocking-condition site) cite
    'RT-003', so a future reader finds the rationale without archaeology — mirrors
    test_gh118_inline_comment_cross_references_lrn_and_gh.
    """
    content = _read(wf_path)

    schema_block = _archive_intent_schema_block(content, wf_path)
    assert "RT-003" in schema_block, (
        f"{wf_path.name}: 'RT-003' not found inside the ARCHIVE_INTENT_SCHEMA block — "
        "the offendingUndeclaredScope description/comment must cite it there."
    )

    condition_match = _UNDECLARED_SCOPE_CONDITION_RE.search(content)
    assert condition_match, (
        f"{wf_path.name}: could not locate the offendingUndeclaredScope blocking "
        "condition — cannot anchor cross-reference assertions to it."
    )
    condition_window = _window_around(content, condition_match.start(), condition_match.end())
    assert "RT-003" in condition_window, (
        f"{wf_path.name}: 'RT-003' not found near the offendingUndeclaredScope blocking "
        "condition — the blocking-condition comment block must cite it there."
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


@pytest.mark.parametrize(
    "wf_path,dialect_root", ARCHIVE_GATE_DIALECT_CASES, ids=ARCHIVE_GATE_DIALECT_IDS
)
def test_rt001_archive_intent_prompt_covers_single_segment_and_top_level_absolute_forms(
    wf_path: Path, dialect_root: str
) -> None:
    """RT-001: the prompt must also cover the single-segment absolute form
    (`import <root>.<module>`, e.g. `import <root>.foo`) and the bare top-level
    from-import form (`from <root> import <name>`), which the original two-form wording
    (which assumed at least a `<pkg>.<submodule>` split) did not literally include.

    RT-001 (round-5): `<root>` is per-runner (ARCHIVE_GATE_DIALECT), not 'agent_sdk' for
    both.
    """
    content = _read(wf_path)
    prompt = _archive_intent_prompt(content, wf_path)
    for expected in [
        f"import {dialect_root}.foo",
        f"from {dialect_root} import <name>",
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

    `from ..<pkg> import <submodule>` names the submodule `<root>/<pkg>/<submodule>.py`,
    where `<pkg>` is a PACKAGE. A rule that resolves it straight to the nonexistent
    `<root>/<pkg>.py` (git ls-files empty, out of scope) flags a false-positive
    undeclared-import archive block on every wave scoping such a file — the exact
    regression this gate must not have. The prompt must therefore instruct the
    submodule-existence check and pin a concrete worked example.

    RT-001 (round-5): both the example import and its resolution target are per-runner
    (ARCHIVE_GATE_DIALECT) — sdk-wave.js pins agent_sdk/credentials/forwarding.py, an
    a2a-sdk path; wave-cycle.js pins src/sources/pricing.py, a downstream agent path.
    Pinning the a2a-sdk example in both cemented a resolver root that cannot exist in
    the tree wave-cycle.js runs against.
    """
    content = _read(wf_path)
    prompt = _archive_intent_prompt(content, wf_path)
    d = _dialect(wf_path)
    example_import = f"from ..{d['example_pkg']} import {d['example_mod']}"
    example_target = f"{d['root']}/{d['example_pkg']}/{d['example_mod']}.py"
    # The submodule-existence disambiguation must be instructed for the relative form,
    # not a straight resolve-to-`<pkg-path>.py`.
    assert "<pkg-path>/<name>.py" in prompt, (
        f"{wf_path.name}: the relative from-import form does not instruct a "
        "`<pkg-path>/<name>.py` submodule-existence check — `from ..pkg import submodule` "
        "will mis-resolve to a nonexistent `<pkg>.py` and false-positive the archive gate."
    )
    # The concrete RT-001 false-positive import and its CORRECT resolution target must
    # both appear as the pinning worked example, in THIS runner's dialect.
    assert example_import in prompt, (
        f"{wf_path.name}: the RT-001 `{example_import}` worked example "
        "is missing — the relative-import submodule disambiguation is unspecified."
    )
    assert example_target in prompt, (
        f"{wf_path.name}: the correct resolution target {example_target} "
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
        f"{_dialect(wf_path)['root']}/<pkg-path>/<name>/__init__.py",
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
    repo layout — it claimed `from <root> import <dir>` resolves by checking for
    `<root>/<dir>.py`, but that file does not exist (`<root>/<dir>/` is a
    package). The corrected example must resolve to `<root>/<dir>/__init__.py`,
    and `<root>/<dir>.py` must never appear as a resolution TARGET — only as the
    "does NOT exist" foil that motivates falling through to the package `__init__.py`.

    RT-001 (round-5 fresh-lens): `<root>`/`<dir>` are per-runner (ARCHIVE_GATE_DIALECT) —
    agent_sdk/routes for sdk-wave.js, src/tools for wave-cycle.js (the downstream agent
    src/ tree ships tools/sources/artifacts/skills, never src/routes/).

    RT-005: the negative half is a semantic, whitespace-normalized check rather than a
    pin to one exact JS-source concatenation/indentation. That exact serialization only
    ever existed transiently in the round-4 working tree and can never match current or
    future (differently formatted, differently worded) content, so a literal-string
    negative here is vacuous — it would silently pass even if the same bug reappeared in
    slightly different phrasing.
    """
    content = _read(wf_path)
    prompt = _archive_intent_prompt(content, wf_path)
    d = _dialect(wf_path)
    pkg_init = f"{d['root']}/{d['example_dir']}/__init__.py"
    pkg_module = f"{d['root']}/{d['example_dir']}.py"
    assert pkg_init in prompt, (
        f"{wf_path.name}: the corrected worked example resolving `from {d['root']} import "
        f"{d['example_dir']}` to `{pkg_init}` is missing."
    )

    normalized = _normalize_ws(prompt)
    assert f"check for `{pkg_module}`. if the submodule file exists" not in normalized.lower(), (
        f"{wf_path.name}: the old factually-wrong worked example (`from {d['root']} import "
        f"{d['example_dir']}` resolved by checking for the nonexistent `{pkg_module}` as a "
        "resolution TARGET) is still present."
    )
    # `<root>/<dir>.py` may legitimately appear as the "does NOT exist" foil that
    # motivates falling through to the package `__init__.py` — but every occurrence must be
    # immediately qualified as nonexistent, never stated as the actual resolution target.
    for match in re.finditer(re.escape(pkg_module), normalized):
        trailing = normalized[match.end(): match.end() + 40].lower()
        assert "does not exist" in trailing, (
            f"{wf_path.name}: `{pkg_module}` appears at offset {match.start()} in the "
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
    # RT-001 (round-5): rooted at THIS runner's source root, not 'agent_sdk' for both.
    root = _dialect(wf_path)["root"]
    assert f"NEVER to the nonexistent `{root}/common/origin/__init__.py`" in ladder, (
        f"{wf_path.name}: the RT-004 ABSOLUTE worked example (guard_origin resolves "
        f"to {root}/common/origin.py, never the enclosing __init__.py) is missing "
        "— the pkg-path-as-MODULE branch is not exercised on the absolute form."
    )

    # RT-004 sub-package worked example on the RELATIVE form — proves the RELATIVE
    # form is a genuine four-way ladder, not the old straight-to-`<pkg-path>.py`.
    assert "from ..common import newsubpkg" in ladder, (
        f"{wf_path.name}: the RT-004 RELATIVE sub-package worked example "
        f"(`from ..common import newsubpkg` -> {root}/common/newsubpkg/__init__.py) "
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
    silently diverged from wave-cycle.js and passed CI green. This equivalence
    assertion fails the moment either runner's ladder is edited without the other,
    closing the sdk-wave.js <-> wave-cycle.js drift axis that test_workflow_sync.py
    (wave-cycle.js's three copies only) does not cover.

    RT-001 (round-5 fresh-lens debug): comparison is dialect-NORMALIZED, not raw.
    Requiring the two ladders to be textually identical is what forced sdk-wave.js's
    `agent_sdk` source root into wave-cycle.js in the first place — a runner that only
    ever executes against a downstream `src/` tree, where an agent_sdk-rooted resolver
    matches nothing. The property worth pinning is that the four-way LOGIC is the same,
    not that the PATHS are; _normalize_ladder_dialect maps each runner's root and
    worked-example tokens to neutral placeholders so a strictly-weaker port still
    fails here while the required dialect divergence is allowed. Same approach as
    _normalize_auth_surface_dialect.
    """
    sdk_ladder = _normalize_ladder_dialect(
        _import_resolver_ladder(_read(SDK_WAVE), SDK_WAVE), SDK_WAVE
    )
    wc_ladder = _normalize_ladder_dialect(
        _import_resolver_ladder(_read(WAVE_CYCLE_RUNTIME), WAVE_CYCLE_RUNTIME),
        WAVE_CYCLE_RUNTIME,
    )
    assert _normalize_ws(sdk_ladder) == _normalize_ws(wc_ladder), (
        "import-resolver ladder diverges between sdk-wave.js and wave-cycle.js "
        "(after normalizing each runner's source-root dialect) — the four-way "
        "disambiguation (submodule -> sub-package -> pkg-path-as-MODULE -> enclosing "
        "package) must be identical across both runners. Any refinement to one MUST be "
        "ported to the other; the byte-identical sync guard covers only wave-cycle.js's "
        "three copies, never this axis."
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

# RT-001 (round-6 fresh-lens): these block terminators previously pinned the literal
# `const protoResults = (await parallel(advisorTasks)).filter(Boolean)`. That spelling was
# the fail-open being fixed — the fan-out now counts null advisor results before discarding
# them (`const rawProtoResults = await parallel(...)`), so the anchors follow the rename.
# Block boundaries are unchanged: the terminator still marks the end of the same seam block,
# and every assertion below still runs against the same extracted text.
_SEAM_INITIAL_BLOCK_RE = re.compile(
    r"const SEAM_ROUTE_MARKERS.*?const rawProtoResults\s*=\s*await parallel\(advisorTasks\)",
    re.DOTALL,
)

_SEAM_RECHECK_BLOCK_RE = re.compile(
    r"// Seam recheck:.*?const rawRecheckResults\s*=\s*await parallel\(recheckTasks\)",
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

# RT-001 (round-6 fresh-lens): terminators follow the null-counting rename — see the
# matching note on _SEAM_INITIAL_BLOCK_RE above. Block boundaries are unchanged.
_SDK_WAVE_SEAM_INITIAL_BLOCK_RE = re.compile(
    r"const advisorTasks = \[\].*?const rawProtoResults\s*=\s*await parallel\(advisorTasks\)",
    re.DOTALL,
)

_SDK_WAVE_SEAM_RECHECK_BLOCK_RE = re.compile(
    r"const recheckTasks = \[\].*?const rawRecheckResults\s*=\s*await parallel\(recheckTasks\)",
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

_PHASE3_MARKER = "// ─── phase 3: unit redteam"
_PHASE4_MARKER = "// ─── phase 4: phase redteam"
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


def _unit_redteam_section(content: str, wf_path: Path) -> str:
    return _section(content, _PHASE3_MARKER, _PHASE4_MARKER, wf_path)


def _phase_redteam_section(content: str, wf_path: Path) -> str:
    return _section(content, _PHASE4_MARKER, _PHASE5_MARKER, wf_path)


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
def test_gh132_unit_loop_exit_uses_severity_floor(wf_path: Path) -> None:
    unit = _unit_redteam_section(_read(wf_path), wf_path)
    assert "if (blocking.length === 0) {" in unit, (
        f"{wf_path.name}: unit redteam loop must exit when zero BLOCKING (critical/high) "
        "findings remain, not on raw findingsCount."
    )
    assert "if (rt.findingsCount === 0) {" not in unit, (
        f"{wf_path.name}: unit redteam loop still exits on raw findingsCount===0 (every "
        "severity, including low) — the exact GH-132 root-cause bug."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_gh132_phase_loop_exit_uses_severity_floor(wf_path: Path) -> None:
    phase_section = _phase_redteam_section(_read(wf_path), wf_path)
    assert "if (blocking.length === 0) {" in phase_section, (
        f"{wf_path.name}: phase redteam loop must exit when zero BLOCKING (critical/high) "
        "findings remain, not on raw findingsCount."
    )
    assert "if (rt.findingsCount === 0) {" not in phase_section, (
        f"{wf_path.name}: phase redteam loop still exits on raw findingsCount===0 (every "
        "severity, including low) — the exact GH-132 root-cause bug."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_gh132_medium_low_findings_deferred_once_not_blocking(wf_path: Path) -> None:
    content = _read(wf_path)
    helpers = _helpers_section(content, wf_path)
    unit = _unit_redteam_section(content, wf_path)
    phase_section = _phase_redteam_section(content, wf_path)
    assert "-medium-low.md" in unit, (
        f"{wf_path.name}: unit loop must write a deferred note recording non-blocking "
        "medium/low findings once, when the loop exits clean on the severity floor."
    )
    assert "-phase-medium-low.md" in phase_section, (
        f"{wf_path.name}: phase loop must write a deferred note recording non-blocking "
        "medium/low findings once, when the loop exits clean on the severity floor."
    )

    # RT-009: a bare substring probe above is satisfied by a write nested inside the
    # clean-exit `if (blocking.length === 0) {` branch alone — unreachable from the
    # null-gate/findings-mismatch/round-budget/tests-red breaks that exit the same
    # while(true) loop. Pin the real contract (accumulate every round via
    # accumulateNonBlocking, write once from a place every break path reaches) directly
    # in this GH132_LOOP_LOGIC_FILES-parametrized test rather than relying solely on the
    # separately-scoped test_rt009_* tests below to catch a regression here.
    assert re.search(r"function accumulateNonBlocking\(store, seenSigs, findings\)\s*\{", helpers), (
        f"{wf_path.name}: accumulateNonBlocking helper missing — findings must be "
        "accumulated into a loop-scoped store every round, not computed-and-discarded "
        "outside the clean-exit branch."
    )
    assert "accumulateNonBlocking(groupNonBlocking, groupNonBlockingSigs, rt.findings)" in unit, (
        f"{wf_path.name}: unit redteam loop must accumulate every round's non-blocking "
        "findings via accumulateNonBlocking, not compute-and-discard outside the "
        "clean-exit branch."
    )
    assert "accumulateNonBlocking(phaseNonBlocking, phaseNonBlockingSigs, rt.findings)" in phase_section, (
        f"{wf_path.name}: phase redteam loop must accumulate every round's non-blocking "
        "findings via accumulateNonBlocking, not compute-and-discard outside the "
        "clean-exit branch."
    )
    assert not _write_is_inside_clean_exit_branch(
        unit, "-group-' + group.label + '-medium-low.md"
    ), (
        f"{wf_path.name}: the unit medium-low deferred note is nested inside the "
        "`if (blocking.length === 0)` clean-exit branch — a clean-exit-only write is "
        "unreachable from the null-gate/findings-mismatch/round-budget/tests-red breaks "
        "that exit the same loop."
    )
    assert not _write_is_inside_clean_exit_branch(phase_section, "-phase-medium-low.md"), (
        f"{wf_path.name}: the phase medium-low deferred note is nested inside the "
        "`if (blocking.length === 0)` clean-exit branch — a clean-exit-only write is "
        "unreachable from every non-clean-exit break path in the same loop."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_gh132_debug_replaces_fix_fan_out_not_alongside_it(wf_path: Path) -> None:
    """The fix fan-out must be gated on NOT escalating to debug: the debug agent's
    own prompt already says 'Fix at the root', so dispatching both debug AND the
    fix fan-out in the same round duplicated the fix work and compounded cost —
    the exact behavior GH-132 flags as the round-4+ compounding bug."""
    content = _read(wf_path)
    unit = _unit_redteam_section(content, wf_path)
    phase_section = _phase_redteam_section(content, wf_path)

    assert "const escalateToDebug = uRound > 3 || stalled" in unit, (
        f"{wf_path.name}: unit loop must compute an escalateToDebug flag from the same "
        "round-4+/stall condition that used to gate debug alone."
    )
    assert "if (!escalateToDebug) {" in unit, (
        f"{wf_path.name}: unit loop's fix fan-out must be gated on !escalateToDebug so "
        "debug replaces it rather than running alongside it."
    )

    assert "const pEscalateToDebug = pRound > 3 || pStalled" in phase_section, (
        f"{wf_path.name}: phase loop must compute a pEscalateToDebug flag from the same "
        "round-4+/stall condition that used to gate debug alone."
    )
    assert "if (!pEscalateToDebug) {" in phase_section, (
        f"{wf_path.name}: phase loop's fix fan-out must be gated on !pEscalateToDebug so "
        "debug replaces it rather than running alongside it."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_gh132_fix_fan_out_batched_below_threshold_split_above(wf_path: Path) -> None:
    content = _read(wf_path)
    assert re.search(r"const FIX_BATCH_FILE_THRESHOLD = \d+", content), (
        f"{wf_path.name}: FIX_BATCH_FILE_THRESHOLD constant missing."
    )
    unit = _unit_redteam_section(content, wf_path)
    phase_section = _phase_redteam_section(content, wf_path)
    for label, section in (("unit", unit), ("phase", phase_section)):
        assert "files.length > FIX_BATCH_FILE_THRESHOLD" in section, (
            f"{wf_path.name}: {label} loop's fix-task construction must branch on "
            "files.length > FIX_BATCH_FILE_THRESHOLD — one agent per round below the "
            "threshold, per-file fan-out above it."
        )
        assert "grouped by file" in section, (
            f"{wf_path.name}: {label} loop must have a single batched-fix prompt covering "
            "every file in ONE agent call below the threshold."
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

# RT-016 (this wave): wave-cycle.js's two-special-case guard (findingsCount===0-with-items
# below, plus its RT-007 inverse) collapsed to a single `findingsCount !== findings.length`
# invariant covering both directions AND every partial mismatch the two-case guard missed
# (e.g. findingsCount=5 with a 1-item array) — see the test_rt016_* tests in
# test_rt_wave_cycle_budget_and_mismatch_fixes.py for the unified-check coverage itself.
# sdk-wave.js was out of scope for that fix and keeps the original two-case guard, so the
# RT-007 tests below select their guard marker per file rather than assuming one shape.
def _findings_mismatch_guard_marker(wf_path: Path) -> str:
    return (
        "rt.findingsCount !== rt.findings.length"
        if wf_path in WAVE_CYCLE_MIRRORS
        else "rt.findingsCount > 0 && rt.findings.length === 0"
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt007_findings_count_zero_with_items_reconciled(wf_path: Path) -> None:
    """WC-RT-004 direction: findingsCount=0 with a non-empty findings array must be
    reconciled to non-clean in BOTH the unit and phase redteam loops (RT-016: on
    wave-cycle.js, both directions are now the SAME single inequality check)."""
    content = _read(wf_path)
    unit = _unit_redteam_section(content, wf_path)
    phase_section = _phase_redteam_section(content, wf_path)
    marker = (
        "rt.findingsCount !== rt.findings.length"
        if wf_path in WAVE_CYCLE_MIRRORS
        else "rt.findingsCount === 0 && rt.findings.length > 0"
    )
    for label, section in (("unit", unit), ("phase", phase_section)):
        assert marker in section, (
            f"{wf_path.name}: {label} loop is missing the findingsCount===0-with-items "
            "reconciliation guard (or its RT-016 unified replacement)."
        )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt007_findings_count_positive_with_empty_array_reconciled(wf_path: Path) -> None:
    """RT-007 inverse direction: findingsCount>0 with an EMPTY findings array must
    also be caught — otherwise it silently breaks the loop clean via
    `blocking.length === 0`, since blocking is derived from rt.findings, not
    rt.findingsCount. RT_SCHEMA sets no minItems, so this shape is schema-valid."""
    content = _read(wf_path)
    unit = _unit_redteam_section(content, wf_path)
    phase_section = _phase_redteam_section(content, wf_path)
    marker = _findings_mismatch_guard_marker(wf_path)
    for label, section in (("unit", unit), ("phase", phase_section)):
        assert marker in section, (
            f"{wf_path.name}: {label} loop is missing the RT-007 inverse "
            "findingsCount-mismatch guard (or its RT-016 unified replacement) — a "
            "{{findingsCount: N>0, findings: []}} response would break the loop clean "
            "with real findings unresolved."
        )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt007_inverse_guard_precedes_severity_floor_exit(wf_path: Path) -> None:
    """The inverse guard must run BEFORE `blocking.length === 0` is evaluated in
    both loops — placed after the guard but still gating the exit would let the
    mismatched response reach the severity-floor exit check and break clean."""
    content = _read(wf_path)
    unit = _unit_redteam_section(content, wf_path)
    phase_section = _phase_redteam_section(content, wf_path)
    marker = _findings_mismatch_guard_marker(wf_path)
    for label, section in (("unit", unit), ("phase", phase_section)):
        guard_pos = section.find(marker)
        exit_pos = section.find("if (blocking.length === 0) {")
        assert guard_pos != -1 and exit_pos != -1 and guard_pos < exit_pos, (
            f"{wf_path.name}: {label} loop's RT-007 inverse guard must appear "
            "before the `blocking.length === 0` severity-floor exit check."
        )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt007_inverse_guard_mirrors_null_response_budget_handling(wf_path: Path) -> None:
    """The inverse guard must fail closed exactly like the null-response branch:
    round-budget check (uRound>=5 / pRound>=8), a deferred note on budget exhaustion,
    and `continue` (not falling through) when budget remains — never a silent
    fall-through into the severity-floor exit."""
    content = _read(wf_path)
    unit = _unit_redteam_section(content, wf_path)
    phase_section = _phase_redteam_section(content, wf_path)
    marker = _findings_mismatch_guard_marker(wf_path)

    unit_guard_start = unit.find(marker)
    unit_exit_pos = unit.find("if (blocking.length === 0) {")
    assert unit_guard_start != -1 and unit_exit_pos != -1 and unit_guard_start < unit_exit_pos, (
        f"{wf_path.name}: unit RT-007 guard not found before the severity-floor exit check."
    )
    unit_guard_block = unit[unit_guard_start:unit_exit_pos]
    assert "if (uRound >= 5) {" in unit_guard_block, (
        f"{wf_path.name}: unit RT-007 guard must enforce the same round-5 budget as "
        "the null-response branch."
    )
    assert "-rt-mismatch-budget.md" in unit_guard_block, (
        f"{wf_path.name}: unit RT-007 guard must write a deferred note on budget exhaustion."
    )
    assert "continue" in unit_guard_block, (
        f"{wf_path.name}: unit RT-007 guard must `continue` (retry) rather than falling "
        "through to the severity-floor exit when round budget remains."
    )

    phase_guard_start = phase_section.find(marker)
    phase_exit_pos = phase_section.find("if (blocking.length === 0) {")
    assert phase_guard_start != -1 and phase_exit_pos != -1 and phase_guard_start < phase_exit_pos, (
        f"{wf_path.name}: phase RT-007 guard not found before the severity-floor exit check."
    )
    phase_guard_block = phase_section[phase_guard_start:phase_exit_pos]
    assert "if (pRound >= 8) {" in phase_guard_block, (
        f"{wf_path.name}: phase RT-007 guard must enforce the same round-8 budget as "
        "the null-response branch."
    )
    assert "-phase-rt-mismatch-budget.md" in phase_guard_block, (
        f"{wf_path.name}: phase RT-007 guard must write a deferred note on budget exhaustion."
    )
    assert "continue" in phase_guard_block, (
        f"{wf_path.name}: phase RT-007 guard must `continue` (retry) rather than falling "
        "through to the severity-floor exit when round budget remains."
    )


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


def _block_before_next_break(section: str, log_marker: str, wf_path: Path) -> str:
    """Slice from a round-budget exit's log() line up to (not including) its own `break` —
    the same bounded-slice technique test_rt_wave_cycle_budget_and_mismatch_fixes.py uses.
    The literal log text is identical across every GH132_LOOP_LOGIC_FILES dialect, and each
    marker's nearest following `break` is unambiguously its own exit's break (no other break
    sits between a round-budget log() and its exit)."""
    start = section.find(log_marker)
    assert start != -1, f"{wf_path.name}: could not locate log marker {log_marker!r}."
    break_idx = section.find("break", start)
    assert break_idx != -1, f"{wf_path.name}: no `break` found after {log_marker!r}."
    return section[start:break_idx]


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt003_unit_null_response_budget_exit_sets_blocking_flags(wf_path: Path) -> None:
    """The unit loop's null-response round-budget exit (uRound >= 5 inside `if (!rt) {`) must
    set protocolBlocked and redteamUnknownBlocked before its break — otherwise a redteam
    agent returning null on every round archives the wave as if clean."""
    unit = _unit_redteam_section(_read(wf_path), wf_path)
    block = _block_before_next_break(
        unit, "Null responses exceeded round budget for group", wf_path
    )
    assert "protocolBlocked = true" in block, (
        f"{wf_path.name}: the unit null-response round-budget exit does not set "
        "protocolBlocked = true before its break — a persistent null redteam verdict would "
        "archive as if clean."
    )
    assert "redteamUnknownBlocked = true" in block, (
        f"{wf_path.name}: the unit null-response round-budget exit does not set "
        "redteamUnknownBlocked = true before its break."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt003_unit_mismatch_budget_exit_sets_blocking_flags(wf_path: Path) -> None:
    """The unit loop's findings-count-mismatch round-budget exit must set protocolBlocked and
    redteamUnknownBlocked before its break, identically to the null-response exit above —
    this exit is fail-closed on the round-budget check itself, but was fail-open on the
    archive-blocking flag."""
    unit = _unit_redteam_section(_read(wf_path), wf_path)
    block = _block_before_next_break(
        unit, "Findings-count mismatch exceeded round budget for group", wf_path
    )
    assert "protocolBlocked = true" in block, (
        f"{wf_path.name}: the unit findings-mismatch round-budget exit does not set "
        "protocolBlocked = true before its break — a persistent findingsCount/findings "
        "mismatch would archive as if clean."
    )
    assert "redteamUnknownBlocked = true" in block, (
        f"{wf_path.name}: the unit findings-mismatch round-budget exit does not set "
        "redteamUnknownBlocked = true before its break."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt003_phase_null_response_budget_exit_sets_blocking_flags(wf_path: Path) -> None:
    """The phase loop's null-response round-budget exit (pRound >= 8 inside `if (!rt) {`) must
    set protocolBlocked and redteamUnknownBlocked before its break."""
    phase_section = _phase_redteam_section(_read(wf_path), wf_path)
    block = _block_before_next_break(
        phase_section, "Null responses exceeded phase round budget", wf_path
    )
    assert "protocolBlocked = true" in block, (
        f"{wf_path.name}: the phase null-response round-budget exit does not set "
        "protocolBlocked = true before its break — a persistent null redteam verdict would "
        "archive as if clean."
    )
    assert "redteamUnknownBlocked = true" in block, (
        f"{wf_path.name}: the phase null-response round-budget exit does not set "
        "redteamUnknownBlocked = true before its break."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt003_phase_mismatch_budget_exit_sets_blocking_flags(wf_path: Path) -> None:
    """The phase loop's findings-count-mismatch round-budget exit must set protocolBlocked and
    redteamUnknownBlocked before its break."""
    phase_section = _phase_redteam_section(_read(wf_path), wf_path)
    block = _block_before_next_break(
        phase_section, "Findings-count mismatch exceeded phase round budget", wf_path
    )
    assert "protocolBlocked = true" in block, (
        f"{wf_path.name}: the phase findings-mismatch round-budget exit does not set "
        "protocolBlocked = true before its break — a persistent findingsCount/findings "
        "mismatch would archive as if clean."
    )
    assert "redteamUnknownBlocked = true" in block, (
        f"{wf_path.name}: the phase findings-mismatch round-budget exit does not set "
        "redteamUnknownBlocked = true before its break."
    )


@pytest.mark.parametrize("wf_path", RT004_FILES, ids=RT004_FILES_IDS)
def test_rt003_archive_skip_message_distinguishes_redteam_unknown_block(wf_path: Path) -> None:
    """A wave blocked solely by redteamUnknownBlocked must not fall into the generic 'blocked
    by critical protocol findings' / '/agent-verify' branch (LRN-032: that remediation is
    wrong for an UNKNOWN verdict — there is nothing for /agent-verify to find)."""
    section = _protocol_blocked_message_section(_read(wf_path), wf_path)
    assert "redteamUnknownBlocked" in section, (
        f"{wf_path.name}: the final protocolBlocked message section has no distinct branch "
        "for redteamUnknownBlocked — a redteam-unknown block would fall through to the "
        "generic 'blocked by critical protocol findings' / '/agent-verify' message, which is "
        "the wrong remediation for this cause."
    )


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

_PLAN_RT_PROMPT_RE = re.compile(
    r"const planRt\s*=\s*await callAgent\((.*?)"
    r"\{\s*schema:\s*PLAN_RT_SCHEMA,\s*label:\s*'rt:todos'",
    re.DOTALL,
)

_TODOS_ANNOTATE_PROMPT_RE = re.compile(
    r"'Annotate the wave file ' \+ WAVE_FILE(.*?)\{\s*label:\s*'rt:todos:annotate'",
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


def _plan_rt_prompt(content: str, wf_path: Path) -> str:
    match = _PLAN_RT_PROMPT_RE.search(content)
    assert match, (
        f"{wf_path.name}: could not locate the `const planRt = await callAgent(...)` "
        "call — cannot anchor todos-redteam prompt assertions to it."
    )
    return match.group(1)


def _todos_annotate_prompt(content: str, wf_path: Path) -> str:
    match = _TODOS_ANNOTATE_PROMPT_RE.search(content)
    assert match, (
        f"{wf_path.name}: could not locate the rt:todos:annotate agent() call — "
        "cannot anchor annotate-payload assertions to it."
    )
    return match.group(1)


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


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt004_todos_redteam_prompt_documents_peer_repo_propagation_check(wf_path: Path) -> None:
    prompt = _plan_rt_prompt(_read(wf_path), wf_path)
    for expected in (
        "PEER-REPO PROPAGATION",
        "harness/workflows/<file>.js",
        "template/.claude/workflows/<file>.js",
        "peerRepoAnnotations",
    ):
        assert expected in prompt, (
            f"{wf_path.name}: todos-redteam prompt is missing {expected!r} — the "
            "PEER-REPO PROPAGATION check item is not documented for the agent that "
            "executes the todos redteam."
        )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt004_has_annotations_includes_peer_repo_annotations(wf_path: Path) -> None:
    content = _read(wf_path)
    has_annotations_match = re.search(
        r"const hasAnnotations\s*=(.*?)\n\s*const hasSliceIssues", content, re.DOTALL
    )
    assert has_annotations_match, (
        f"{wf_path.name}: could not locate the `const hasAnnotations = ...` expression."
    )
    assert "planRt.peerRepoAnnotations" in has_annotations_match.group(1), (
        f"{wf_path.name}: hasAnnotations does not fold in planRt.peerRepoAnnotations — "
        "a peer-repo-only gap would silently skip the annotate-back step."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt004_peer_repo_gap_count_logged(wf_path: Path) -> None:
    content = _read(wf_path)
    assert (
        "if (planRt.peerRepoAnnotations && planRt.peerRepoAnnotations.length > 0) {"
        in content
    ), (
        f"{wf_path.name}: missing the peer-repo propagation gap count log guard."
    )
    assert "peer-repo propagation gap(s) flagged" in content, (
        f"{wf_path.name}: missing the peer-repo propagation gap count log message."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt004_annotate_agent_payload_includes_peer_repo_annotations(wf_path: Path) -> None:
    annotate_prompt = _todos_annotate_prompt(_read(wf_path), wf_path)
    assert "JSON.stringify(planRt.peerRepoAnnotations, null, 2)" in annotate_prompt, (
        f"{wf_path.name}: rt:todos:annotate call does not serialize "
        "planRt.peerRepoAnnotations into the annotate-agent payload."
    )
    assert "git -C template/ commit" in annotate_prompt, (
        f"{wf_path.name}: rt:todos:annotate call does not instruct the implementer to "
        "commit+push the template/ peer repo (LRN-071)."
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
def test_rt008_plan_row_checks_require_both_wave_id_and_file_tag(wf_path: Path) -> None:
    """Both the initial presence check and the post-repair recheck must pipe a waveId grep
    into a fixed-string grep on this wave's own waveFileTag — matching on waveId alone is
    exactly the LRN-062/RT-008 vacuous-pass hole this guard exists to close.
    """
    content = _read(wf_path)
    block = _plan_row_guard_block(content, wf_path)
    combined_grep = (
        'Run: grep -i "\' + wave.waveId + \'" workspace/todos/plan.md | '
        'grep -ci -F "\' + waveFileTag + \'"\\n'
    )
    assert block.count(combined_grep) == 2, (
        f"{wf_path.name}: expected the combined waveId+waveFileTag grep pipeline in both "
        f"planRowCheck and planRowRecheck (found {block.count(combined_grep)} of 2)."
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


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_MIRRORS, ids=WAVE_CYCLE_MIRROR_IDS)
def test_rt008_plan_row_repair_prompt_warns_about_id_reuse(wf_path: Path) -> None:
    """The self-heal repair prompt must tell the implementing agent not to overwrite a
    same-waveId-but-different-file row belonging to another wave (RT-004 ID reuse) — without
    this, an agent repairing the ledger could "fix" the pre-existing row in place instead of
    appending a new one, silently merging two distinct waves' history under one row.
    """
    content = _read(wf_path)
    block = _plan_row_guard_block(content, wf_path)
    assert "different wave that reused this waveId" in block, (
        f"{wf_path.name}: repair prompt does not warn about RT-004 waveId reuse — an agent "
        "could overwrite a different wave's pre-existing row instead of appending its own."
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


def _write_is_inside_clean_exit_branch(section: str, marker: str) -> bool:
    """True if `marker` occurs while the nearest preceding
    `if (blocking.length === 0) {` block is still open (brace-depth walk).

    This is the RT-002 defect expressed directly: a deferred-note write nested
    in the clean-exit branch is unreachable from the null-gate,
    findings-mismatch, round-budget and tests-red breaks, which all exit the
    same while(true) loop.
    """
    pos = section.find(marker)
    assert pos != -1, f"marker {marker!r} not found in section"
    branch = section.rfind("if (blocking.length === 0) {", 0, pos)
    if branch == -1:
        return False
    between = section[branch:pos]
    return between.count("{") > between.count("}")


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt009_accumulate_non_blocking_helper_defined(wf_path: Path) -> None:
    helpers = _helpers_section(_read(wf_path), wf_path)
    assert re.search(r"function accumulateNonBlocking\(store, seenSigs, findings\)\s*\{", helpers), (
        f"{wf_path.name}: accumulateNonBlocking helper missing — findings must be accumulated "
        "into a loop-scoped store every round, not computed-and-discarded outside the "
        "clean-exit branch."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt009_unit_and_phase_loops_accumulate_every_round(wf_path: Path) -> None:
    content = _read(wf_path)
    unit = _unit_redteam_section(content, wf_path)
    phase_section = _phase_redteam_section(content, wf_path)
    assert "accumulateNonBlocking(groupNonBlocking, groupNonBlockingSigs, rt.findings)" in unit, (
        f"{wf_path.name}: unit redteam loop must accumulate every round's non-blocking findings, "
        "not only the round the loop happens to exit clean on."
    )
    assert "accumulateNonBlocking(phaseNonBlocking, phaseNonBlockingSigs, rt.findings)" in phase_section, (
        f"{wf_path.name}: phase redteam loop must accumulate every round's non-blocking "
        "findings, not only the round the loop happens to exit clean on."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt009_unit_medium_low_note_reachable_from_every_break(wf_path: Path) -> None:
    """The medium-low deferred note must be written from ONE place positioned AFTER the
    while(true) loop closes, not nested inside the clean-exit `if` branch — otherwise only
    the clean-exit break reaches it, and the null-gate/findings-mismatch/round-budget/
    tests-red breaks (which all exit the same loop) silently drop that round's non-blocking
    findings."""
    unit = _unit_redteam_section(_read(wf_path), wf_path)
    marker = "-group-' + group.label + '-medium-low.md"
    assert marker in unit, f"{wf_path.name}: unit medium-low deferred note not found."
    assert not _write_is_inside_clean_exit_branch(unit, marker), (
        f"{wf_path.name}: the unit medium-low deferred note is nested inside the "
        "`if (blocking.length === 0)` clean-exit branch — it must be written once after "
        "the while(true) loop closes so every break path (null-gate, findings-mismatch, "
        "round-budget, tests-red) reaches it."
    )
    assert unit.count(marker) == 1, (
        f"{wf_path.name}: expected exactly one unit medium-low deferred-note call site "
        "(written once per group, after the loop) — not one per exit path."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt009_phase_medium_low_note_reachable_from_every_break(wf_path: Path) -> None:
    """Mirrors test_rt009_unit_medium_low_note_reachable_from_every_break for the full-wave
    phase redteam loop."""
    phase_section = _phase_redteam_section(_read(wf_path), wf_path)
    marker = "-phase-medium-low.md"
    assert marker in phase_section, f"{wf_path.name}: phase medium-low deferred note not found."
    assert not _write_is_inside_clean_exit_branch(phase_section, marker), (
        f"{wf_path.name}: the phase medium-low deferred note is nested inside the "
        "`if (blocking.length === 0)` clean-exit branch — it must be written once after "
        "the while(true) loop closes so every break path reaches it."
    )
    assert phase_section.count(marker) == 1, (
        f"{wf_path.name}: expected exactly one phase medium-low deferred-note call site "
        "(written once, after the loop) — not one per exit path."
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
def test_rt001_unit_budget_exit_captures_codify_findings_before_break(wf_path: Path) -> None:
    unit = _unit_redteam_section(_read(wf_path), wf_path)
    push_idx = unit.find("allHighFindings.push.apply(allHighFindings, highFindings)")
    budget_log_idx = unit.find("Round budget exhausted for group")
    assert push_idx != -1, f"{wf_path.name}: unit loop never pushes highFindings into allHighFindings."
    assert budget_log_idx != -1, f"{wf_path.name}: unit round-budget exit log message not found."
    assert push_idx < budget_log_idx, (
        f"{wf_path.name}: allHighFindings.push.apply(...) must run BEFORE the uRound >= 5 "
        "round-budget break — codify accumulation positioned after the break is unreachable "
        "from that exit path, silently dropping surviving critical/high findings from the "
        "Codify LRN pass and SDK-issue scan."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt001_phase_budget_exit_captures_codify_findings_before_break(wf_path: Path) -> None:
    phase_section = _phase_redteam_section(_read(wf_path), wf_path)
    push_idx = phase_section.find("allHighFindings.push.apply(allHighFindings, highFindings)")
    budget_log_idx = phase_section.find("Phase round budget exhausted")
    assert push_idx != -1, f"{wf_path.name}: phase loop never pushes highFindings into allHighFindings."
    assert budget_log_idx != -1, f"{wf_path.name}: phase round-budget exit log message not found."
    assert push_idx < budget_log_idx, (
        f"{wf_path.name}: allHighFindings.push.apply(...) must run BEFORE the pRound >= 8 "
        "round-budget break — codify accumulation positioned after the break is unreachable "
        "from that exit path, silently dropping surviving critical/high findings from the "
        "Codify LRN pass and SDK-issue scan."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt001_phase_budget_exit_writes_deferred_note(wf_path: Path) -> None:
    """The phase round-cap exit must write a durable deferred note — the exact gap RT-001
    found in sdk-wave.js: 'continuing to Protocol Audit' with no artifact at all."""
    phase_section = _phase_redteam_section(_read(wf_path), wf_path)
    budget_log_idx = phase_section.find("Phase round budget exhausted")
    assert budget_log_idx != -1, f"{wf_path.name}: phase round-budget exit log message not found."
    window = phase_section[budget_log_idx : budget_log_idx + 1200]
    assert "-phase-budget-exhausted.md" in window, (
        f"{wf_path.name}: the phase round-budget exit must write a deferred note "
        "(<wave>-phase-budget-exhausted.md) — a bare log() with no durable artifact loses the "
        "surviving critical/high findings' paper trail."
    )
    assert "JSON.stringify(rt.findings, null, 2)" in window, (
        f"{wf_path.name}: the phase round-budget deferred note must include the round's full "
        "findings."
    )


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
def test_rt001_unit_and_phase_budget_exit_set_blocking_flags(wf_path: Path) -> None:
    content = _read(wf_path)
    unit = _unit_redteam_section(content, wf_path)
    phase_section = _phase_redteam_section(content, wf_path)

    unit_budget_log_idx = unit.find("Round budget exhausted for group")
    assert unit_budget_log_idx != -1, f"{wf_path.name}: unit round-budget exit log message not found."
    unit_window = unit[unit_budget_log_idx : unit_budget_log_idx + 1200]
    assert "unitBudgetBlocked = true" in unit_window, (
        f"{wf_path.name}: the unit round-budget exit must set unitBudgetBlocked — a group "
        "exiting round 5 with surviving critical/high findings must not let the wave archive "
        "as if clean."
    )
    assert "protocolBlocked = true" in unit_window, (
        f"{wf_path.name}: the unit round-budget exit must fold into protocolBlocked so the "
        "existing archive gate actually stops the wave."
    )

    phase_budget_log_idx = phase_section.find("Phase round budget exhausted")
    assert phase_budget_log_idx != -1, f"{wf_path.name}: phase round-budget exit log message not found."
    phase_window = phase_section[phase_budget_log_idx : phase_budget_log_idx + 1200]
    assert "phaseBudgetBlocked = true" in phase_window, (
        f"{wf_path.name}: the phase round-budget exit must set phaseBudgetBlocked — reaching "
        "the round cap now signals surviving critical/high findings (GH-132 severity floor), "
        "not a leftover low nit, and must not let the wave archive as if clean."
    )
    assert "protocolBlocked = true" in phase_window, (
        f"{wf_path.name}: the phase round-budget exit must fold into protocolBlocked so the "
        "existing archive gate actually stops the wave."
    )


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


@pytest.mark.parametrize("wf_path", GH132_LOOP_LOGIC_FILES, ids=GH132_LOOP_LOGIC_IDS)
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

_WAVE_SCHEMA_BLOCK_RE = re.compile(r"const WAVE_SCHEMA\s*=\s*\{.*?\n\}\n", re.DOTALL)

_PARSE_PROMPT_RE = re.compile(
    r"const wave\s*=\s*await callAgent\((.*?)"
    r"\{\s*schema:\s*WAVE_SCHEMA,\s*label:\s*'parse'",
    re.DOTALL,
)

_ARCHIVE_MOVE_PROMPT_RE = re.compile(
    r"('Archive wave '\s*\+\s*wave\.waveId\s*\+\s*'\. Perform in order:.*?)"
    r"\{\s*label:\s*'archive',\s*phase:\s*'Archive'",
    re.DOTALL,
)


def _wave_schema_block(content: str, wf_path: Path) -> str:
    match = _WAVE_SCHEMA_BLOCK_RE.search(content)
    assert match, f"{wf_path.name}: could not locate the WAVE_SCHEMA block."
    return match.group(0)


def _parse_prompt(content: str, wf_path: Path) -> str:
    match = _PARSE_PROMPT_RE.search(content)
    assert match, (
        f"{wf_path.name}: could not locate the `const wave = await callAgent(...)` "
        "Parse-phase call — cannot anchor prompt-content assertions to it."
    )
    return match.group(1)


def _archive_move_prompt(content: str, wf_path: Path) -> str:
    match = _ARCHIVE_MOVE_PROMPT_RE.search(content)
    assert match, (
        f"{wf_path.name}: could not locate the archive-step "
        "'Archive wave ' + wave.waveId + '. Perform in order:' callAgent prompt."
    )
    return match.group(1)


@pytest.mark.parametrize("wf_path", RT004_FILES, ids=RT004_FILES_IDS)
def test_w039_wave_schema_has_completed_file_exists_in_required(wf_path: Path) -> None:
    """WAVE_SCHEMA.required must include 'completedFileExists' — without it the parse
    agent is not constrained to return the field and the collision gate below can never
    fire."""
    schema_match = re.search(
        r"const WAVE_SCHEMA\s*=\s*\{.*?required:\s*\[([^\]]*)\]", _read(wf_path), re.DOTALL
    )
    assert schema_match, f"{wf_path.name}: WAVE_SCHEMA not found or has no 'required' array"
    required_array = schema_match.group(1)
    assert "completedFileExists" in required_array, (
        f"{wf_path.name}: 'completedFileExists' is missing from WAVE_SCHEMA.required. "
        f"Required array found: {required_array!r}"
    )


@pytest.mark.parametrize("wf_path", RT004_FILES, ids=RT004_FILES_IDS)
def test_w039_wave_schema_has_completed_file_exists_boolean_property(wf_path: Path) -> None:
    """WAVE_SCHEMA.properties must define 'completedFileExists' as a boolean, anchored to
    the schema block itself so a stray comment mention elsewhere can't substitute."""
    schema_block = _wave_schema_block(_read(wf_path), wf_path)
    assert re.search(r"completedFileExists:\s*\{\s*type:\s*'boolean'", schema_block), (
        f"{wf_path.name}: 'completedFileExists' boolean property not found inside "
        "WAVE_SCHEMA."
    )


@pytest.mark.parametrize("wf_path", RT004_FILES, ids=RT004_FILES_IDS)
def test_w039_parse_prompt_checks_completed_dir_unconditionally(wf_path: Path) -> None:
    """The Parse-phase prompt must instruct the agent to determine completedFileExists via
    an unconditional `test -f workspace/todos/completed/<basename>` check, mirroring how
    templateDirExists is determined unconditionally in the archive-commit gate."""
    prompt = _parse_prompt(_read(wf_path), wf_path)
    for expected in ["test -f workspace/todos/completed/", "UNCONDITIONALLY", "completedFileExists"]:
        assert expected in prompt, (
            f"{wf_path.name}: Parse-phase prompt missing {expected!r} — the "
            "completedFileExists check is not instructed unconditionally."
        )


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


@pytest.mark.parametrize("wf_path", RT004_FILES, ids=RT004_FILES_IDS)
def test_rt001_parse_prompt_scans_full_creates_line_for_every_backticked_path(wf_path: Path) -> None:
    """The Parse-phase prompt must instruct the agent to scan the WHOLE Creates: line
    for every backticked path token, not just extract "the" path — and must name the
    parenthetical "(modifies ...)" prose form as the dominant shape, with a worked
    example, so a literal-compliant agent cannot stop at the first token."""
    prompt = _parse_prompt(_read(wf_path), wf_path)
    for expected in [
        "backticked",
        "(modifies ...)",
        "NEVER stop at the first backticked",
        "adds `x`",
    ]:
        assert expected in prompt, (
            f"{wf_path.name}: Parse-phase prompt missing {expected!r} — the RT-001 "
            "under-extraction fix is missing or incomplete."
        )


@pytest.mark.parametrize("wf_path", RT004_FILES, ids=RT004_FILES_IDS)
def test_rt001_wave_schema_allcreates_allmodifies_document_dominant_prose_form(wf_path: Path) -> None:
    """WAVE_SCHEMA's allCreates/allModifies properties must carry a description naming
    the parenthetical prose form as dominant — a reader of the schema alone (without
    the Extract prose) must be able to tell a bare-path Creates: line is the minority
    case."""
    schema_block = _wave_schema_block(_read(wf_path), wf_path)
    for prop in ["allCreates", "allModifies"]:
        match = re.search(
            rf"{prop}:\s*\{{.*?description:\s*'([^']*)'", schema_block, re.DOTALL
        )
        assert match, (
            f"{wf_path.name}: could not locate a description on WAVE_SCHEMA.{prop} — "
            "RT-001 (fix round) requires one naming the dominant parenthetical prose form."
        )
        description = match.group(1)
        assert "RT-001" in description, (
            f"{wf_path.name}: WAVE_SCHEMA.{prop} description does not cite RT-001. "
            f"Description found: {description!r}"
        )


@pytest.mark.parametrize("wf_path", RT004_FILES, ids=RT004_FILES_IDS)
def test_w039_wave_id_collision_hard_block_present(wf_path: Path) -> None:
    """`if (wave.completedFileExists)` must appear between the Parse-phase agent call and
    the rest of the workflow, and must `return` an error object (not merely log) — a wave
    reusing an already-archived basename must not proceed to Implement."""
    content = _read(wf_path)
    match = re.search(
        r"if \(wave\.completedFileExists\) \{(.*?)\n\}",
        content,
        re.DOTALL,
    )
    assert match, f"{wf_path.name}: 'if (wave.completedFileExists)' hard-block not found."
    block = match.group(1)
    assert "return {" in block and "'wave-id-collision'" in block, (
        f"{wf_path.name}: the completedFileExists block does not return an "
        "'wave-id-collision' error object — a bare log() would let the wave proceed."
    )


@pytest.mark.parametrize("wf_path", RT004_FILES, ids=RT004_FILES_IDS)
def test_w039_wave_id_collision_gate_precedes_scope_union(wf_path: Path) -> None:
    """The completedFileExists hard-block must run before wave.allScope is computed (and
    therefore before Implement can start) — catching the collision only after other
    Parse-phase work has already run wastes the work this gate exists to avoid."""
    content = _read(wf_path)
    gate_pos = content.find("if (wave.completedFileExists)")
    scope_pos = content.find("wave.allCreates  = uniq(wave.allCreates)")
    assert gate_pos != -1, f"{wf_path.name}: completedFileExists gate not found."
    assert scope_pos != -1, f"{wf_path.name}: allScope union line not found."
    assert gate_pos < scope_pos, (
        f"{wf_path.name}: the completedFileExists hard-block must precede the "
        "allCreates/allModifies/allScope union, not follow it."
    )


@pytest.mark.parametrize("wf_path", RT004_FILES, ids=RT004_FILES_IDS)
def test_w039_archive_move_prompt_checks_before_overwriting(wf_path: Path) -> None:
    """The archive step's move instruction must check whether the destination already
    exists and refuse to overwrite it, as a defense-in-depth fallback behind the
    Parse-phase hard-block (e.g. a destination created by a concurrent process after
    Parse ran)."""
    prompt = _archive_move_prompt(_read(wf_path), wf_path)
    normalized = _normalize_ws(prompt)
    assert "already exists" in normalized, (
        f"{wf_path.name}: archive move instruction does not check whether the destination "
        "already exists."
    )
    assert "do NOT move or overwrite it" in normalized, (
        f"{wf_path.name}: archive move instruction does not explicitly forbid overwriting "
        "an existing destination file."
    )


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_MIRRORS, ids=WAVE_CYCLE_MIRROR_IDS)
def test_w039_lrn100_sweep_checks_before_overwriting(wf_path: Path) -> None:
    """wave-cycle.js's step-4 LRN-100 relocation sweep moves resolved deferred markers to
    completed/ by basename too — it must not overwrite an existing destination file
    either, mirroring the step-1 move-instruction fix. sdk-wave.js has no step 4 (it does
    not implement the LRN-100 sweep), so this is scoped to the three wave-cycle.js
    mirrors only."""
    prompt = _archive_move_prompt(_read(wf_path), wf_path)
    normalized = _normalize_ws(prompt)
    assert "LRN-100 relocation sweep" in normalized, (
        f"{wf_path.name}: step-4 LRN-100 relocation sweep not found in the archive prompt."
    )
    assert "do NOT overwrite it" in normalized, (
        f"{wf_path.name}: step-4 LRN-100 relocation sweep does not forbid overwriting an "
        "existing workspace/todos/completed/ destination for a relocated deferred marker."
    )


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
def test_rt011_unit_loop_pushes_all_blocking_findings_not_just_codified(wf_path: Path) -> None:
    unit = _unit_redteam_section(_read(wf_path), wf_path)
    assert "const highFindings = blocking.filter(function(f) { return f.codify })" not in unit, (
        f"{wf_path.name}: the unit loop must not filter blocking findings on f.codify before "
        "pushing into allHighFindings — a critical/high finding missing the required Codify: "
        "line would be silently dropped from the Codify LRN pass and the SDK issue scan."
    )
    assert "const highFindings = blocking\n" in unit, (
        f"{wf_path.name}: the unit loop must push EVERY blocking (critical/high) finding into "
        "allHighFindings, not a codify-filtered subset."
    )
    push_idx = unit.find("allHighFindings.push.apply(allHighFindings, highFindings)")
    assert push_idx != -1, f"{wf_path.name}: unit loop never pushes highFindings into allHighFindings."


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_MIRRORS, ids=WAVE_CYCLE_MIRROR_IDS)
def test_rt011_unit_loop_warns_by_name_on_missing_codify(wf_path: Path) -> None:
    unit = _unit_redteam_section(_read(wf_path), wf_path)
    assert "missingCodify" in unit, (
        f"{wf_path.name}: the unit loop must compute which blocking findings lack a Codify: "
        "line (missingCodify), even though they are no longer dropped from allHighFindings."
    )
    warn_idx = unit.find("WARNING: ' + missingCodify.length")
    assert warn_idx != -1, (
        f"{wf_path.name}: a critical/high finding missing a Codify: line must be logged by "
        "name (f.id) so the gap stays visible instead of silent."
    )
    assert "missingCodify.map(function(f) { return f.id })" in unit, (
        f"{wf_path.name}: the missing-codify warning must name each offending finding by id."
    )


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_MIRRORS, ids=WAVE_CYCLE_MIRROR_IDS)
def test_rt011_phase_loop_pushes_all_blocking_findings_not_just_codified(wf_path: Path) -> None:
    phase_section = _phase_redteam_section(_read(wf_path), wf_path)
    assert "const highFindings = blocking.filter(function(f) { return f.codify })" not in phase_section, (
        f"{wf_path.name}: the phase loop must not filter blocking findings on f.codify before "
        "pushing into allHighFindings — see the unit-loop RT-011 test for the failure mode."
    )
    assert "const highFindings = blocking\n" in phase_section, (
        f"{wf_path.name}: the phase loop must push EVERY blocking (critical/high) finding into "
        "allHighFindings, not a codify-filtered subset."
    )
    push_idx = phase_section.find("allHighFindings.push.apply(allHighFindings, highFindings)")
    assert push_idx != -1, f"{wf_path.name}: phase loop never pushes highFindings into allHighFindings."


@pytest.mark.parametrize("wf_path", WAVE_CYCLE_MIRRORS, ids=WAVE_CYCLE_MIRROR_IDS)
def test_rt011_phase_loop_warns_by_name_on_missing_codify(wf_path: Path) -> None:
    phase_section = _phase_redteam_section(_read(wf_path), wf_path)
    assert "missingCodify" in phase_section, (
        f"{wf_path.name}: the phase loop must compute which blocking findings lack a Codify: "
        "line (missingCodify), even though they are no longer dropped from allHighFindings."
    )
    assert "WARNING: ' + missingCodify.length" in phase_section, (
        f"{wf_path.name}: a critical/high finding missing a Codify: line must be logged by "
        "name so the gap stays visible instead of silent."
    )


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

# The fail-closed fold: count the nulls BEFORE discarding them.
_NULL_COUNT_FOLD_RE = re.compile(r"\.filter\(function\(r\)\s*\{\s*return\s*!r\s*\}\)\.length")


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


@pytest.mark.parametrize("wf_path", RT004_FILES, ids=RT004_FILES_IDS)
def test_rt001_both_advisor_fanouts_count_nulls_and_block(wf_path: Path) -> None:
    """Both protocol fan-outs (initial audit + post-fix recheck) must count null advisor
    results and block archive. The recheck site matters most: a null there drops the
    verdict on a protocol that ALREADY had a critical finding, so protoCritical
    recomputes to 0 and the wave archives as though the fix had been verified."""
    code = _strip_comments_and_strings(_read(wf_path))
    folds = list(_NULL_COUNT_FOLD_RE.finditer(code))
    assert len(folds) >= 2, (
        f"{wf_path.name}: expected a null-counting fold at BOTH the initial advisor "
        f"fan-out and the recheck fan-out, found {len(folds)}."
    )
    for fold in folds:
        window = code[fold.end() : fold.end() + 400]
        assert "protocolBlocked = true" in window, (
            f"{wf_path.name}: a null-advisor count at offset {fold.start()} does not set "
            "protocolBlocked = true — counting the nulls without blocking archive leaves "
            "the fail-open intact."
        )
