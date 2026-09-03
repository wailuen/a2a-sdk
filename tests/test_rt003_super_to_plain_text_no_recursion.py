"""RT-003 (round 2): a legacy ``to_plain_text()`` override that subclasses a
CONCRETE built-in card and calls ``super().to_plain_text()`` must not recurse.

That pattern was fully legal against the pre-split API: every card's
``to_plain_text()`` was a plain concrete method, so ``super().to_plain_text()``
from a subclass of e.g. ``KpiCard`` returned ``KpiCard``'s own rendering.

``ContentModel.__init_subclass__`` adopts a legacy override as the class's
``_body_text()`` and rebinds ``to_plain_text`` to the shared base
implementation. For a class whose PARENT is itself concrete (not the abstract
``ContentModel``), that rebinding used to recurse infinitely:
``super().to_plain_text()`` resolves to ``ContentModel.to_plain_text`` (the
parent has no ``to_plain_text`` of its own to intercept it), which calls
``self._body_text()`` — and ``self`` is still the subclass instance, so that
lands right back on the subclass's own adopted override.

Fixed: ``ContentModel.to_plain_text()`` detects it is being re-entered from
inside an adopted override executing for this same instance and resolves
``super().to_plain_text()`` to the next ancestor's ``_body_text()`` directly
(no double metadata suffix), instead of re-dispatching through
``type(self)._body_text()``.
"""

from __future__ import annotations

from typing import ClassVar

from agent_sdk.models.content_types import ContentModel, KpiCard, MetricItem


class LegacyKpiSubclass(KpiCard):
    """A domain card subclassing a CONCRETE built-in, written against the
    pre-split API: it extends the parent's rendering via
    ``super().to_plain_text()`` — legal code at the time it was written."""

    data_type: ClassVar[str] = "rt003_legacy_kpi_subclass"
    component: ClassVar[str] = "Rt003LegacyKpiSubclass"
    catalog_id: ClassVar[str] = "urn:test:rt003b:v1"

    def to_plain_text(self) -> str:
        return super().to_plain_text() + "\nextra"


def test_super_to_plain_text_from_concrete_subclass_does_not_recurse():
    card = LegacyKpiSubclass(metrics=[MetricItem(label="a", value=1)])
    text = card.to_plain_text()  # previously: RecursionError
    assert text == "a: 1\nextra"


def test_super_to_plain_text_from_concrete_subclass_still_carries_metadata_once():
    card = LegacyKpiSubclass(
        metrics=[MetricItem(label="a", value=1)],
        metadata={"coverage_note": "x"},
    )
    text = card.to_plain_text()
    assert text == "a: 1\nextra\ncoverage_note=x"
    # exactly one suffix, not appended once per recursion level
    assert text.count("coverage_note=x") == 1


class DoublyNestedLegacySubclass(LegacyKpiSubclass):
    """Two levels of adopted legacy overrides chained via super()."""

    data_type: ClassVar[str] = "rt003_doubly_nested_legacy_subclass"
    component: ClassVar[str] = "Rt003DoublyNestedLegacySubclass"
    catalog_id: ClassVar[str] = "urn:test:rt003b:v1"

    def to_plain_text(self) -> str:
        return super().to_plain_text() + "\nmore"


def test_two_chained_adopted_overrides_do_not_recurse():
    card = DoublyNestedLegacySubclass(metrics=[MetricItem(label="a", value=1)])
    assert card.to_plain_text() == "a: 1\nextra\nmore"


class DirectAbcSubclassLegacyOverride(ContentModel):
    """A direct ContentModel subclass whose legacy override calls
    super().to_plain_text() -- the one case the original (false) claim in
    __init_subclass__'s docstring was actually correct about: no concrete
    ancestor exists, so this resolves to the abstract stub's `None`."""

    data_type: ClassVar[str] = "rt003_direct_abc_legacy"
    component: ClassVar[str] = "Rt003DirectAbcLegacy"
    catalog_id: ClassVar[str] = "urn:test:rt003b:v1"

    def to_plain_text(self) -> str:
        parent_text = super().to_plain_text()
        return f"[{parent_text}] own"


def test_direct_abc_subclass_super_call_gets_none_not_recursion():
    card = DirectAbcSubclassLegacyOverride()
    assert card.to_plain_text() == "[None] own"
