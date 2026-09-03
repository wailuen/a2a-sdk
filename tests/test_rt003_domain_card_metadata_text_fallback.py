"""RT-003: ``metadata`` must reach ``to_plain_text()`` for DOMAIN cards too.

``metadata`` lives on ``ContentModel`` (RT-006), but appending its text-fallback
suffix used to be a per-subclass obligation, hand-written at 14 call sites in
``content_types.py``. The 14 built-ins honoured it. Nothing enforced it, and the
one class of card nobody had hand-edited -- a domain card registered through
``register_content_type``, the extension path the module docstring advertises --
did not: its ``wire()`` carried the disclosure annotation while its
``to_plain_text()`` dropped it.

That is the exact failure the field exists to prevent. ``to_plain_text()`` is the
mandatory fallback for clients WITHOUT A2UI capability (the A2A ``TextPart`` in
``agent/runner.py``, the MCP ``tools/call`` text in ``routes/mcp.py``) -- so a
``metadata={"coverage_note": "Partial: 5 of 20 funds"}`` disclosure vanished for
precisely the audience that can see nothing else.

Fixed structurally: ``ContentModel.to_plain_text()`` is concrete
(``_body_text() + _metadata_suffix()``) and subclasses implement ``_body_text()``.
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from agent_sdk.models.content_types import ContentModel


class DomainCard(ContentModel):
    """A domain card written against the CURRENT API (implements _body_text)."""

    data_type: ClassVar[str] = "rt003_domain_card"
    component: ClassVar[str] = "Rt003DomainCard"
    catalog_id: ClassVar[str] = "urn:test:rt003:v1"

    n: int

    def _body_text(self) -> str:
        return f"Dom: {self.n}"


class LegacyDomainCard(ContentModel):
    """A domain card written against the OLDER API (overrides to_plain_text).

    ``ContentModel.__init_subclass__`` adopts the override as ``_body_text``, so
    such a card keeps rendering identically AND picks up the metadata suffix --
    rather than silently shadowing the concrete base method and reintroducing
    the very bug this closes for the extension path it exists to serve.
    """

    data_type: ClassVar[str] = "rt003_legacy_domain_card"
    component: ClassVar[str] = "Rt003LegacyDomainCard"
    catalog_id: ClassVar[str] = "urn:test:rt003:v1"

    n: int

    def to_plain_text(self) -> str:
        return f"Legacy: {self.n}"


@pytest.mark.parametrize("cls", [DomainCard, LegacyDomainCard])
def test_domain_card_metadata_reaches_text_fallback(cls):
    card = cls(n=1, metadata={"coverage_note": "Partial: 5 of 20 funds"})
    text = card.to_plain_text()
    assert "coverage_note=Partial: 5 of 20 funds" in text, (
        f"{cls.__name__}: the disclosure annotation vanished from the mandatory "
        f"text fallback; got {text!r}"
    )
    # ...and wire() still carries it, so the two halves agree.
    assert card.wire()["metadata"] == {"coverage_note": "Partial: 5 of 20 funds"}


@pytest.mark.parametrize("cls", [DomainCard, LegacyDomainCard])
def test_domain_card_body_text_unchanged_without_metadata(cls):
    """No metadata -> byte-identical to what the card's own rendering produces;
    the split adds a suffix, it does not reshape the body."""
    expected = "Dom: 2" if cls is DomainCard else "Legacy: 2"
    assert cls(n=2).to_plain_text() == expected


def test_legacy_override_is_adopted_not_discarded():
    """The adopted function stays reachable as ``_body_text``, so a legacy card
    is debuggable rather than mysteriously rebound."""
    assert LegacyDomainCard._body_text.__name__ == "to_plain_text"
    assert LegacyDomainCard(n=3)._body_text() == "Legacy: 3"
    assert LegacyDomainCard.to_plain_text is ContentModel.to_plain_text


def test_body_text_is_the_abstract_hook():
    """A subclass implementing NEITHER method must still be uninstantiable --
    the concrete to_plain_text() must not have silently satisfied the ABC."""

    class Incomplete(ContentModel):
        data_type: ClassVar[str] = "rt003_incomplete"
        component: ClassVar[str] = "Rt003Incomplete"

    assert "_body_text" in Incomplete.__abstractmethods__
    with pytest.raises(TypeError):
        Incomplete()


def test_every_builtin_card_renders_metadata_in_text_fallback():
    """Sweep the whole registry rather than spot-checking: a card type added
    later inherits the guarantee automatically, and this fails if one is ever
    given a to_plain_text() that bypasses the suffix."""
    from agent_sdk.models.content_types import PROFILE_TYPES

    marker = {"coverage_note": "rt003-sweep"}
    samples: dict[str, dict[str, Any]] = {
        "KpiCard": {"metrics": [{"label": "a", "value": 1}]},
        "TimeSeriesChart": {
            "chart_type": "line", "title": "t", "x_key": "date", "y_key": "value",
            "total_count": 1, "data": [{"date": "2026-01-01", "value": 1.0}],
        },
        "ComparisonTable": {
            "columns": [{"key": "k", "label": "K"}], "rows": [{"k": 1}],
        },
        "BarChart": {"bars": [{"category": "Q1", "value": 1.0}]},
        "EntityList": {"entity_type": "fund", "items": [{"id": "1", "name": "A"}]},
        "MarketBriefing": {"title": "t", "as_of": "2026-01-01", "prose": "p"},
        "WaterfallChart": {
            "title": "t",
            "segments": [
                {"label": "s", "value": 1.0, "type": "initial", "cumulative": 1.0}
            ],
        },
        "MultiCategoryChart": {
            "title": "t",
            "periods": [{"period": "Q1", "categories": {"a": {"value": 1.0}}}],
            "summary": {"by_category": {"a": {"value": 1.0}}, "period_count": 1},
            "date_range": {"first": "2026-01-01", "last": "2026-03-31"},
        },
        "FundPerformance": {"irr": 0.18},
        "EmailList": {"messages": [], "total_count": 0, "has_more": False},
        "CalendarEvents": {
            "events": [], "date_range": {"start": "a", "end": "b"},
            "total_count": 0, "has_more": False,
        },
        "UserProfile": {
            "id": "1", "display_name": "A", "email": "a@b.c", "business_phones": [],
        },
        "UserList": {"users": [], "total_count": 0, "has_more": False},
        "DocumentList": {"documents": []},
    }

    missing = [c.component for c in PROFILE_TYPES if c.component not in samples]
    assert not missing, f"add a sample payload for {missing}"

    for cls in PROFILE_TYPES:
        card = cls(**samples[cls.component], metadata=marker)
        assert "coverage_note=rt003-sweep" in card.to_plain_text(), cls.component


def test_market_briefing_markdown_still_carries_no_suffix():
    """The prose exception is unchanged: to_markdown() stays clean and picks the
    suffix up only through the shared to_plain_text()."""
    from agent_sdk.models.content_types import MarketBriefing

    mb = MarketBriefing(
        title="t", as_of="2026-01-01", prose="p", metadata={"coverage_note": "x"}
    )
    assert "coverage_note" not in mb.to_markdown()
    assert "coverage_note=x" in mb.to_plain_text()
