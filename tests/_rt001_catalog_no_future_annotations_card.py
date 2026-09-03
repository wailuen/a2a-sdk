"""Helper for tests/test_a2ui_wire.py's RT-001 regression.

Deliberately has NO ``from __future__ import annotations``. On Python 3.14
(PEP 649) a class body's annotations in a module without that import are
compiled into a lazy ``__annotate__`` function, so ``vars(cls).get(
"__annotations__", {})`` returns ``{}`` for this class even though it
genuinely redeclares ``metadata`` in its own body — the exact drift RT-001
found in ``_field_summary``'s ``declared_here`` check.

``tests/test_a2ui_wire.py`` itself carries ``from __future__ import
annotations``, which forces annotations to be eagerly stringified at class
creation on every Python version, so a card class defined directly in that
file can never reproduce this gap. It has to live here instead.
"""

from typing import ClassVar

from agent_sdk.models.content_types import ContentModel


class OwnMetadataCardNoFutureAnnotations(ContentModel):
    data_type: ClassVar[str] = "test_own_metadata_card_no_future_annotations"
    component: ClassVar[str] = "TestOwnMetadataCardNoFutureAnnotations"

    title: str
    metadata: str  # deliberately redeclared, required, different type than the base

    def to_plain_text(self) -> str:  # pragma: no cover - trivial fallback
        return self.title
