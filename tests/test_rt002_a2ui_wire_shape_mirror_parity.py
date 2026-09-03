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

RT-A08 follow-up: `template/.claude/agents/a2ui-advisor.md` is a *third*
a2ui-advisor copy (the peer-repo template seed) but `template/` is entirely
gitignored, so no diff-based check ever covers it — a fix landing in
`.claude/`+`harness/` alone can silently stay unpropagated there. Unlike the
DataPart wire-shape content above (template deliberately still diverges there
per the tracked GH-128 follow-on, issue #151 — do not fold it into the
byte-identical check), the RT-006 `metadata`-is-cross-cutting content below
IS expected to already match in all three copies, so it is checked directly
off disk (present on disk despite being untracked), following the same
gitignored-template-read precedent as `tests/test_workflow_sync.py`.
"""

from __future__ import annotations

import warnings
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


TEMPLATE_A2UI_ADVISOR = "template/.claude/agents/a2ui-advisor.md"

# RT-006: the SDK-wide `metadata` field must be documented once, as
# cross-cutting, never redeclared as a per-type table row.
METADATA_CROSS_CUTTING_MARKER = (
    "`metadata` is a cross-cutting field, not a per-type one."
)
STALE_TIME_SERIES_METADATA_ROW = (
    "| `metadata` | `{identifier?, metric?, frequency?, source?}` | — | |"
)

# RT-003 (w040 follow-up): REVIEWS.md Round 8 records the removal of this row
# as PROPOSED, pending user ratification — explicitly NOT SIGNED OFF, per the
# standing rule that a wave's own redteam/implementer cannot ratify a
# frozen-contract doc change alone
# (memory/feedback-wave-signoff-needs-user-ratification). Flip this to True
# ONLY alongside a REVIEWS.md Round 8 edit that records a maintainer's
# SIGNED OFF ruling — never as a bare test edit. Until then, a reverted row
# must warn, not hard-fail, so the enforced status here matches the
# provisional status recorded in REVIEWS.md.
ROUND_8_METADATA_ROW_REMOVAL_RATIFIED = False


def _repo_root() -> Path:
    return Path(_app_module.__file__).parent.parent


def _read(relative: str) -> str:
    return (_repo_root() / relative).read_text()


def _assert_metadata_row_removed_or_warn(
    path: str, text: str, *, ratified: bool = ROUND_8_METADATA_ROW_REMOVAL_RATIFIED
) -> None:
    if STALE_TIME_SERIES_METADATA_ROW not in text:
        return
    message = (
        f"{path} still carries the stale per-type `metadata` row on "
        f"TimeSeriesChart's field table — REVIEWS.md Round 8 proposed "
        f"removing it (RT-006) but this is not yet ratified"
    )
    if ratified:
        raise AssertionError(message)
    warnings.warn(message, stacklevel=2)


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


def test_all_three_a2ui_advisor_copies_state_metadata_is_cross_cutting():
    """RT-A08: the untracked `template/` copy must not silently drift from
    the two git-tracked copies on RT-006 content just because no diff
    watches it. RT-003: the template copy is a hard requirement here — its
    absence must fail loudly, not silently shrink the 'all three copies'
    check down to two."""
    template_path = _repo_root() / TEMPLATE_A2UI_ADVISOR
    assert template_path.exists(), (
        f"{TEMPLATE_A2UI_ADVISOR} is missing — this test must fail rather "
        f"than silently drop the template copy from the 'all three copies' "
        f"guarantee its name asserts"
    )

    copies = {
        ".claude/agents/a2ui-advisor.md": _read(".claude/agents/a2ui-advisor.md"),
        "harness/agents/a2ui-advisor.md": _read("harness/agents/a2ui-advisor.md"),
        TEMPLATE_A2UI_ADVISOR: template_path.read_text(),
    }

    for path, text in copies.items():
        assert METADATA_CROSS_CUTTING_MARKER in text, (
            f"{path} is missing the RT-006 cross-cutting `metadata` note — "
            f"every a2ui-advisor copy must document `metadata` once, not "
            f"per FROZEN-type table"
        )
        _assert_metadata_row_removed_or_warn(path, text)
