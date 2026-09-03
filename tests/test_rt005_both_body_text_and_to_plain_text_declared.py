"""RT-005: declaring BOTH ``_body_text()`` and ``to_plain_text()`` on the same
subclass must not silently drop the ``metadata`` suffix.

``ContentModel.__init_subclass__`` only adopts a legacy ``to_plain_text()``
override into ``_body_text()`` when the subclass has NOT also declared its own
``_body_text()`` (``"_body_text" in own`` short-circuits adoption). When a
subclass declares both, its own ``to_plain_text()`` is left in place and
shadows the concrete ``ContentModel.to_plain_text()`` — the exact "one card
... forgets the call" drift the class docstring (content_types.py:198-212)
claims is now structurally impossible.

Fixed: declaring both is a class-definition-time error. The author must
delete the stale ``to_plain_text()`` override and let ``_body_text()`` alone
define the card's rendering.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from agent_sdk.models.content_types import ContentModel


def test_declaring_both_body_text_and_to_plain_text_raises_at_class_definition():
    with pytest.raises(TypeError, match="to_plain_text"):

        class Both(ContentModel):
            data_type: ClassVar[str] = "rt005_both"
            component: ClassVar[str] = "Rt005Both"
            catalog_id: ClassVar[str] = "urn:test:rt005:v1"

            n: int

            def _body_text(self) -> str:
                return f"Body: {self.n}"

            def to_plain_text(self) -> str:
                return f"TPT: {self.n}"


def test_error_names_the_offending_class():
    with pytest.raises(TypeError, match="BothNamed"):

        class BothNamed(ContentModel):
            data_type: ClassVar[str] = "rt005_both_named"
            component: ClassVar[str] = "Rt005BothNamed"
            catalog_id: ClassVar[str] = "urn:test:rt005:v1"

            def _body_text(self) -> str:
                return "x"

            def to_plain_text(self) -> str:
                return "y"


def test_body_text_only_still_works_unaffected():
    class BodyOnly(ContentModel):
        data_type: ClassVar[str] = "rt005_body_only"
        component: ClassVar[str] = "Rt005BodyOnly"
        catalog_id: ClassVar[str] = "urn:test:rt005:v1"

        n: int

        def _body_text(self) -> str:
            return f"Body: {self.n}"

    card = BodyOnly(n=1, metadata={"k": "v"})
    assert card.to_plain_text() == "Body: 1\nk=v"


def test_legacy_to_plain_text_only_still_adopted_unaffected():
    class LegacyOnly(ContentModel):
        data_type: ClassVar[str] = "rt005_legacy_only"
        component: ClassVar[str] = "Rt005LegacyOnly"
        catalog_id: ClassVar[str] = "urn:test:rt005:v1"

        n: int

        def to_plain_text(self) -> str:
            return f"Legacy: {self.n}"

    card = LegacyOnly(n=1, metadata={"k": "v"})
    assert card.to_plain_text() == "Legacy: 1\nk=v"
