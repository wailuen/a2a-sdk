"""RT-011 regression (redteam finding on reuse.py, low severity):
``Reusable(value=None, ...)`` is permanently inert — ``resolve_reuse_fields``
treats an explicit ``None`` argument as "not supplied" and never checks it
against the index (RT-018), so such a resolution could never be matched by
a raw value or referenced via ``$ref:<kind>``. ``Reusable`` now rejects
``None`` at construction time rather than shipping a marker nothing can
ever use.

A dict/``BaseModel``-valued ``Reusable`` is deliberately NOT rejected here —
see ``Reusable``'s docstring and
``tests/test_rt002_invoke_any_reusable_unwrap.py``'s
``rt002_reusable_with_emits_tool``/``..._dict_tool`` for the legitimate,
already-shipped pattern of wrapping a tool's full structured result to
participate in the resolved-value/audit machinery without ever being
``$ref``-matchable.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from agent_sdk.agent.reuse import Reusable


def test_reusable_none_value_rejected():
    with pytest.raises(TypeError, match="must not be None"):
        Reusable(value=None, kind="entity_id", label="Acme")


def test_reusable_scalar_value_still_works():
    r = Reusable(value="ENT_1", kind="entity_id", label="Acme")
    assert r.value == "ENT_1"


def test_reusable_dict_value_still_works():
    """Not rejected — a documented, tested pattern for a tool wrapping its
    full structured result (see module docstring above)."""
    r = Reusable(value={"metrics": [{"label": "Revenue", "value": 42}]}, kind="x", label="y")
    assert r.value == {"metrics": [{"label": "Revenue", "value": 42}]}


def test_reusable_basemodel_value_still_works():
    class Card(BaseModel):
        title: str

    r = Reusable(value=Card(title="Q3"), kind="x", label="y")
    assert r.value == Card(title="Q3")
