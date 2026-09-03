"""RT-003 regression: `reuse_fields_for_model` must not re-resolve a pydantic
model's annotations with `typing.get_type_hints`.

`get_type_hints` resolves string annotations against module globals only,
while pydantic v2 also resolves them against the defining frame's local
namespace. A tool whose `input_model` is built inside a function — and
references a sibling locally-defined class on an unrelated field — builds
fine under pydantic (`model_fields` is fully populated) but crashed
`reuse_fields_for_model` with `NameError` at `@tools.tool` decoration time
(registry.py), breaking tool registration for tools that use no `ReuseKind`
at all.

Fix: read the already-resolved metadata pydantic stores on
`input_model.model_fields[...].metadata` instead of re-resolving
annotations.

Deliberately NOT `from __future__ import annotations` here — the locally-
scoped model factories live in `tests/_rt003_local_model_helper.py` (which
does use it, so their fields are genuinely deferred/string annotations, the
condition that triggers the bug), while this module's own tool-function
parameter (`inp: model`, `model` a local variable) needs eager annotation
evaluation so registering the test tool doesn't hit an unrelated NameError
of its own.
"""

from typing import Any

import pytest

from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.reuse import reuse_fields_for_model
from tests._rt003_local_model_helper import (
    make_locally_scoped_model,
    make_plain_locally_scoped_model,
)


def test_reuse_fields_for_model_handles_locally_scoped_sibling_type():
    model = make_locally_scoped_model()

    result = reuse_fields_for_model(model)

    assert result == {"entity_id": "entity_id"}


def test_tool_registration_succeeds_for_locally_scoped_input_model():
    tools = ToolSet()
    model = make_locally_scoped_model()

    @tools.tool(tier=1)
    async def uses_local_model(inp: model) -> Any:
        """A tool whose input_model closes over a locally-defined sibling type."""
        return inp.entity_id

    registry = ToolRegistry([tools], {})
    entry = registry.get("uses_local_model")
    assert entry.decl.reuse_fields == {"entity_id": "entity_id"}


def test_plain_local_model_with_no_reuse_kind_still_registers():
    tools = ToolSet()
    model = make_plain_locally_scoped_model()

    @tools.tool(tier=1)
    async def uses_plain_local_model(inp: model) -> Any:
        """Untouched by ReuseKind — must register with an empty reuse map."""
        return inp.name

    registry = ToolRegistry([tools], {})
    entry = registry.get("uses_plain_local_model")
    assert entry.decl.reuse_fields == {}


@pytest.mark.parametrize("_unused", [None])
def test_reuse_fields_for_model_none_input_model_still_empty(_unused):
    assert reuse_fields_for_model(None) == {}
