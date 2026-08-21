"""CI sync-check: workflow files shipped in both .claude/workflows/ (runtime) and
harness/workflows/ (template/propagation source) MUST stay byte-identical.

RT-003 fix: the two copies of wave-cycle.js silently diverged across ~10 behaviors
(null-gate fail-closed guards, recheck guard, deferred notes, archive row-append).
Whenever a fix lands in one copy but not the other, it is silently un-applied for
whichever copy actually runs. This test fails the moment the copies drift, so the
divergence can never recur unnoticed.

Three sync axes are guarded:

1. .claude/workflows/ ↔ harness/workflows/ (runtime ↔ propagation source) — files
   present in BOTH directories must be byte-identical.

2. harness/workflows/ ↔ template/.claude/workflows/ (harness ↔ peer-repo template) —
   files that live only in harness/ but are propagated to the template repo must also
   stay byte-identical. acceptance-api.js is the canonical example: it is absent from
   .claude/workflows/ (no runtime copy here) but IS propagated to template/. Without
   this second axis the intersection-only check silently skips it, creating exactly the
   split-brain failure mode warned against in LRN-067/LRN-065.

3. .claude/agents/core/ ↔ harness/agents/core/ (RT-007, w036) — the core agent
   definitions (redteam, analyst, planner, codify, debug) match today by convention
   only, with no test pinning them: a wave edited .claude/agents/core/redteam.md and
   harness/agents/core/redteam.md in lockstep by hand, but nothing would have caught
   it landing in only one copy. Same failure class as axis 1, one directory over.

RT-002 fix: the axis-2 presence guard (test_acceptance_api_is_harness_template_shared)
must never be silenced when template/ is absent from the checkout. It is marked xfail,
not skip, when template/ is missing — the assertion still runs and still fails, so the
"propagation unverified" state stays visible in the pytest summary (and turns into a
loud, strict XPASS failure if the guard is ever satisfied without the peer repo present).
Only the byte-identity parametrize case is allowed to fall out silently when template/ is
absent, since its parameter set (HARNESS_TEMPLATE_SHARED) is legitimately empty then.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
RUNTIME_DIR = REPO_ROOT / ".claude" / "workflows"
HARNESS_DIR = REPO_ROOT / "harness" / "workflows"
TEMPLATE_DIR = REPO_ROOT / "template" / ".claude" / "workflows"
CORE_AGENTS_RUNTIME_DIR = REPO_ROOT / ".claude" / "agents" / "core"
CORE_AGENTS_HARNESS_DIR = REPO_ROOT / "harness" / "agents" / "core"

# Axis 1: files present in both .claude/workflows/ and harness/workflows/
_runtime_names = {p.name for p in RUNTIME_DIR.glob("*.js")}
_harness_names = {p.name for p in HARNESS_DIR.glob("*.js")}
SHARED = sorted(_runtime_names & _harness_names)

# Axis 2: files present in both harness/workflows/ and template/.claude/workflows/
_template_names = {p.name for p in TEMPLATE_DIR.glob("*.js")} if TEMPLATE_DIR.exists() else set()
HARNESS_TEMPLATE_SHARED = sorted(_harness_names & _template_names)

# Axis 3 (RT-007): files present in both .claude/agents/core/ and harness/agents/core/
_core_agents_runtime_names = {p.name for p in CORE_AGENTS_RUNTIME_DIR.glob("*.md")}
_core_agents_harness_names = {p.name for p in CORE_AGENTS_HARNESS_DIR.glob("*.md")}
CORE_AGENTS_SHARED = sorted(_core_agents_runtime_names & _core_agents_harness_names)


def test_wave_cycle_is_shared() -> None:
    """Guard: wave-cycle.js must be present in both dirs (it is the core wave runner).

    If this fails, one copy was deleted/renamed — investigate before trusting the
    sync test below, which would otherwise silently skip the most important file.
    """
    assert "wave-cycle.js" in SHARED, (
        "wave-cycle.js missing from .claude/workflows/ or harness/workflows/ — "
        f"shared workflow files found: {SHARED}"
    )


@pytest.mark.xfail(
    not TEMPLATE_DIR.exists(),
    reason=(
        "peer repo not checked out — propagation unverified: template/ "
        "(wailuen/a2a-agent-template, LRN-071) is absent from this working tree, "
        "so the harness↔template propagation axis cannot be evaluated locally. "
        "This must pass wherever template/ is present (e.g. CI with the peer repo "
        "cloned) — an XPASS there means the axis is verified; leaving this on "
        "xfail keeps the unverifiable state visible in the run summary instead of "
        "silently skipping it."
    ),
    strict=True,
)
def test_acceptance_api_is_harness_template_shared() -> None:
    """Guard: acceptance-api.js must be present in both harness/ and template/ dirs.

    acceptance-api.js is absent from .claude/workflows/ (no local runtime copy) but
    IS propagated to template/.claude/workflows/. If this fails, it was removed from
    one side without updating the other — investigate before the propagation axis
    check below silently shrinks.

    This assertion always runs (it is never skipped): when template/ is absent it
    is expected to fail (xfail, above) as the loud, still-visible signal that the
    propagation axis is unverifiable in this checkout; when template/ is present
    it must pass as a hard assertion.
    """
    assert "acceptance-api.js" in HARNESS_TEMPLATE_SHARED, (
        "acceptance-api.js missing from harness/workflows/ or "
        "template/.claude/workflows/ — "
        f"harness↔template shared workflow files found: {HARNESS_TEMPLATE_SHARED}"
    )


@pytest.mark.xfail(
    not TEMPLATE_DIR.exists(),
    reason=(
        "peer repo not checked out — propagation unverified: template/ "
        "(wailuen/a2a-agent-template, LRN-071) is absent from this working tree, "
        "so the harness↔template propagation axis cannot be evaluated locally. "
        "This must pass wherever template/ is present (e.g. CI with the peer repo "
        "cloned) — an XPASS there means the axis is verified; leaving this on "
        "xfail keeps the unverifiable state visible in the run summary instead of "
        "silently skipping it."
    ),
    strict=True,
)
def test_wave_cycle_is_harness_template_shared() -> None:
    """RT-003: wave-cycle.js is the core wave runner — GH-131 and GH-132 both declared
    template/.claude/workflows/wave-cycle.js in Modifies:, yet template/ is gitignored
    (LRN-071) and can be absent from a local checkout. Without this guard, the
    _existing_wf_files()-style parametrize helpers in test_workflows.py silently drop the
    missing template path from every GH-131/GH-132 parametrization, so a wave that forgets
    to propagate a wave-cycle.js fix into the peer-repo template still runs fully green —
    the exact split-brain failure mode axis 2 exists to catch (see acceptance-api.js above),
    just never pinned for the single most important file it protects.

    Mirrors test_acceptance_api_is_harness_template_shared exactly: this assertion always
    runs (never skipped); it is expected to fail (xfail, above) when template/ is absent, so
    the "propagation unverified" state stays visible in the run summary instead of silently
    dropping out; it must pass as a hard assertion once template/ is present with
    wave-cycle.js propagated into it.
    """
    assert "wave-cycle.js" in HARNESS_TEMPLATE_SHARED, (
        "wave-cycle.js missing from harness/workflows/ or template/.claude/workflows/ — "
        f"harness↔template shared workflow files found: {HARNESS_TEMPLATE_SHARED}"
    )


@pytest.mark.parametrize("name", SHARED)
def test_runtime_and_harness_copies_are_identical(name: str) -> None:
    runtime = (RUNTIME_DIR / name).read_text()
    harness = (HARNESS_DIR / name).read_text()
    assert runtime == harness, (
        f".claude/workflows/{name} and harness/workflows/{name} have diverged. "
        "These two copies must be byte-identical — a fix landing in only one copy "
        "is silently un-applied for the other. Reconcile into a single superset "
        "(diff the files to find the drift)."
    )


@pytest.mark.parametrize("name", HARNESS_TEMPLATE_SHARED)
def test_harness_and_template_copies_are_identical(name: str) -> None:
    harness = (HARNESS_DIR / name).read_text()
    template = (TEMPLATE_DIR / name).read_text()
    assert harness == template, (
        f"harness/workflows/{name} and template/.claude/workflows/{name} have diverged. "
        "These two copies must be byte-identical — a fix landing in only one copy "
        "is silently un-applied in the peer repo. Reconcile into a single superset "
        "(diff the files to find the drift), then copy the result to both locations."
    )


def test_redteam_agent_is_core_agents_shared() -> None:
    """Guard: redteam.md must be present in both .claude/agents/core/ and
    harness/agents/core/ (it is the agent the RT-007 finding was filed against).

    If this fails, one copy was deleted/renamed — investigate before trusting the
    axis-3 sync test below, which would otherwise silently skip it.
    """
    assert "redteam.md" in CORE_AGENTS_SHARED, (
        "redteam.md missing from .claude/agents/core/ or harness/agents/core/ — "
        f"shared core agent files found: {CORE_AGENTS_SHARED}"
    )


@pytest.mark.parametrize("name", CORE_AGENTS_SHARED)
def test_core_agent_runtime_and_harness_copies_are_identical(name: str) -> None:
    """RT-007: .claude/agents/core/ and harness/agents/core/ matched only by convention,
    with no test pinning them — a fix landing in only one copy (e.g. redteam.md's
    peerRepoAnnotations addition) would silently un-apply for whichever copy actually
    runs. Same failure class, and same fix shape, as test_runtime_and_harness_copies_are_
    identical above for .claude/workflows/ ↔ harness/workflows/.
    """
    runtime = (CORE_AGENTS_RUNTIME_DIR / name).read_text()
    harness = (CORE_AGENTS_HARNESS_DIR / name).read_text()
    assert runtime == harness, (
        f".claude/agents/core/{name} and harness/agents/core/{name} have diverged. "
        "These two copies must be byte-identical — a fix landing in only one copy "
        "is silently un-applied for the other. Reconcile into a single superset "
        "(diff the files to find the drift)."
    )


# ---------------------------------------------------------------------------
# Axis 4 (RT-008, round-5 fresh-lens debug): .claude/skills/<name>/SKILL.md ↔
# harness/skills/<name>/SKILL.md.
#
# Same drift class axis 3 closed for .claude/agents/core/ — one directory over,
# and the larger one: 20 skills ship in both trees. Nothing pinned them.
#
# These two directories are NOT wholesale byte-identical, and must not be made so.
# Four skills are deliberately context-divergent, because .claude/ drives waves in
# the a2a-sdk repo itself while harness/ is the copy propagated to downstream agent
# repos: `wave` (launches sdk-wave.js vs wave-cycle.js; agent_sdk/routes vs
# src/routes; /sdk-test vs /agent-verify), `implement`, `codify`, and `acceptance`.
# Every OTHER shared skill is byte-identical today and has no reason not to be, so
# the axis pins the identical set and requires each divergence to be declared here
# — which turns a silent drift into a one-line, reviewable decision.
#
# DELIBERATELY_DIVERGENT_SKILLS is an allow-list, not a skip-list: a name may only
# be added alongside the reason it is context-specific. Adding one to silence a
# failure re-opens exactly the gap this axis exists to close.
# ---------------------------------------------------------------------------

SKILLS_RUNTIME_DIR = REPO_ROOT / ".claude" / "skills"
SKILLS_HARNESS_DIR = REPO_ROOT / "harness" / "skills"

DELIBERATELY_DIVERGENT_SKILLS = {
    # .claude/ launches sdk-wave.js for this repo; harness/ launches wave-cycle.js
    # for downstream agents (GH-132/RT-002). Also diverges on source-root dialect
    # (agent_sdk/routes vs src/routes) and the post-block verification command
    # (/sdk-test vs /agent-verify). Shared loop-control invariants are pinned
    # separately below.
    "wave",
    # SDK-context implementer (python-implementer over agent_sdk/) vs the
    # downstream agent implementer.
    "implement",
    # SDK learnings are filed against agent_sdk/; agent learnings against src/.
    "codify",
    # RT-004 (round 5): "acceptance" was exempted here on the rationale that the
    # SDK copy drives the alphageo example while the harness copy drives a
    # provisioned downstream agent. That exemption was load-bearing in the wrong
    # direction: under it the two copies drifted into a HALF-reconciled GH-89/SI-2
    # security fix — the .claude/ copy still interpolated the resolved admin key
    # as `adminKey:` into a Workflow input (and thus into harness transcripts),
    # while only harness/ had the chmod-600 keyFile externalisation. The run-context
    # difference the rationale describes is already carried INSIDE the file, by the
    # "Path note" comment above scriptPath, so it never needed a whole-file
    # exemption. Reconciled and re-pinned to the byte-identity axis.
}

_skills_runtime_names = {
    p.parent.name for p in SKILLS_RUNTIME_DIR.glob("*/SKILL.md")
}
_skills_harness_names = {
    p.parent.name for p in SKILLS_HARNESS_DIR.glob("*/SKILL.md")
}
SKILLS_SHARED = sorted(_skills_runtime_names & _skills_harness_names)
SKILLS_PINNED = [n for n in SKILLS_SHARED if n not in DELIBERATELY_DIVERGENT_SKILLS]


def test_wave_skill_is_shared() -> None:
    """Guard: wave/SKILL.md must exist in both skill trees — it is the entry point
    both runners are launched from. If this fails, the parity assertions below are
    silently skipping the file the RT-008 finding was filed against."""
    assert "wave" in SKILLS_SHARED, (
        "wave/SKILL.md missing from .claude/skills/ or harness/skills/ — "
        f"shared skills found: {SKILLS_SHARED}"
    )


def test_divergent_skill_allowlist_is_not_stale() -> None:
    """Every name on the allow-list must actually exist in both trees AND actually
    differ. An entry that no longer diverges is a stale exemption suppressing a real
    guard — the same fail-open shape LRN-020/LRN-022 codify."""
    for name in sorted(DELIBERATELY_DIVERGENT_SKILLS):
        assert name in SKILLS_SHARED, (
            f"DELIBERATELY_DIVERGENT_SKILLS names {name!r}, which is not present in "
            "both .claude/skills/ and harness/skills/ — remove the stale entry."
        )
        runtime = (SKILLS_RUNTIME_DIR / name / "SKILL.md").read_text()
        harness = (SKILLS_HARNESS_DIR / name / "SKILL.md").read_text()
        assert runtime != harness, (
            f"{name}/SKILL.md is on DELIBERATELY_DIVERGENT_SKILLS but the two copies "
            "are now identical. Remove it from the allow-list so the byte-identity "
            "axis guards it — a stale exemption is an un-guarded file."
        )


@pytest.mark.parametrize("name", SKILLS_PINNED)
def test_skill_runtime_and_harness_copies_are_identical(name: str) -> None:
    """RT-008: .claude/skills/ ↔ harness/skills/ matched by convention only, with no
    test pinning them — the same gap axis 3 was added to close for
    .claude/agents/core/. An edit landing in one copy is silently un-applied for
    whichever tree actually runs.
    """
    runtime = (SKILLS_RUNTIME_DIR / name / "SKILL.md").read_text()
    harness = (SKILLS_HARNESS_DIR / name / "SKILL.md").read_text()
    assert runtime == harness, (
        f".claude/skills/{name}/SKILL.md and harness/skills/{name}/SKILL.md have "
        "diverged. Either reconcile them, or — if the divergence is genuinely "
        "context-specific (SDK repo vs downstream agent repo) — add the name to "
        "DELIBERATELY_DIVERGENT_SKILLS above WITH the reason."
    )


# The loop-control contract inside wave/SKILL.md is shared behaviour, not context:
# both runners implement the same severity floor, the same round caps, and the same
# debug-replaces-fix-fan-out rule, and this wave edited both copies by hand in
# lockstep. Byte-identity cannot guard it (the files legitimately differ elsewhere),
# so pin the invariants themselves.
WAVE_SKILL_SHARED_INVARIANTS = [
    "critical/high",          # the GH-132 severity floor
    # RT-014: "round 4+" overstated the unit loop, whose round-budget exit (uRound >= 5)
    # runs BEFORE the escalateToDebug check (uRound > 3 || stalled) — so debug can only
    # ever fire at exactly round 4 there, never round 5+. "4+" is only accurate for the
    # phase loop (rounds 4-7, since pRound >= 8 exits first) — see wave-cycle.js's Phase
    # Redteam description, which keeps "round 4+" unchanged.
    "round 4 (the only round above the fix-fan-out threshold before the round-5 deferred exit)",  # debug trigger round (unit loop)
    "REPLACES the fix fan-out",  # debug replaces, never runs alongside
    "Max 5 rounds",           # unit loop cap
    "max 8 rounds",           # phase loop cap
    "agentBudget",            # the agent-call ceiling override
]


@pytest.mark.parametrize("invariant", WAVE_SKILL_SHARED_INVARIANTS)
def test_wave_skill_loop_control_invariants_present_in_both_copies(invariant: str) -> None:
    """RT-008: wave/SKILL.md is exempt from byte-identity (it launches a different
    runner per tree), which leaves the ~95% of the file that IS shared unguarded.
    These loop-control invariants are that shared part — a severity floor, two round
    caps, the debug-replaces-fan-out rule, and the agent-call ceiling — all edited in
    lockstep by hand. Pinning them means an edit to one copy's shared prose fails the
    build instead of silently applying to only one tree.
    """
    for label, path in (
        (".claude", SKILLS_RUNTIME_DIR / "wave" / "SKILL.md"),
        ("harness", SKILLS_HARNESS_DIR / "wave" / "SKILL.md"),
    ):
        # Whitespace-normalized: the two copies wrap their prose at different
        # points, so an invariant may straddle a line break in one and not the
        # other. The rule is what must match, not the line wrapping.
        text = " ".join(path.read_text().split())
        assert invariant in text, (
            f"{label}/skills/wave/SKILL.md no longer states the shared loop-control "
            f"invariant {invariant!r}. The two copies are deliberately divergent on "
            "scriptPath only — the loop contract must stay in lockstep."
        )


# ---------------------------------------------------------------------------
# Axis 5: harness/skills/setup/SKILL.md ↔ template/.claude/skills/setup/SKILL.md
#
# Same drift class as axis 2 (harness/workflows/ ↔ template/.claude/workflows/),
# one directory over: /setup only exists in the harness→template direction (there
# is no .claude/skills/setup/ in this repo — /setup only makes sense inside a
# freshly-cloned template checkout, so axis 4 above cannot cover it — its SHARED
# set requires presence in BOTH .claude/skills/ and harness/skills/). Found
# unguarded when the AGENT_SDK_OAUTH_ONE_TIME_CONSENT per-user/per-org interview
# question was added to harness/skills/setup/SKILL.md — the harness and template
# copies had already independently drifted (uv vs pip install instructions,
# a missing retry-config interview step) with nothing to catch it.
# ---------------------------------------------------------------------------

SETUP_SKILL_HARNESS_PATH = REPO_ROOT / "harness" / "skills" / "setup" / "SKILL.md"
SETUP_SKILL_TEMPLATE_PATH = TEMPLATE_DIR.parent / "skills" / "setup" / "SKILL.md"


def test_setup_skill_exists_in_harness() -> None:
    """Guard: harness/skills/setup/SKILL.md must exist — it is the source of truth
    the template copy is propagated from. If this fails, the identity test below
    would otherwise silently skip the file entirely."""
    assert SETUP_SKILL_HARNESS_PATH.is_file(), (
        f"{SETUP_SKILL_HARNESS_PATH} is missing — /setup's harness source was "
        "deleted or moved."
    )


@pytest.mark.xfail(
    not TEMPLATE_DIR.exists(),
    reason=(
        "peer repo not checked out — propagation unverified: template/ "
        "(wailuen/a2a-agent-template, LRN-071) is absent from this working tree, "
        "so the harness↔template propagation axis cannot be evaluated locally. "
        "This must pass wherever template/ is present (e.g. CI with the peer repo "
        "cloned) — an XPASS there means the axis is verified; leaving this on "
        "xfail keeps the unverifiable state visible in the run summary instead of "
        "silently skipping it."
    ),
    strict=True,
)
def test_setup_skill_is_harness_template_identical() -> None:
    """harness/skills/setup/SKILL.md and template/.claude/skills/setup/SKILL.md must
    stay byte-identical — a fix (e.g. a new /setup interview question) landing in
    only one copy is silently un-applied for whoever actually runs /setup: the
    template copy, never the harness one.

    This assertion always runs (never skipped): when template/ is absent it is
    expected to fail (xfail, above) as the loud, still-visible signal that the
    propagation axis is unverifiable in this checkout; when template/ is present
    it must pass as a hard assertion.
    """
    harness_text = SETUP_SKILL_HARNESS_PATH.read_text()
    template_text = SETUP_SKILL_TEMPLATE_PATH.read_text()
    assert harness_text == template_text, (
        "harness/skills/setup/SKILL.md and template/.claude/skills/setup/SKILL.md "
        "have diverged. These two copies must be byte-identical — a fix landing in "
        "only one copy is silently un-applied in the peer repo. Reconcile into a "
        "single superset (diff the files to find the drift), then copy the result "
        "to both locations."
    )
