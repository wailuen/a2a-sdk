"""GH-270 RT-001: `_wire_reshape` / `_wire_rule` name collisions warn, never raise.

The #270 ruling asked for one shared serializer, not a new class-creation
error, so a subclass shape that worked in v0.24.0 must still build and dump.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

import pytest
from pydantic import model_serializer

from agent_sdk.models.content_types import DocumentItem, TimeSeriesDataPoint, _Wire

LOGGER = "agent_sdk.models.content_types"


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def test_wrong_signature_wire_reshape_warns_and_is_not_called(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[int] = []

    with caplog.at_level(logging.WARNING, logger=LOGGER):

        class Helper(_Wire):
            v: int = 1

            def _wire_reshape(self) -> int:
                calls.append(1)
                return 1

    assert any("Helper._wire_reshape" in m for m in _warnings(caplog))
    assert Helper().wire() == {"v": 1}
    assert Helper()._wire_reshape() == 1  # the helper itself still works
    assert calls == [1]  # called once, by the line above, never by wire()


def test_wrong_signature_override_keeps_parent_hook() -> None:
    class Doc(DocumentItem):
        def _wire_reshape(self) -> str:  # unrelated helper, same name
            return "x"

    d = Doc(id="1", name="n", web_url="https://e/x", last_modified="2026-01-01")
    assert d.wire() == DocumentItem(**d.model_dump()).wire()
    assert d.wire()["link"] == "https://e/x"
    assert "web_url" not in d.wire()


def test_correct_signature_wire_reshape_runs(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):

        class Ok(_Wire):
            v: int = 1

            def _wire_reshape(self, data: dict[str, Any], info: Any) -> bool:
                data["extra"] = True
                return True

    assert _warnings(caplog) == []
    assert Ok().wire() == {"v": 1, "extra": True}


def test_own_serializer_with_wire_keeps_null_warns(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):

        class Own(_Wire):
            wire_keeps_null: ClassVar[frozenset[str]] = frozenset({"a"})
            a: int | None = None

            @model_serializer(mode="wrap")
            def _ser(self, handler: Any) -> Any:
                return handler(self)

    assert any("Own declares wire_keeps_null" in m for m in _warnings(caplog))
    assert Own().wire() == {}


def test_own_serializer_with_wire_omitted_warns(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):

        class Own(_Wire):
            wire_omitted: ClassVar[frozenset[str]] = frozenset({"a"})
            a: int | None = None

            @model_serializer(mode="wrap")
            def _wire_rule(self, handler: Any) -> Any:
                return handler(self)

    assert any("Own declares wire_keeps_null" in m for m in _warnings(caplog))
    assert Own(a=2).wire() == {"a": 2}


def test_own_serializer_without_wire_sets_is_silent(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):

        class Ok(_Wire):
            a: int = 1

            @model_serializer(mode="wrap")
            def _ser(self, handler: Any) -> Any:
                return handler(self)

    assert _warnings(caplog) == []
    assert Ok().wire() == {"a": 1}


def test_subclass_of_builtin_fragment_with_own_serializer_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):

        class Point(TimeSeriesDataPoint):
            @model_serializer(mode="wrap")
            def _ser(self, handler: Any) -> Any:
                return handler(self)

    assert any("Point declares wire_keeps_null" in m for m in _warnings(caplog))
    # Same as v0.24.0: an own serializer replaces the inherited one.
    assert "value" not in Point(date="2026-01-01", value=None).wire()


def test_plain_subclass_of_builtin_fragment_is_silent(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER):

        class Point(TimeSeriesDataPoint):
            note: str | None = None

    assert _warnings(caplog) == []
    assert Point(date="2026-01-01", value=None).wire() == {"date": "2026-01-01", "value": None}
