"""Regression test for GH-13: sweeper tight-loop when asyncio.sleep is patched.

The sweeper uses `_asyncio_sleep` (captured at module import time) so that
test code patching `asyncio.sleep` cannot cause the sweeper to spin to OOM.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import agent_sdk.app as _app_module


def test_asyncio_sleep_capture_is_real_sleep():
    """_asyncio_sleep must be the real asyncio.sleep at import time."""
    assert _app_module._asyncio_sleep is asyncio.sleep


def test_asyncio_sleep_capture_survives_patch():
    """Patching asyncio.sleep must not affect _asyncio_sleep."""
    original = _app_module._asyncio_sleep
    with patch("asyncio.sleep", new_callable=AsyncMock):
        assert asyncio.sleep is not original
        assert _app_module._asyncio_sleep is original
