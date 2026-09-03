"""Helper for tests/test_rt003_reuse_fields_local_scope.py.

Isolated in its own module (with ``from __future__ import annotations``) so
the pydantic model factories build under deferred (string) annotations
without forcing the same on the test module — the test module needs eager
annotations so its own tool-function parameter (``inp: model``, ``model`` a
local variable) resolves without going through ``eval_str``.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel

from agent_sdk.agent.reuse import ReuseKind


def make_locally_scoped_model() -> type[BaseModel]:
    class Sibling(BaseModel):
        x: int

    class LocalInput(BaseModel):
        entity_id: Annotated[str, ReuseKind("entity_id")]
        sibling: Sibling

    return LocalInput


def make_plain_locally_scoped_model() -> type[BaseModel]:
    class Sibling(BaseModel):
        x: int

    class PlainLocalInput(BaseModel):
        sibling: Sibling
        name: str

    return PlainLocalInput
