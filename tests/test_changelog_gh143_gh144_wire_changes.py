"""GH-143 / GH-144 CHANGELOG discipline (redteam finding on CHANGELOG.md).

Both GH-143 (adds a 429 admission cap to GET /mcp / GET /mcp/sse) and GH-144
(/v1/message:stream's terminal-task error code changes from 404/-32001 to
501/-32004 — a stable-core wire change per DESIGN.md §4.0) are wire-visible
changes landed in this repo with no CHANGELOG entry. DESIGN.md §4.0's
wire-shape conformance exemption explicitly conditions on carrying "a
dedicated breaking-changes CHANGELOG heading ... and an explicit Migration
callout" — this module pins that both entries exist, in the right section,
with the right content, so doc and code can never drift apart silently
again (mirrors test_gh41_lifespan_extras_docs.py's pattern).

RT-001 (round 7): those pins were all GH-specific string matches, so they
caught nothing when the SAME wave went on to ship three further stable-core
additions with no entry at all — a new `BaseAgentSettings` field
(`AGENT_SDK_MAX_A2A_STREAMS_PER_IDENTITY`), a new module
(`agent_sdk/common/admission.py`, component C-024), and a per-identity cap
layer the existing A2A entry actively misdescribed by omitting. The last three
tests below are therefore GENERAL rules rather than another round of
per-symbol pins: every non-grandfathered `AGENT_SDK_*` alias must appear in
CHANGELOG.md, the grandfather list may only shrink, and the admission module
must be named. `BaseAgentSettings` is stable core under strict SemVer
(DESIGN.md §4.0), and documenting a field's behaviour in DESIGN.md does not
discharge that accounting.
"""

from __future__ import annotations

import re
from pathlib import Path

import agent_sdk.app as _app_module


def _changelog_text() -> str:
    return (Path(_app_module.__file__).parent.parent / "CHANGELOG.md").read_text()


def test_changelog_has_unreleased_section() -> None:
    text = _changelog_text()
    idx = text.find("## [Unreleased]")
    assert idx != -1, "CHANGELOG.md must have an ## [Unreleased] section for undated changes"
    assert idx < text.find("## [0.6.0]"), "## [Unreleased] must precede the last tagged release"


def test_changelog_gh144_breaking_change_entry() -> None:
    text = _changelog_text()
    unreleased = text[text.find("## [Unreleased]"): text.find("## [0.6.0]")]
    assert "GH-144" in unreleased, "CHANGELOG.md [Unreleased] must have a GH-144 entry"

    breaking = unreleased[unreleased.find("### 🔴 Breaking changes"):]
    gh144_idx = breaking.find("GH-144")
    assert gh144_idx != -1, "GH-144 must be filed under a 🔴 Breaking changes heading"
    entry = breaking[gh144_idx : gh144_idx + 4000]

    assert "message:stream" in entry or "message/stream" in entry, (
        "GH-144 entry must name the exact surface: message:stream"
    )
    assert "-32001" in entry and "-32004" in entry, (
        "GH-144 entry must name both the old (-32001) and new (-32004) code"
    )
    assert re.search(r"\b404\b", entry) and re.search(r"\b501\b", entry), (
        "GH-144 entry must name both the old (404) and new (501) HTTP status"
    )
    assert "Migration" in entry, "GH-144 entry must carry an explicit Migration callout"


def test_gh144_does_not_falsely_claim_the_wire_shape_exemption() -> None:
    """RT-002: `agent_sdk/models/errors.py` is untouched by GH-144 (both
    `-32001` and `-32004` already existed there, unchanged) and REVIEWS.md's
    own Round 10 audit classifies the pre-fix code split as "not a hard-MUST
    breach" — no A2A v0.3.0 clause mandates `-32004` specifically for a
    terminal re-message via `message/stream` (only a generic "MUST return an
    error"). The entry must not claim DESIGN.md §4.0's wire-shape exemption
    applies, and must say why."""
    text = _changelog_text()
    unreleased = text[text.find("## [Unreleased]"): text.find("## [0.6.0]")]
    breaking = unreleased[unreleased.find("### 🔴 Breaking changes"):]
    gh144_idx = breaking.find("GH-144")
    entry = breaking[gh144_idx : gh144_idx + 4000]

    assert "exemption **does apply**" not in entry, (
        "GH-144 must not claim the DESIGN.md §4.0 wire-shape exemption "
        "applies — agent_sdk/models/errors.py is unchanged by this diff and "
        "no A2A v0.3.0 clause mandates -32004 specifically for this case"
    )
    assert "no major bump is required" not in entry, (
        "GH-144 must not assert an exemption-driven patch/minor-eligible "
        "claim it does not satisfy"
    )
    assert "does not apply" in entry, (
        "GH-144 entry must explicitly state the wire-shape exemption does "
        "not apply to this change"
    )
    assert "major bump" in entry, (
        "GH-144 entry must state the DESIGN.md:141 consequence: a voluntary "
        "stable-core break not required by spec conformance requires a "
        "major bump"
    )
    assert "REVIEWS.md" in entry, (
        "GH-144 entry must reconcile with REVIEWS.md's own 'not a hard-MUST "
        "breach' verdict on the identical finding, not contradict it silently"
    )


def test_wire_shape_exemption_citations_name_a_models_file() -> None:
    """DESIGN.md §4.0's wire-shape exemption is scoped to a break in a
    stable-core wire shape living under `agent_sdk/models/`. Pin the rule
    generally, not just for GH-144: any [Unreleased] entry that asserts the
    exemption DOES apply must name an actual `agent_sdk/models/` file in its
    own text — an argument from code semantics alone (as GH-144's original,
    incorrect revision made) is not sufficient grounding."""
    text = _changelog_text()
    unreleased = text[text.find("## [Unreleased]"): text.find("## [0.6.0]")]
    for match in re.finditer(r"exemption\s+\*\*does apply\*\*", unreleased):
        start = max(0, match.start() - 3000)
        entry = unreleased[start : match.end() + 500]
        assert re.search(r"`agent_sdk/models/[\w./]+\.py`", entry), (
            "an entry claiming DESIGN.md §4.0's wire-shape exemption applies "
            "must name an actual agent_sdk/models/ file — the exemption is "
            "scoped to a wire-shape break living there, not to route-level "
            "behavior changes"
        )


def test_changelog_gh143_security_entry() -> None:
    text = _changelog_text()
    unreleased = text[text.find("## [Unreleased]"): text.find("## [0.6.0]")]
    assert "GH-143" in unreleased, "CHANGELOG.md [Unreleased] must have a GH-143 entry"

    idx = unreleased.find("GH-143")
    entry = unreleased[idx : idx + 3000]
    assert "429" in entry, "GH-143 entry must name the new 429 status"
    assert "/mcp/sse" in entry, (
        "GH-143 entry must cover GET /mcp/sse, not just GET /mcp — both "
        "transports share the same cap"
    )
    assert "_MAX_GET_STREAMS" in entry, (
        "GH-143 entry must name the _MAX_GET_STREAMS/_MAX_GET_STREAMS_PER_IDENTITY defaults"
    )


def test_a2a_stream_cap_entry_names_all_three_admission_layers() -> None:
    """RT-001 (round 7): the A2A admission entry described only the global and
    per-task layers, omitting the per-identity one DESIGN.md §5.5 and
    docs/protocols.md both document as the cross-tenant fairness layer — and
    the per-task cap is vacuous on message:stream's dominant no-taskId path
    (a fresh uuid per call always counts 0), so the entry as written described
    a budget with no cross-tenant dimension on the busiest streaming route.
    Pin all three, in the release section that ships them."""
    text = _changelog_text()
    release = text[text.find("## [Unreleased]"): text.find("## [0.6.0]")]
    idx = release.find("_MAX_A2A_STREAMS")
    assert idx != -1, "the release section must describe the A2A stream admission budget"
    entry = release[max(0, idx - 2000) : idx + 3000]
    for layer in ("_MAX_A2A_STREAMS = 500", "_MAX_A2A_STREAMS_PER_IDENTITY", "_MAX_A2A_STREAMS_PER_TASK"):
        assert layer in entry, (
            f"the A2A stream admission entry must name the {layer} layer — "
            "naming a subset misdescribes the shipped design"
        )


# ---------------------------------------------------------------------------
# RT-001 (round 7): stable-core settings accounting
# ---------------------------------------------------------------------------

# Every `AGENT_SDK_*` alias on `BaseAgentSettings` predating the 0.7.0 release,
# from before this ratchet existed. DESIGN.md §4.0 puts `BaseAgentSettings` in
# the stable core under strict SemVer, so from 0.7.0 on a NEW alias must carry
# its own CHANGELOG mention in the release that ships it. This list is
# deliberately explicit and must never grow: adding to it is the visible,
# reviewable act of shipping a settable stable-core field undocumented.
_GRANDFATHERED_ALIASES = frozenset(
    {
        "AGENT_SDK_A2UI_ALLOWED_COMPONENTS",
        "AGENT_SDK_INTERRUPT_TTL",
        "AGENT_SDK_MAX_INTERRUPTED",
        "AGENT_SDK_MAX_OUTPUT_TOKENS",
        "AGENT_SDK_MAX_TURNS",
        "AGENT_SDK_RATE_LIMIT",
        "AGENT_SDK_TASK_DEADLINE",
        "AGENT_SDK_TASK_TOKEN_BUDGET",
        "AGENT_SDK_TASK_TTL",
        "AGENT_SDK_TRUSTED_PROXIES",
        "AGENT_SDK_UNAUTH_RATE_LIMIT",
    }
)


def _settings_aliases() -> set[str]:
    config = (Path(_app_module.__file__).parent / "config.py").read_text()
    return set(re.findall(r'alias="(AGENT_SDK_[A-Z0-9_]+)"', config))


def test_every_settings_alias_is_recorded_in_the_changelog() -> None:
    """RT-001 (round 7): `AGENT_SDK_MAX_A2A_STREAMS_PER_IDENTITY` shipped as a
    new stable-core `BaseAgentSettings` field with zero CHANGELOG record — the
    behaviour was documented in DESIGN.md, which does not discharge SemVer
    accounting for a settable public field. Nothing would have caught it: the
    pins above are all GH-specific string matches. This is the general rule."""
    text = _changelog_text()
    missing = sorted(
        alias
        for alias in _settings_aliases()
        if alias not in _GRANDFATHERED_ALIASES and alias not in text
    )
    assert not missing, (
        "new AGENT_SDK_* BaseAgentSettings aliases with no CHANGELOG mention: "
        f"{missing}. BaseAgentSettings is stable core under strict SemVer "
        "(DESIGN.md §4.0) — every new settable field needs its own entry in "
        "the release that ships it, naming the alias, the attribute, its "
        "default and its clamp/validation bounds."
    )


def test_grandfathered_alias_list_stays_accurate() -> None:
    """The ratchet is only a ratchet while the exemption list cannot silently
    absorb new fields: every grandfathered name must still exist in config.py
    (so a renamed field is re-caught), and none may be one this repo has since
    documented (so the list shrinks rather than ossifies)."""
    aliases = _settings_aliases()
    stale = sorted(_GRANDFATHERED_ALIASES - aliases)
    assert not stale, (
        f"grandfathered aliases no longer present in config.py: {stale} — "
        "drop them from _GRANDFATHERED_ALIASES so a future field reusing the "
        "name is not silently exempted"
    )
    text = _changelog_text()
    now_documented = sorted(a for a in _GRANDFATHERED_ALIASES if a in text)
    assert not now_documented, (
        f"these aliases are now documented in CHANGELOG.md: {now_documented} "
        "— remove them from _GRANDFATHERED_ALIASES; the exemption list must "
        "only ever shrink"
    )


def test_c024_admission_module_is_recorded_in_the_changelog() -> None:
    """RT-001 (round 7): `agent_sdk/common/admission.py` was registered as
    component C-024 in workspace/components/README.md and imported by three
    route modules, with no CHANGELOG mention at all — a new module under
    `agent_sdk/` is a public-surface addition, not an internal refactor."""
    text = _changelog_text()
    assert "common/admission.py" in text, (
        "the new agent_sdk/common/admission.py module (C-024) must be named "
        "in CHANGELOG.md in the release that ships it"
    )
    assert "C-024" in text, "the entry must cite the component id it registers"
