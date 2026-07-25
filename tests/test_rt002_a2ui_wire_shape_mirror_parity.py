"""RT-002: the A2UI-over-A2A `DataPart.data` wire-shape rule must be stated
consistently across every mirror of the conformance oracle — a2ui-advisor.md,
a2a-advisor.md, a2ui-check/SKILL.md, and a2a-check/SKILL.md — in both the
repo (`.claude/`) and harness (`harness/`) trees. Before this fix only
a2ui-advisor.md (and its harness mirror) had been updated for GH-128's
`data.messages` object-wrapping; the other three still flatly asserted
"`data` MUST be a bare array" / "protocol error" otherwise, so the static
conformance gate (a2a-advisor pass of `/agent-stack-check`) would flag the
landed GH-128 fix as a violation and oscillate on re-run.

Scope: repo-tracked mirrors only (`.claude/` + `harness/`), matching the
established C-014 `AUTH_SURFACE` / GH-117 parity-test precedent. The user's
live `~/.claude` copies are outside pytest's reach (not repo-tracked) and are
kept in sync by hand per the same mirror convention.
"""

from __future__ import annotations

from pathlib import Path

import agent_sdk.app as _app_module

# Old, now-stale wire-shape phrasings that contradict the reconciled rule and
# must never reappear in any conformance-oracle mirror.
STALE_PHRASES = (
    "MUST be a JSON array",
    "`data` not an array",
    "is an array | Even for one message",
    "`data` = array of A2UI messages",
    "data[] is an array; first message is createSurface",
)

# The reconciled rule every mirror must state: a genuine, unresolved spec
# conflict between A2UI's own bare-array binding and A2A v0.3.0's object-only
# DataPart.data typing, resolved per-server via the `dataEncoding` agent-card
# hint rather than by asserting one shape as universally correct.
REQUIRED_MARKERS = ("genuine, unresolved", "dataEncoding")

AGENT_MIRROR_PAIRS = [
    (".claude/agents/a2ui-advisor.md", "harness/agents/a2ui-advisor.md"),
    (".claude/agents/a2a-advisor.md", "harness/agents/a2a-advisor.md"),
    (".claude/skills/a2ui-check/SKILL.md", "harness/skills/a2ui-check/SKILL.md"),
    (".claude/skills/a2a-check/SKILL.md", "harness/skills/a2a-check/SKILL.md"),
]


def _repo_root() -> Path:
    return Path(_app_module.__file__).parent.parent


def _read(relative: str) -> str:
    return (_repo_root() / relative).read_text()


def test_repo_and_harness_mirrors_are_byte_identical():
    for repo_rel, harness_rel in AGENT_MIRROR_PAIRS:
        repo_text = _read(repo_rel)
        harness_text = _read(harness_rel)
        assert repo_text == harness_text, (
            f"{repo_rel} and {harness_rel} have drifted — the harness seed "
            f"must stay byte-identical to the repo copy or newly-seeded "
            f"agent repos get a different conformance answer than this one"
        )


def test_no_mirror_states_a_stale_unqualified_wire_shape_rule():
    for repo_rel, _ in AGENT_MIRROR_PAIRS:
        text = _read(repo_rel)
        for stale in STALE_PHRASES:
            assert stale not in text, (
                f"{repo_rel} still contains the stale, unqualified "
                f"wire-shape phrasing {stale!r} — RT-002 requires every "
                f"mirror to state the reconciled genuine-spec-conflict rule "
                f"instead of a flat single-shape assertion"
            )


def test_every_mirror_states_the_reconciled_spec_conflict_and_hint():
    for repo_rel, _ in AGENT_MIRROR_PAIRS:
        text = _read(repo_rel)
        for marker in REQUIRED_MARKERS:
            assert marker in text, (
                f"{repo_rel} must state {marker!r} as part of the "
                f"reconciled DataPart.data wire-shape rule (RT-002) — every "
                f"mirror of the conformance oracle must agree the shape is "
                f"a genuine, unresolved spec conflict resolved via the "
                f"dataEncoding agent-card hint, not a single hard rule"
            )
