"""RT-001 (round 6, fresh-lens) — every admitted stream must register its task
id on the admission slot it holds, and there must be no way to subscribe
without doing so.

Root cause: ``_admit`` handed back a slot whose task binding was a SEPARATE
callable the route invoked after its own ``store.subscribe()``. Exactly one
caller ever invoked it (``routes/a2a.py``'s ``_open_stream``).
``POST /ag-ui/run`` — documented in DESIGN.md §5.5 and docs/protocols.md as
sharing that budget INCLUDING its per-task subscriber cap — subscribed
straight against the store and never bound, so:

* its slots kept the ``""`` placeholder and ``count_for_task`` could neither
  cap nor count them. The per-task cap was unenforceable on the one AG-UI path
  that subscribes to an ALREADY EXISTING task (resume), and it simultaneously
  UNDER-counted for A2A: an A2A client still got its full
  ``_MAX_A2A_STREAMS_PER_TASK`` subscribers on top of the AG-UI ones on the
  same ``record.subscriptions`` — the per-frame ``store.publish`` walk the cap
  exists to bound.
* ``slot.release()`` never unsubscribed, leaving AG-UI's subscription teardown
  on the inner generator's ``finally`` ALONE — precisely the layer
  ``_open_stream``'s own docstring documents as not a lifecycle hook — so the
  BackgroundTask and ``prune_finished`` backstops reclaimed strictly less for
  AG-UI than for A2A.

The fix removes the forgettable step rather than adding a second call site:
``_ClaimedSlot`` exposes ``subscribe(task_id)``, which performs
``store.subscribe()`` and the slot update as one synchronous operation. The
source gate at the bottom of this module is what keeps that true.
"""

from __future__ import annotations

import ast
import asyncio
import pathlib

import httpx
import pytest

from agent_sdk.agent.runner import new_task
from agent_sdk.auth.identity import Identity
from agent_sdk.common.admission import count_for_task
from agent_sdk.routes import a2a as a2a_module
from agent_sdk.routes import ag_ui as ag_ui_module
from agent_sdk.routes.a2a import _a2a_streams

from .conftest import sse_frames
from .test_ag_ui import run_body


async def _hold(coro_task: "asyncio.Task", seconds: float = 0.5) -> None:
    """Let an in-flight streaming request reach its blocked state."""
    try:
        await asyncio.wait_for(asyncio.shield(coro_task), timeout=seconds)
    except asyncio.TimeoutError:
        return
    pytest.fail(f"expected the stream to stay open; it completed: {coro_task.result()}")


async def _cancel(task: "asyncio.Task") -> None:
    if not task.done():
        task.cancel()
    try:
        await task
    except BaseException:
        pass


# ---------------------------------------------------------------------------
# The slot must carry the real task id
# ---------------------------------------------------------------------------


async def test_ag_ui_run_binds_its_slot_to_the_real_task_id(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh /ag-ui/run reserves its slot before the task exists, exactly as
    A2A's no-taskId message:stream does — so it must rewrite the placeholder
    once it subscribes. Otherwise the shared budget's per-task counter is blind
    to every AG-UI subscriber on the list ``store.publish`` walks per frame."""
    monkeypatch.setattr(ag_ui_module, "_start_worker", lambda *a, **k: None)
    streams = _a2a_streams(app)

    inflight = asyncio.create_task(client.post("/ag-ui/run", json=run_body()))
    try:
        await _hold(inflight)

        assert len(streams) == 1, f"expected exactly one live slot, got {dict(streams)}"
        slot_task_id = next(iter(streams.values())).task_id
        assert slot_task_id, (
            "/ag-ui/run kept its empty placeholder task id — it subscribed "
            "outside its admission slot, so the per-task cap cannot see it"
        )
        assert slot_task_id in app.state.task_store._records, (
            f"slot task id {slot_task_id!r} is not a real task id"
        )
        assert count_for_task(streams, slot_task_id) == 1, (
            "the shared budget's per-task counter does not see the AG-UI stream"
        )
    finally:
        await _cancel(inflight)


async def test_ag_ui_slot_release_is_the_subscription_teardown(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``slot.release`` — the callable the StreamingResponse BackgroundTask and
    ``prune_finished`` both invoke — must unsubscribe, not merely drop the
    budget entry. Asserted by calling release directly while the stream is
    still open, so the inner generator's ``finally`` demonstrably is not what
    reclaimed the subscription."""
    monkeypatch.setattr(ag_ui_module, "_start_worker", lambda *a, **k: None)
    streams = _a2a_streams(app)

    inflight = asyncio.create_task(client.post("/ag-ui/run", json=run_body()))
    try:
        await _hold(inflight)
        slot = next(iter(streams.values()))
        record = app.state.task_store._records[slot.task_id]
        assert len(record.subscriptions) == 1, "the run never subscribed"

        await slot.release()

        assert record.subscriptions == [], (
            "slot.release() dropped the budget entry but left the Subscription "
            "on record.subscriptions — the two backstops that only ever call "
            "release reclaim less for AG-UI than for A2A"
        )
        assert len(streams) == 0
    finally:
        await _cancel(inflight)


# ---------------------------------------------------------------------------
# The documented per-task cap must actually cover /ag-ui/run
# ---------------------------------------------------------------------------


async def test_ag_ui_resume_is_capped_by_the_shared_per_task_cap(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The resume branch is the one AG-UI path that subscribes to an ALREADY
    EXISTING task, so it is what the per-task cap exists to bound. With the cap
    at 1 and an A2A subscriber already holding that task's only slot, the
    resume must be shed with 429 — and shed BEFORE ``RUN_STARTED``, per §5.3,
    since past that point the route may only emit ``RUN_ERROR`` frames."""
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS_PER_TASK", 1)
    store = app.state.task_store
    # Owned by another subject; the `client` fixture's key is admin, which
    # bypasses the identity binding on both lookups (store.get / find_interrupt).
    record = store.create(new_task(), Identity(kind="api_key", subject="rt001-r6-owner"))
    store.mark_interrupted(record.task.id, "rt001-r6-interrupt")

    held = asyncio.create_task(client.post(f"/v1/tasks/{record.task.id}:subscribe"))
    try:
        await _hold(held)
        streams = _a2a_streams(app)
        assert count_for_task(streams, record.task.id) == 1, dict(streams)

        r = await asyncio.wait_for(
            client.post(
                "/ag-ui/run",
                json=run_body(
                    resume=[
                        {
                            "interruptId": "rt001-r6-interrupt",
                            "status": "accepted",
                            "payload": {},
                        }
                    ]
                ),
            ),
            timeout=5,
        )

        assert r.status_code == 429, (
            "an /ag-ui/run resume onto a task already at the per-task "
            f"subscriber cap was admitted; got {r.status_code}: {r.text[:200]}"
        )
        assert r.headers.get("Retry-After") == "5"
        assert "RUN_STARTED" not in r.text, (
            "the shed happened after RUN_STARTED — §5.3 requires every failure "
            "past that frame to be a RUN_ERROR, so the cap must be enforced "
            "before the run is announced"
        )
        assert count_for_task(streams, record.task.id) == 1, (
            "a rejected resume still registered a subscriber on the task"
        )
    finally:
        await _cancel(held)


async def test_ag_ui_unknown_interrupt_is_run_error_not_a_capacity_error(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard against over-broad enforcement: resolving the resume target before
    admission must not turn an unresolvable interrupt into a 429. An unknown id
    yields no task, so the per-task check is skipped and the run is admitted —
    then reports the accurate ``RUN_ERROR`` on the stream."""
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS_PER_TASK", 1)

    r = await asyncio.wait_for(
        client.post(
            "/ag-ui/run",
            json=run_body(resume=[{"interruptId": "no-such-interrupt"}]),
        ),
        timeout=10,
    )

    assert r.status_code == 200, r.text
    frames = sse_frames(r.text)
    types = [f["type"] for f in frames]
    assert types[0] == "RUN_STARTED"
    assert types[-1] == "RUN_ERROR"
    assert frames[-1]["message"] == "unknown or expired interrupt"
    assert len(_a2a_streams(app)) == 0, "the completed run leaked its slot"


# ---------------------------------------------------------------------------
# Completeness gate — subscribing outside the slot must stay impossible
# ---------------------------------------------------------------------------

_ROUTES_DIR = pathlib.Path(a2a_module.__file__).parent


# `_ClaimedSlot.subscribe`'s implementation — the `subscribe` closure inside
# `_admit`. The single sanctioned place in `agent_sdk/routes/` where a task
# store is subscribed to directly, because it updates the slot in the same
# synchronous step.
_SANCTIONED_SUBSCRIBE_SITE = "a2a.py::subscribe"


def _direct_store_subscribe_sites() -> list[str]:
    """Every ``<name>.subscribe(...)`` call in ``agent_sdk/routes/`` whose
    receiver is not a claimed admission slot, reported as
    ``file::innermost_enclosing_function``.

    Attribution is to the INNERMOST enclosing function: routes register their
    release/subscribe logic in closures, so a nested call must not also be
    charged to every outer function that lexically contains it."""
    offenders: list[str] = []
    for path in sorted(_ROUTES_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            nested_calls = {
                id(call)
                for inner in ast.walk(node)
                if inner is not node
                and isinstance(inner, (ast.AsyncFunctionDef, ast.FunctionDef))
                for call in ast.walk(inner)
                if isinstance(call, ast.Call)
            }
            for call in ast.walk(node):
                if not isinstance(call, ast.Call) or id(call) in nested_calls:
                    continue
                func = call.func
                if not (isinstance(func, ast.Attribute) and func.attr == "subscribe"):
                    continue
                receiver = func.value
                if isinstance(receiver, ast.Name) and receiver.id == "slot":
                    continue  # the sanctioned path: through the admission slot
                offenders.append(f"{path.name}::{node.name}")
    return offenders


def test_routes_only_subscribe_through_their_admission_slot() -> None:
    """LRN-140 class. The per-task cap and the slot's unsubscribe-on-release
    both depend on the task id reaching the slot, and the ONLY thing that
    guarantees it is that ``store.subscribe()`` is unreachable from a route
    except via ``_ClaimedSlot.subscribe``. Any other direct store subscribe in
    a route reintroduces the bug by omission, silently, exactly as
    ``/ag-ui/run`` did."""
    offenders = _direct_store_subscribe_sites()
    assert offenders == [_SANCTIONED_SUBSCRIBE_SITE], (
        "a route subscribes to the task store outside its admission slot, so "
        "its stream is invisible to the per-task cap and its subscription is "
        f"not torn down by slot.release: {offenders}"
    )


def test_subscribe_gate_is_not_vacuous() -> None:
    """The gate above asserts an exact list; prove the detector still sees the
    one sanctioned site rather than silently matching nothing."""
    assert _SANCTIONED_SUBSCRIBE_SITE in _direct_store_subscribe_sites(), (
        "the detector stopped seeing _ClaimedSlot.subscribe's own "
        "store.subscribe() call — the gate would pass vacuously for every route"
    )
