"""Unit coverage for the shared RT-004 Origin guard predicate (C-009).

Locks the contract in isolation so any future change to the allow-list
semantics (null Origin, subdomain matching, case-folding, ...) is exercised
here regardless of which route module calls it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agent_sdk.common.origin import guard_origin


def _request(origin: str | None, allowed: frozenset[str]) -> SimpleNamespace:
    return SimpleNamespace(
        headers={"origin": origin} if origin is not None else {},
        app=SimpleNamespace(state=SimpleNamespace(cors_origins=allowed)),
    )


def test_guard_origin_allows_absent_origin() -> None:
    guard_origin(_request(None, frozenset({"https://claude.ai"})))


def test_guard_origin_allows_allowlisted_origin() -> None:
    guard_origin(_request("https://claude.ai", frozenset({"https://claude.ai"})))


def test_guard_origin_rejects_disallowed_origin() -> None:
    with pytest.raises(HTTPException) as exc_info:
        guard_origin(_request("https://evil.example.com", frozenset({"https://claude.ai"})))
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "origin not allowed"
