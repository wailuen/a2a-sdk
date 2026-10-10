"""RT-002: the A2UI-over-A2A `DataPart.data` wire-shape rule must be stated
consistently across every mirror of the conformance oracle — a2ui-advisor.md,
a2a-advisor.md, a2ui-check/SKILL.md, and a2a-check/SKILL.md — in the repo
(`.claude/`), harness (`harness/`) and template (`template/.claude/`) trees.
Before this fix only a2ui-advisor.md (and its harness mirror) had been updated
for GH-128's `data.messages` object-wrapping; the other three still flatly
asserted "`data` MUST be a bare array" / "protocol error" otherwise, so the
static conformance gate would flag the landed GH-128 fix as a violation.

Repo and harness copies are git-tracked; the user's live `~/.claude` copies are
outside pytest's reach and are kept in sync by hand.

`template/` is entirely gitignored, so no diff-based check ever covers it.
The four template mirrors are therefore checked directly off disk: each must
be byte-identical to its harness copy, so DataPart wording, the spec-conflict
markers and the Profile v1.1 `TimeSeriesChart.metadata` state cannot drift.
Every template-reading test is marked strict xfail (not skip, not hard-fail)
when `template/` is absent, so a clean clone stays green while the
"propagation unverified" state remains visible, per test_workflow_sync.py.

Profile v1.1 (REVIEWS.md Round 11): the maintainer signed off removing the
frozen `TimeSeriesChart.metadata` row in favour of a cross-cutting `metadata`
note (issue #153). The gate flag `ROUND_8_METADATA_ROW_REMOVAL_RATIFIED` is
derived from REVIEWS.md and is True while the status line reads SIGNED OFF and
the `Checkable reference:` line holds a wailuen/a2a-sdk GitHub URL or a commit
SHA. Every advisor-copy assertion branches on the flag: while True every copy,
template included, must LACK the typed row and CARRY the cross-cutting marker;
if the record is reverted the reverse. The REVIEWS.md record and the advisor
text therefore cannot disagree without a test failing.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import agent_sdk.app as _app_module

# Old, now-stale wire-shape phrasings that contradict the reconciled rule and
# must never reappear in any conformance-oracle mirror.
STALE_PHRASES = (
    "MUST be a JSON array",
    "`data` not an array",
    "is an array | Even for one message",
    "`data` = array of A2UI messages",
    "data[] is an array",
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

TEMPLATE_MIRRORS = [
    TEMPLATE_A2UI_ADVISOR,
    "template/.claude/agents/a2a-advisor.md",
    "template/.claude/skills/a2ui-check/SKILL.md",
    "template/.claude/skills/a2a-check/SKILL.md",
]

# The frozen Profile v1 typed TimeSeriesChart.metadata row. Present while the
# Present only before the Profile v1.1 amendment (REVIEWS.md Round 11) was ratified.
STALE_TIME_SERIES_METADATA_ROW = (
    "| `metadata` | `{identifier?, metric?, frequency?, source?}` | — | |"
)
# The ratified v1.1 replacement note: required once Round 11 is signed off.
METADATA_CROSS_CUTTING_MARKER = (
    "`metadata` is a cross-cutting field, not a per-type one."
)



_STATUS_SIGNED_OFF = re.compile(r"^\*\*SIGNED OFF\*\*")
# Format check only: a wailuen/a2a-sdk issue/PR URL (optionally a comment
# anchor) or a full commit SHA. Whoever reviews the sign-off commit must open
# the reference and confirm it is the maintainer's own approval.
_REFERENCE_LINE = re.compile(
    r"^Checkable reference:\s*("
    r"https://github\.com/wailuen/a2a-sdk/(?:issues|pull)/\d+"
    r"(?:#(?:issuecomment|discussion_r|pullrequestreview)-?\d+)?"
    r"|[0-9a-f]{40}"
    r")\s*$",
)


def round_11_checkable_reference_recorded(reviews_text: str) -> bool:
    """True only when the Round 11 status line is SIGNED OFF and its
    `Checkable reference:` line holds a real reference."""
    if "## Round 11" not in reviews_text:
        return False
    section = reviews_text.split("## Round 11", 1)[1].split("\n## ", 1)[0]
    lines = section.splitlines()[1:]
    status = next((ln for ln in lines if ln.strip()), "")
    if not _STATUS_SIGNED_OFF.match(status):
        return False
    return any(_REFERENCE_LINE.match(ln) for ln in lines)


def _repo_root() -> Path:
    return Path(_app_module.__file__).parent.parent


requires_template = pytest.mark.xfail(
    not (_repo_root() / "template").exists(),
    strict=True,
    reason="template/ (gitignored peer repo) is absent from this checkout; "
    "propagation unverified",
)


def _read(relative: str) -> str:
    return (_repo_root() / relative).read_text()


ROUND_8_METADATA_ROW_REMOVAL_RATIFIED = round_11_checkable_reference_recorded(
    _read("REVIEWS.md")
)


def _assert_metadata_row_state(
    path: str, text: str, ratified: bool = ROUND_8_METADATA_ROW_REMOVAL_RATIFIED
) -> None:
    """Enforce the advisor state that matches the REVIEWS.md Round 11 record."""
    has_row = STALE_TIME_SERIES_METADATA_ROW in text
    has_marker = METADATA_CROSS_CUTTING_MARKER in text
    if ratified:
        if has_row:
            raise AssertionError(
                f"{path} still carries the typed TimeSeriesChart.metadata "
                f"row, but REVIEWS.md Round 11 records Profile v1.1 as "
                f"SIGNED OFF — apply the amendment to every copy"
            )
        if not has_marker:
            raise AssertionError(
                f"{path} is missing the cross-cutting `metadata` note that "
                f"the signed-off Profile v1.1 amendment requires"
            )
        return
    if not has_row:
        raise AssertionError(
            f"{path} dropped the frozen TimeSeriesChart.metadata row while "
            f"REVIEWS.md Round 11 is still pending ratification — a wave may "
            f"not apply an unratified frozen-contract edit"
        )
    if has_marker:
        raise AssertionError(
            f"{path} carries the cross-cutting `metadata` note while "
            f"REVIEWS.md Round 11 is still pending ratification"
        )


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


@requires_template
def test_all_three_a2ui_advisor_copies_match_the_round_11_record():
    """RT-A08: the untracked `template/` copy must not silently drift from
    the two git-tracked copies just because no diff watches it. RT-003: the
    template copy is a hard requirement here — its absence must fail
    loudly, not silently shrink the 'all three copies' check down to two.
    Every copy must match the REVIEWS.md Round 11 ratification state
    (ROUND_8_METADATA_ROW_REMOVAL_RATIFIED)."""
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
        _assert_metadata_row_state(path, text)


@requires_template
@pytest.mark.parametrize("template_rel", TEMPLATE_MIRRORS)
def test_template_mirrors_state_reconciled_wire_shape_rule(template_rel: str):
    assert (_repo_root() / template_rel).exists(), (
        f"{template_rel} is missing — template/ (wailuen/a2a-agent-template) "
        f"is required; this test must fail rather than skip propagation checks"
    )
    text = _read(template_rel)
    for stale in STALE_PHRASES:
        assert stale not in text, f"{template_rel} contains stale phrasing {stale!r}"
    for marker in REQUIRED_MARKERS:
        assert marker in text, f"{template_rel} lacks the marker {marker!r}"
    harness_rel = template_rel.replace("template/.claude/", "harness/", 1)
    assert text == _read(harness_rel), (
        f"{template_rel} has drifted from {harness_rel}"
    )


def _signed_off(reviews_text: str, reference_line: str) -> str:
    head, rest = reviews_text.split("## Round 11", 1)
    lines = rest.splitlines()
    out = []
    for ln in lines:
        if ln.startswith("**PROPOSED**"):
            ln = "**SIGNED OFF** — confirmed by the maintainer."
        elif ln.startswith("Checkable reference:"):
            ln = reference_line
        out.append(ln)
    return head + "## Round 11" + "\n".join(out)


# Clearly fake placeholder — not a real issue or approval.
_FAKE_SIGNOFF_URL = (
    "https://github.com/wailuen/a2a-sdk/issues/999999#issuecomment-999999"
)


def test_real_reviews_md_flips_true_after_documented_signoff_edit():
    reviews = _read("REVIEWS.md")
    signed = _signed_off(reviews, f"Checkable reference: {_FAKE_SIGNOFF_URL}")
    assert round_11_checkable_reference_recorded(signed) is True


@pytest.mark.parametrize(
    "reference_line",
    [
        "Checkable reference: no session ID exists",
        "Checkable reference: http TBD",
        "Checkable reference: **PENDING**",
        "Checkable reference:",
        "Checkable reference: https://github.com/someone/else/issues/1",
        "Checkable reference: https://github.com/wailuen/a2a-sdk",
        "Checkable reference: session 123e4567-e89b-12d3-a456-426614174000",
        "Checkable reference: " + "a" * 39,
    ],
)
def test_non_references_do_not_satisfy_the_gate(reference_line: str):
    signed = _signed_off(_read("REVIEWS.md"), reference_line)
    assert round_11_checkable_reference_recorded(signed) is False


@pytest.mark.parametrize(
    "reference_line",
    [
        "Checkable reference: " + "a" * 40,
        "Checkable reference: https://github.com/wailuen/a2a-sdk/pull/999999",
    ],
)
def test_sha_and_repo_url_references_are_accepted(reference_line: str):
    signed = _signed_off(_read("REVIEWS.md"), reference_line)
    assert round_11_checkable_reference_recorded(signed) is True
