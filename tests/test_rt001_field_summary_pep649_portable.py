"""RT-001: ``_field_summary``'s declared-here check must be interpreter-portable.

The carve-out that keeps a domain card's own redeclared ``metadata`` in its LLM
teaching string was reading ``vars(cls).get("__annotations__", {})``. That is a
CPython implementation detail, not a portable "did this class declare it?" test:
under PEP 649 (3.14+) it returns ``{}`` for any class defined in a module without
``from __future__ import annotations``, so the answer was always False on 3.14
while 3.12/3.13 worked -- silently dropping the field across the declared
``requires-python = ">=3.12"`` range.

The pre-existing regression tests could not catch it: they live in
``tests/test_a2ui_wire.py``, which happens to declare the future import, so their
card classes took the eager-string path. The cards exercised here are defined in
``tests/_rt001_no_future_annotations_cards.py``, which deliberately omits it.
"""

from __future__ import annotations

import sys

import pytest

from agent_sdk.a2ui.catalog import _field_summary, _own_annotation_names
from agent_sdk.models.content_types import ContentModel

from ._rt001_no_future_annotations_cards import (
    NoFutureGrandchildCard,
    NoFutureInheritedMetadataCard,
    NoFutureOwnMetadataCard,
)


def test_own_declared_metadata_survives_without_future_import():
    summary = _field_summary(NoFutureOwnMetadataCard)
    assert "metadata" in summary, (
        "a domain card's OWN redeclared metadata field vanished from its "
        f"teaching string; got {summary!r}"
    )
    assert "title" in summary


def test_domain_metadata_two_levels_deep_survives_without_future_import():
    """RT-008's MRO walk, re-pinned on the no-future-import path."""
    summary = _field_summary(NoFutureGrandchildCard)
    assert "metadata" in summary, (
        f"domain-declared metadata inherited two levels vanished; got {summary!r}"
    )


def test_inherited_base_metadata_still_skipped_without_future_import():
    """The carve-out must not become "always keep" -- a card that merely
    inherits ContentModel.metadata still drops it from its per-type summary."""
    summary = _field_summary(NoFutureInheritedMetadataCard)
    assert "metadata" not in summary, (
        f"inherited ContentModel.metadata must not appear; got {summary!r}"
    )
    assert "title" in summary


def test_field_summary_never_reads_raw_class_annotations_dict():
    """Guard the fix itself: a future edit that goes back to the raw
    ``vars(cls)["__annotations__"]`` read reintroduces the 3.14 blind spot."""
    import inspect as _inspect

    import agent_sdk.a2ui.catalog as catalog

    # Comments are allowed to name the anti-pattern (they explain the fix);
    # executable lines are not.
    code = [
        line
        for line in _inspect.getsource(catalog._field_summary).splitlines()
        if not line.lstrip().startswith("#")
    ]
    offenders = [line for line in code if "__annotations__" in line]
    assert not offenders, (
        "_field_summary must go through _own_annotation_names(), not read "
        f"vars(cls)['__annotations__'] directly (PEP 649 makes that empty on "
        f"3.14); offending lines: {offenders}"
    )


def test_own_annotation_names_is_non_inheriting():
    assert "metadata" in _own_annotation_names(NoFutureOwnMetadataCard)
    assert "title" in _own_annotation_names(NoFutureOwnMetadataCard)
    # The grandchild declares neither itself.
    assert "metadata" not in _own_annotation_names(NoFutureGrandchildCard)
    assert "title" not in _own_annotation_names(NoFutureGrandchildCard)
    assert "metadata" in _own_annotation_names(ContentModel)


@pytest.mark.skipif(sys.version_info < (3, 14), reason="PEP 649 lands in 3.14")
def test_raw_vars_read_would_have_been_empty_here():
    """Documents WHY the helper exists: on 3.14 the raw read this replaced is
    empty for exactly these classes, so the old check answered False for every
    field. If this ever stops holding, the helper is still correct -- but the
    3.14-specific hazard it guards has changed and the comment should be
    revisited."""
    assert vars(NoFutureOwnMetadataCard).get("__annotations__", {}) == {}


def test_own_annotation_names_tolerates_unresolvable_forward_reference():
    """FORWARDREF (3.14+) / no eval (3.12-3.13): an annotation naming a type
    that does not exist must not raise, or the whole summary degrades to
    ``{...}``."""

    # A plain class whose annotation names an undefined symbol.
    ns: dict = {}
    exec(
        "from typing import ClassVar\n"
        "class Fwd:\n"
        "    later: 'NotDefinedAnywhere'\n",
        ns,
    )
    assert "later" in _own_annotation_names(ns["Fwd"])
