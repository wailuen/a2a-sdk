"""RT-004: admin.py's and loop.py's generic ``except Exception`` catch-alls
claimed parity with routes/mcp.py's identical branch (comments citing
"mirroring routes/mcp.py's identical catch-all branch" / "at parity with the
mcp.py/admin.py siblings (C-012 cross-surface contract)"), but only mcp.py
actually logged frame LOCATIONS (file:line, RT-010) alongside the exception
type — admin.py and loop.py stayed type-only. The claim was false.

Fix: a shared ``frame_locations()`` helper (agent_sdk/common/redact.py,
next to ``safe_error_text``) is now called from every generic catch-all —
mcp.py, admin.py's try-tool, and all three of loop.py's dispatch sites — so
the parity comments describe what actually landed.
"""

from __future__ import annotations

import gc
import logging
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest

from agent_sdk.agent.events import ToolResultEvent
from agent_sdk.agent.loop import ToolInterrupt, run_loop
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.contrib.commitments import STATUS_FAILED
from agent_sdk.contrib.commitments.executor import CommitmentExecutor
from agent_sdk.contrib.commitments.store import CommitmentStore
from agent_sdk.example.agent import make_agent
from agent_sdk.testing import FakeModelClient, tool_call

_THIS_FILE = __file__.rsplit("/", 1)[-1]

# ── admin.py's try-tool catch-all ──

admin_tools = ToolSet()


@admin_tools.tool(tier=1)
async def rt004_admin_crash_tool() -> dict[str, Any]:
    """Raises a plain, non-validation exception from the tool body."""
    raise RuntimeError("boom")


@pytest.fixture
def crash_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [admin_tools]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def crash_client(crash_app):
    async with crash_app.router.lifespan_context(crash_app):
        _, token = crash_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=crash_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            yield c


async def test_admin_try_tool_catchall_logs_frame_locations(crash_client, sdk_caplog) -> None:
    with sdk_caplog("agent_sdk.admin", logging.ERROR) as records:
        r = await crash_client.post("/admin/api/tools/rt004_admin_crash_tool/try", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is False, body
    assert "boom" not in r.text, "SI-2 leak: exception message echoed on the wire"

    assert records, "expected the catch-all branch to log something diagnosable"
    joined = " ".join(record.getMessage() for record in records)
    assert "RuntimeError" in joined, joined
    assert "frames=" in joined, (
        f"expected file:line frame locations for diagnosability, got: {joined!r}"
    )
    assert _THIS_FILE in joined, f"expected the raise site's own file:line in frames, got: {joined!r}"

    for record in records:
        assert "boom" not in record.getMessage(), (
            f"SI-2 leak: exception message in log: {record.getMessage()!r}"
        )
        assert record.exc_info is None, (
            "frames must be logged as plain file:line text, not a live "
            "traceback object via exc_info=True (SI-2)"
        )


# ── loop.py's three dispatch-site catch-alls ──

loop_tools = ToolSet()


@loop_tools.tool(tier=1)
async def rt004_loop_crash_tool() -> dict[str, Any]:
    raise RuntimeError("boom")


@loop_tools.tool(tier=1)
async def rt004_loop_crash_gen_tool() -> AsyncGenerator[Any, None]:
    raise RuntimeError("boom")
    yield {}  # pragma: no cover — unreachable, keeps this an async generator


async def _rt004_bad_resume_handler(resume_value: Any) -> Any:
    raise RuntimeError("boom")


@loop_tools.tool(tier=1)
async def rt004_loop_interrupt_crash_tool() -> dict[str, Any]:
    raise ToolInterrupt(
        "confirm", "please confirm", resume_handler=_rt004_bad_resume_handler
    )


REGISTRY = ToolRegistry([loop_tools], {})


async def _wait_resume(interrupt_id: str) -> Any:
    return {"confirmed": True}


async def _collect(model: FakeModelClient, *, with_resume: bool = False) -> list[Any]:
    events: list[Any] = []
    async for ev in run_loop(
        model=model,
        registry=REGISTRY,
        adapters={},
        system="test",
        messages=[{"role": "user", "content": [{"text": "go"}]}],
        wait_resume=_wait_resume if with_resume else None,
    ):
        events.append(ev)
    return events


def _tool_result(events: list[Any]) -> ToolResultEvent:
    results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert results, "expected at least one ToolResultEvent"
    return results[0]


def _assert_frames_logged(records: list[logging.LogRecord]) -> None:
    assert records, "expected the catch-all branch to log something diagnosable"
    joined = " ".join(record.getMessage() for record in records)
    assert "RuntimeError" in joined, joined
    assert "frames=" in joined, (
        f"expected file:line frame locations for diagnosability, got: {joined!r}"
    )
    assert _THIS_FILE in joined, f"expected the raise site's own file:line in frames, got: {joined!r}"
    for record in records:
        assert "boom" not in record.getMessage(), (
            f"SI-2 leak: exception message in log: {record.getMessage()!r}"
        )
        assert record.exc_info is None, (
            "frames must be logged as plain file:line text, not a live "
            "traceback object via exc_info=True (SI-2)"
        )


async def test_loop_coroutine_dispatch_catchall_logs_frame_locations(sdk_caplog) -> None:
    model = FakeModelClient([tool_call("rt004_loop_crash_tool", {})])
    with sdk_caplog("agent_sdk.agent.loop", logging.ERROR) as records:
        result = _tool_result(await _collect(model))
    assert not result.ok
    assert result.error == "tool 'rt004_loop_crash_tool' failed", result.error
    _assert_frames_logged(records)


async def test_loop_generator_dispatch_catchall_logs_frame_locations(sdk_caplog) -> None:
    model = FakeModelClient([tool_call("rt004_loop_crash_gen_tool", {})])
    with sdk_caplog("agent_sdk.agent.loop", logging.ERROR) as records:
        result = _tool_result(await _collect(model))
    assert not result.ok
    assert result.error == "tool 'rt004_loop_crash_gen_tool' failed", result.error
    _assert_frames_logged(records)


async def test_loop_resume_handler_catchall_logs_frame_locations(sdk_caplog) -> None:
    model = FakeModelClient([tool_call("rt004_loop_interrupt_crash_tool", {})])
    with sdk_caplog("agent_sdk.agent.loop", logging.ERROR) as records:
        result = _tool_result(await _collect(model, with_resume=True))
    assert not result.ok
    assert result.error == "tool 'rt004_loop_interrupt_crash_tool' failed after resume", (
        result.error
    )
    _assert_frames_logged(records)


# ── commitments executor's generic catch-all (RT-012: the FOURTH C-012
# dispatch surface, alongside admin.py and loop.py's three sites above) ──


class _Rt004CommitmentEntry:
    async def invoke_any(self, args: dict, adapters: dict) -> Any:
        raise RuntimeError("boom")


class _Rt004CommitmentRegistry:
    def get(self, name: str) -> _Rt004CommitmentEntry | None:
        return _Rt004CommitmentEntry() if name == "rt004_commitment_crash_tool" else None


def _rt004_past() -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=60)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


async def test_commitments_executor_catchall_logs_frame_locations(tmp_path, sdk_caplog) -> None:
    store = CommitmentStore(tmp_path / "commitments.db")
    store.initialize()
    cid = store.add(
        tool="rt004_commitment_crash_tool", args={}, fire_at=_rt004_past()
    )
    executor = CommitmentExecutor(store, _Rt004CommitmentRegistry(), {})

    with sdk_caplog("agent_sdk.contrib.commitments", logging.ERROR) as records:
        await executor.tick_once()

    row = store._fetch_row(cid)
    assert row["status"] == STATUS_FAILED
    assert row["last_error"] == "RuntimeError"
    assert "boom" not in str(dict(row)), "SI-2 leak: exception message persisted"

    _assert_frames_logged(records)
    store.close()
