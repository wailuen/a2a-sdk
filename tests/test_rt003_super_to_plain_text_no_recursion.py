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
    super().to_plain_text() -- no concrete ancestor exists, so this resolves
    to ContentModel's abstract ``_body_text`` stub, the base case of the
    rendering chain."""

    data_type: ClassVar[str] = "rt003_direct_abc_legacy"
    component: ClassVar[str] = "Rt003DirectAbcLegacy"
    catalog_id: ClassVar[str] = "urn:test:rt003b:v1"

    def to_plain_text(self) -> str:
        parent_text = super().to_plain_text()
        return f"[{parent_text}] own"


def test_direct_abc_subclass_super_call_gets_empty_string_not_recursion():
    """DBG-7: this asserted ``"[None] own"`` — it pinned a defect as the
    contract. The subject of the test is that the call does not RECURSE; the
    ``None`` was incidental, and only survived because an f-string stringifies
    it. The concatenation form the SDK's own docs recommend
    (``"head " + super().to_plain_text()``) raised TypeError on that same
    ``None``, and the passthrough form produced ``TextPart(text=None)`` and a
    ValidationError out of ``build_artifact``. The stub now returns ``""``:
    ContentModel contributes no rendering of its own, which is what the base
    case of the chain should say. See tests/test_dbg7_root_cause_regressions.py.
    """
    card = DirectAbcSubclassLegacyOverride()
    assert card.to_plain_text() == "[] own"


class NewStyleKpiSubclass(KpiCard):
    """DBG-5 (debug round 5): the shape this SDK's own migration path
    RECOMMENDS — a NEW ``_body_text()`` override — calling
    ``super().to_plain_text()``.

    ``docs/content-types.md`` stated that this and ``super()._body_text()``
    "both resolve correctly" and differ only by "one extra indirection", and
    ``__init_subclass__``'s TypeError told authors to "move the body of
    to_plain_text() into _body_text()" without warning that a
    ``super().to_plain_text()`` call inside that body had to be rewritten. It
    did not resolve correctly: only the adopted-legacy wrapper pushed a
    re-entrancy frame, so a new-style override pushed nothing, the guard in
    ``to_plain_text()`` never fired, and the call recursed until
    ``RecursionError`` — failing every artifact emission for that card type
    (``runner.py``'s dual-part ``TextPart``, ``routes/mcp.py``'s
    ``tools/call`` text) as an internal error."""

    data_type: ClassVar[str] = "rt003_new_style_kpi_subclass"
    component: ClassVar[str] = "Rt003NewStyleKpiSubclass"
    catalog_id: ClassVar[str] = "urn:test:rt003b:v1"

    def _body_text(self) -> str:
        return super().to_plain_text() + "\nextra"


def test_new_style_body_text_super_to_plain_text_does_not_recurse():
    card = NewStyleKpiSubclass(metrics=[MetricItem(label="a", value=1)])
    assert card.to_plain_text() == "a: 1\nextra"  # previously: RecursionError


def test_new_style_body_text_super_call_carries_metadata_exactly_once():
    card = NewStyleKpiSubclass(
        metrics=[MetricItem(label="a", value=1)],
        metadata={"coverage_note": "x"},
    )
    text = card.to_plain_text()
    assert text == "a: 1\nextra\ncoverage_note=x"
    assert text.count("coverage_note=x") == 1


class NewStyleBodyTextSuper(KpiCard):
    """The RECOMMENDED call, which must keep giving the identical rendering —
    the docs promise the two differ only by the suffix indirection."""

    data_type: ClassVar[str] = "rt003_new_style_body_super"
    component: ClassVar[str] = "Rt003NewStyleBodySuper"
    catalog_id: ClassVar[str] = "urn:test:rt003b:v1"

    def _body_text(self) -> str:
        return super()._body_text() + "\nextra"


def test_both_super_spellings_render_identically():
    kwargs = {"metrics": [MetricItem(label="a", value=1)], "metadata": {"k": "v"}}
    assert (
        NewStyleKpiSubclass(**kwargs).to_plain_text()
        == NewStyleBodyTextSuper(**kwargs).to_plain_text()
    )


class NewStyleNestedSubclass(NewStyleKpiSubclass):
    """Two chained NEW-style overrides, the new-style mirror of
    ``DoublyNestedLegacySubclass`` above: each level must resolve one step up,
    not land back on itself."""

    data_type: ClassVar[str] = "rt003_new_style_nested"
    component: ClassVar[str] = "Rt003NewStyleNested"
    catalog_id: ClassVar[str] = "urn:test:rt003b:v1"

    def _body_text(self) -> str:
        return super().to_plain_text() + "\nmore"


def test_two_chained_new_style_overrides_do_not_recurse():
    card = NewStyleNestedSubclass(metrics=[MetricItem(label="a", value=1)])
    assert card.to_plain_text() == "a: 1\nextra\nmore"


class RendersAnotherCard(KpiCard):
    """A card whose rendering calls ``to_plain_text()`` on a DIFFERENT card
    instance. The re-entrancy frame carries the instance, so this is an
    ordinary top-level call and the nested card keeps its own suffix."""

    data_type: ClassVar[str] = "rt003_renders_another_card"
    component: ClassVar[str] = "Rt003RendersAnotherCard"
    catalog_id: ClassVar[str] = "urn:test:rt003b:v1"

    def _body_text(self) -> str:
        nested = KpiCard(
            metrics=[MetricItem(label="n", value=2)], metadata={"nested": "yes"}
        )
        return f"{super()._body_text()} [{nested.to_plain_text()}]"


def test_nested_other_instance_keeps_its_own_metadata_suffix():
    card = RendersAnotherCard(
        metrics=[MetricItem(label="a", value=1)], metadata={"outer": "yes"}
    )
    assert card.to_plain_text() == "a: 1 [n: 2\nnested=yes]\nouter=yes"
