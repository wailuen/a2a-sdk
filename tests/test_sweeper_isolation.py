"""Regression test for GH-13: sweeper tight-loop when asyncio.sleep is patched.

The sweeper uses `_asyncio_sleep` (captured at module import time) so that
test code patching `asyncio.sleep` cannot cause the sweeper to spin to OOM.
"""
from __future__ import annotations

import asyncio
import inspect
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


def test_sweeper_calls_captured_sleep_not_asyncio_sleep():
    """The _sweeper closure must call _asyncio_sleep, not asyncio.sleep.

    A future refactor that reverts to `await asyncio.sleep(...)` would pass
    the identity tests above but fail here — closing the regression gap.
    """
    # Find _sweeper via the lifespan source; inspect its closure for the sleep call.
    source = inspect.getsource(_app_module)
    # The sweeper body must reference _asyncio_sleep, not asyncio.sleep directly.
    assert "await _asyncio_sleep(" in source, (
        "_sweeper must call _asyncio_sleep(), not asyncio.sleep() — "
        "the captured reference is what isolates the sweeper from test patches"
    )
    assert "await asyncio.sleep(" not in source, (
        "asyncio.sleep() called directly in app.py — this is the GH-13 OOM vector; "
        "use _asyncio_sleep() instead"
    )
