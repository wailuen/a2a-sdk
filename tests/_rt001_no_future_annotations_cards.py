"""Domain cards defined WITHOUT ``from __future__ import annotations``.

RT-001: the absence of that import is the entire point of this module -- do NOT
add it, and do not merge these classes into a test module that has it.

``catalog._field_summary`` decides whether a card declared a field ITSELF (and
so must keep it in its LLM teaching string) or merely inherited it from
``ContentModel`` (and so must drop it). That check used to read
``vars(cls)["__annotations__"]`` directly. Under PEP 649 (Python 3.14+) a class
body's annotations compile to a lazy ``__annotate__`` function and
``__annotations__`` is absent from the class ``__dict__`` until something forces
it -- but ONLY for classes in a module without the PEP-563 future import, which
still stores plain strings eagerly. So the raw read returned ``{}`` on 3.14 for
exactly these classes, silently answering "not declared here" for everything,
while 3.12/3.13 kept working.

The three regression tests that were meant to lock this behaviour live in
``tests/test_a2ui_wire.py``, which declares the future import at line 9 -- so
they passed on 3.14 against broken code. Pinning the cards here, in a module
that deliberately omits it, is what makes the interpreter-version dependence
impossible to mask again.
"""

from typing import ClassVar

from agent_sdk.models.content_types import ContentModel


class NoFutureOwnMetadataCard(ContentModel):
    """Redeclares ``metadata`` with its own domain semantics (required, str)."""

    data_type: ClassVar[str] = "rt001_no_future_own_metadata"
    component: ClassVar[str] = "Rt001NoFutureOwnMetadata"

    title: str
    metadata: str

    def _body_text(self) -> str:
        return self.title


class NoFutureGrandchildCard(NoFutureOwnMetadataCard):
    """Two levels deep: inherits the DOMAIN ``metadata`` declaration above,
    which must still count as declared (RT-008's MRO walk)."""

    data_type: ClassVar[str] = "rt001_no_future_grandchild"
    component: ClassVar[str] = "Rt001NoFutureGrandchild"


class NoFutureInheritedMetadataCard(ContentModel):
    """Does NOT redeclare ``metadata`` -- the base-class field must be skipped."""

    data_type: ClassVar[str] = "rt001_no_future_inherited_metadata"
    component: ClassVar[str] = "Rt001NoFutureInheritedMetadata"

    title: str

    def _body_text(self) -> str:
        return self.title
