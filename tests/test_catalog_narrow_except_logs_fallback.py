"""catalog.py:50 -- ``_own_annotation_names`` (and ``_field_summary``) must not
swallow every exception with a bare ``except Exception``.

Before this fix, an unexpected failure inside ``inspect.get_annotations`` (or
inside the field-enumeration loop in ``_field_summary``) was caught by a
catch-all and silently downgraded to a fallback value -- an empty
``frozenset`` / a bare ``"{...}"`` summary -- with no signal that anything had
gone wrong. That flips ``_field_summary``'s ``declared_here`` test to False
and silently drops a domain card's own redeclared metadata from the
LLM-facing compact-schema line.

The fix narrows the except clauses to the errors these helpers can actually
raise (``NameError`` / ``TypeError`` / ``AttributeError``) and logs a WARNING
whenever the fallback path is taken, so the degraded summary is observable
instead of silently wrong. An exception outside that narrowed set must
propagate rather than be swallowed.
"""

from __future__ import annotations

import logging

import pytest

from agent_sdk.a2ui import catalog
from agent_sdk.a2ui.catalog import _field_summary, _own_annotation_names
from agent_sdk.models.content_types import ContentModel


class _PlainClass:
    """Not a ContentModel subclass -- just something with a __mro__/annotations
    surface to point ``inspect.get_annotations`` at."""

    title: str


def test_own_annotation_names_logs_warning_on_narrowed_exception(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _boom(klass: object, **kwargs: object) -> dict[str, object]:
        raise AttributeError("simulated exotic __annotate__ failure")

    monkeypatch.setattr(catalog.inspect, "get_annotations", _boom)

    with caplog.at_level(logging.WARNING, logger=catalog.__name__):
        result = _own_annotation_names(_PlainClass)

    assert result == frozenset({"title"}), (
        "must still fall back to the raw __annotations__ read"
    )
    assert any(
        record.levelno == logging.WARNING for record in caplog.records
    ), "fallback path must log a WARNING so the degraded summary is observable"


@pytest.mark.parametrize("exc_type", [NameError, TypeError, AttributeError])
def test_own_annotation_names_catches_only_the_narrowed_set(
    monkeypatch: pytest.MonkeyPatch, exc_type: type[Exception]
) -> None:
    def _boom(klass: object, **kwargs: object) -> dict[str, object]:
        raise exc_type("simulated")

    monkeypatch.setattr(catalog.inspect, "get_annotations", _boom)

    # Must not raise -- falls back instead.
    _own_annotation_names(_PlainClass)


def test_own_annotation_names_does_not_swallow_unrelated_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(klass: object, **kwargs: object) -> dict[str, object]:
        raise ValueError("not one of the errors get_annotations documents")

    monkeypatch.setattr(catalog.inspect, "get_annotations", _boom)

    with pytest.raises(ValueError):
        _own_annotation_names(_PlainClass)


class _CardWithBrokenField(ContentModel):
    """A card whose annotation is deliberately hostile to ``_annotation_str``
    so the enumeration loop inside ``_field_summary`` raises."""

    data_type = "rt_narrow_except_broken_field"
    component = "RtNarrowExceptBrokenField"

    title: str

    def _body_text(self) -> str:
        return self.title


def test_field_summary_logs_warning_on_narrowed_exception(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _boom(ann: object, required: bool) -> tuple[str, bool]:
        raise AttributeError("simulated annotation-introspection failure")

    monkeypatch.setattr(catalog, "_annotation_str", _boom)

    with caplog.at_level(logging.WARNING, logger=catalog.__name__):
        result = _field_summary(_CardWithBrokenField)

    assert result == "{...}"
    assert any(
        record.levelno == logging.WARNING for record in caplog.records
    ), "fallback path must log a WARNING so the degraded summary is observable"


def test_field_summary_does_not_swallow_unrelated_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(ann: object, required: bool) -> tuple[str, bool]:
        raise RuntimeError("not one of the narrowed types")

    monkeypatch.setattr(catalog, "_annotation_str", _boom)

    with pytest.raises(RuntimeError):
        _field_summary(_CardWithBrokenField)
