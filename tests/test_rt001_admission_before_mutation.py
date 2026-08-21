"""RT-001/RT-002 (round 4, fresh-lens) — an admission check must run BEFORE
any durable state mutation, and EVERY indefinite SSE route must be admitted.

Root cause (RT-001): ``routes/a2a.py``'s ``_open_stream`` conflated the
admission DECISION with the subscription REGISTRATION into one call that
needs a ``TaskRecord``. ``message_stream``'s no-taskId path has no record
until ``_create_task_record()`` has already run ``task_store.create()``, so
the load-shed check ran AFTER a durable write to the LRU-bounded store.
Every 429-rejected request therefore still inserted an orphan ``TaskRecord``
(no worker, permanently 'submitted'), and ``create()`` ->
``_evict_over_capacity()`` evicts oldest-first while ``evict()`` cancels the
evicted record's worker and ``sub.close()``s its subscribers — turning the
shed path into an eviction vector that severs ANOTHER tenant's in-flight SSE
stream with no ``final:true`` frame, the exact outcome this wave's
reject-not-evict rationale exists to prevent.

Root cause (RT-002): ``POST /ag-ui/run`` is a third authenticated,
indefinitely-held ``text/event-stream`` on the same single-process
connection pool and was given no admission cap at all, leaving the DoS the
cap exists to close fully reachable via that transport.

This module verifies:
- a 429'd no-taskId ``message:stream`` writes NOTHING to the task store.
- such a rejection cannot evict another identity's pre-existing task.
- the admission slot is bound to the REAL task id once admitted, so the
  per-task cap sees it.
- ``POST /ag-ui/run`` is admitted against the same shared budget and frees
  its slot afterwards.
- a source-level completeness gate: every route in ``agent_sdk/routes/``
  returning ``media_type="text/event-stream"`` performs an admission check,
  so the next stream route cannot silently escape the budget.
"""

from __future__ import annotations

import ast
import asyncio
import pathlib
import re

import httpx
import pytest

from agent_sdk.agent.runner import new_task
from agent_sdk.auth.identity import Identity
from agent_sdk.routes import a2a as a2a_module
from agent_sdk.routes.a2a import _a2a_streams
from agent_sdk.testing import reply

from .test_ag_ui import run_body


def _send_body() -> dict:
    return {
        "message": {
            "kind": "message",
            "role": "user",
            "messageId": "m1",
            "parts": [{"kind": "text", "text": "hello"}],
        }
    }


# ---------------------------------------------------------------------------
# RT-001 — admission must precede the task-store write
# ---------------------------------------------------------------------------


async def test_rejected_no_taskid_stream_writes_nothing_to_store(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The no-taskId branch is the ONLY path that mutates the store before a
    stream opens; a shed request there must be a pure no-op."""
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS", 0)
    store = app.state.task_store
    before = len(store._records)

    r = await asyncio.wait_for(client.post("/v1/message:stream", json=_send_body()), timeout=5)

    assert r.status_code == 429, r.text
    assert r.headers.get("Retry-After") == "5"
    assert r.json()["error"]["code"] == -32000
    assert len(store._records) == before, (
        "a 429'd message:stream inserted an orphan TaskRecord — the admission "
        "check ran after task_store.create()"
    )
    assert len(_a2a_streams(app)) == 0, "a rejected request must not hold a slot"


async def test_rejected_stream_cannot_evict_another_identity_task(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cross-tenant harm: orphan records pushed a bounded store over
    capacity, and eviction cancels the victim's worker and closes its
    subscribers — severing a live stream with no final:true frame."""
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS", 0)
    store = app.state.task_store
    store._capacity = 3
    victim = store.create(new_task(), Identity(kind="api_key", subject="other-tenant"))
    victim_id = victim.task.id
    victim_sub = store.subscribe(victim_id)

    for _ in range(5):
        r = await asyncio.wait_for(
            client.post("/v1/message:stream", json=_send_body()), timeout=5
        )
        assert r.status_code == 429, r.text

    assert victim_id in store._records, (
        "429'd requests evicted another identity's task — load shedding became "
        "a cross-tenant eviction vector"
    )
    assert victim_sub in store._records[victim_id].subscriptions, (
        "the victim's in-flight subscription was closed by an eviction it never caused"
    )


async def test_admitted_stream_binds_real_task_id_to_its_slot(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The slot is reserved before the task id exists, so it must be rewritten
    to the real id once the subscription attaches — otherwise the per-task cap
    would never see streams opened on the no-taskId path, and `release` would
    never unsubscribe the subscription it owns.

    No worker is started, so the task stays SUBMITTED and the stream stays
    open — that is what makes the live slot observable."""
    monkeypatch.setattr(a2a_module, "_start_worker", lambda *a, **k: None)
    streams = _a2a_streams(app)

    inflight = asyncio.create_task(client.post("/v1/message:stream", json=_send_body()))
    try:
        try:
            await asyncio.wait_for(asyncio.shield(inflight), timeout=0.5)
        except asyncio.TimeoutError:
            pass  # expected: the stream is held open

        assert len(streams) == 1, f"expected exactly one live slot, got {dict(streams)}"
        slot_task_id = next(iter(streams.values())).task_id
        assert slot_task_id, "admitted slot kept its empty placeholder task id"
        assert slot_task_id in app.state.task_store._records, (
            f"slot task id {slot_task_id!r} is not a real task id"
        )
        record = app.state.task_store._records[slot_task_id]
        assert len(record.subscriptions) == 1, (
            "the bound slot does not own the subscription it must tear down"
        )
    finally:
        inflight.cancel()
        try:
            await inflight
        except BaseException:
            pass


# ---------------------------------------------------------------------------
# RT-002 — /ag-ui/run shares the same budget
# ---------------------------------------------------------------------------


async def test_ag_ui_run_is_admission_capped(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS", 0)
    store = app.state.task_store
    before = len(store._records)

    r = await asyncio.wait_for(client.post("/ag-ui/run", json=run_body()), timeout=5)

    assert r.status_code == 429, (
        "POST /ag-ui/run holds an indefinite text/event-stream on the same "
        f"connection pool and must be admitted against the shared budget; got {r.status_code}"
    )
    assert r.headers.get("Retry-After") == "5"
    assert len(store._records) == before, "a shed /ag-ui/run must not create a task"


async def test_ag_ui_run_releases_its_slot(
    client: httpx.AsyncClient, app, fake_model
) -> None:
    fake_model.script(reply("hi"))
    streams = _a2a_streams(app)
    assert len(streams) == 0

    r = await asyncio.wait_for(client.post("/ag-ui/run", json=run_body()), timeout=10)
    assert r.status_code == 200, r.text

    assert len(streams) == 0, (
        "a completed /ag-ui/run leaked its admission slot — the budget would "
        "drain to zero over time and reject every caller"
    )


async def test_ag_ui_run_consumes_the_shared_a2a_budget(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch, fake_model
) -> None:
    """The whole point of one shared budget: a cap on one transport must not
    be bypassable by calling the other."""
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS", 1)
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS_PER_IDENTITY", 1)
    task = app.state.task_store.create(
        new_task(), Identity(kind="api_key", subject="holder")
    )
    held = asyncio.create_task(client.post(f"/v1/tasks/{task.task.id}:subscribe"))
    try:
        # let the A2A subscribe claim the only slot
        try:
            await asyncio.wait_for(asyncio.shield(held), timeout=0.5)
        except asyncio.TimeoutError:
            pass
        assert len(_a2a_streams(app)) == 1

        r = await asyncio.wait_for(client.post("/ag-ui/run", json=run_body()), timeout=5)
        assert r.status_code == 429, (
            "an A2A stream holding the only slot did not shed an /ag-ui/run — "
            "the two transports are not sharing one budget"
        )
    finally:
        held.cancel()
        try:
            await held
        except BaseException:
            pass


# ---------------------------------------------------------------------------
# Completeness gate — no future SSE route may escape the budget (LRN-140 class)
# ---------------------------------------------------------------------------

_ROUTES_DIR = pathlib.Path(a2a_module.__file__).parent

# Any of these appearing in a handler means it performs an admission check:
# the A2A/AG-UI helpers, or mcp.py's own inline _get_streams() cap.
_ADMISSION_MARKERS = {
    "_admit",
    "_admit_stream",
    "_open_stream",
    "_prune_a2a_streams",
    "_prune_get_streams",
}


def _sse_handlers_without_admission() -> list[str]:
    offenders: list[str] = []
    for path in sorted(_ROUTES_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            src = ast.dump(node)
            returns_sse = any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "StreamingResponse"
                and any(
                    kw.arg == "media_type"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value == "text/event-stream"
                    for kw in n.keywords
                )
                for n in ast.walk(node)
            )
            if not returns_sse:
                continue
            if not any(f"'{marker}'" in src for marker in _ADMISSION_MARKERS):
                offenders.append(f"{path.name}::{node.name}")
    return offenders


def test_every_sse_route_is_admission_capped() -> None:
    """LRN-140 class: a budget added because 'capping one transport is
    bypassable via the other' must enumerate EVERY route holding an
    indefinite text/event-stream, not just the ones named in the issue.
    This gate fails the moment a new SSE route is added without admission."""
    offenders = _sse_handlers_without_admission()
    assert offenders == [], (
        "these routes return text/event-stream but perform no admission check, "
        f"so they bypass the concurrency budget entirely: {offenders}"
    )


def test_completeness_gate_actually_detects_sse_routes() -> None:
    """Guard against the gate above passing vacuously (e.g. if the AST shape
    it matches ever stops matching real handlers)."""
    found: list[str] = []
    for path in sorted(_ROUTES_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "StreamingResponse"
                and any(
                    kw.arg == "media_type"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value == "text/event-stream"
                    for kw in n.keywords
                )
                for n in ast.walk(node)
            ):
                found.append(f"{path.name}::{node.name}")
    assert {"a2a.py::message_stream", "a2a.py::tasks_resubscribe", "ag_ui.py::ag_ui_run"} <= set(
        found
    ), f"the SSE-route detector stopped seeing known stream routes; saw {found}"


# ---------------------------------------------------------------------------
# RT-003 — the 429 must be recorded on every spec surface (LRN-118)
# ---------------------------------------------------------------------------

_REPO_ROOT = pathlib.Path(a2a_module.__file__).parent.parent.parent


def _norm(text: str) -> str:
    """Collapse markdown hand-wrapping so a clause split across lines still
    matches a single-line regex (mirrors test_gh144_terminal_resume_error_docs)."""
    return re.sub(r"\s+", " ", text)


def _design_md() -> str:
    return _norm((_REPO_ROOT / "DESIGN.md").read_text())


def _protocols_md() -> str:
    return _norm((_REPO_ROOT / "docs" / "protocols.md").read_text())


def test_design_md_documents_the_stream_admission_429() -> None:
    text = _design_md()
    assert "429" in text and "Retry-After" in text
    assert re.search(r"GET /mcp`[^.]*429", text), (
        "DESIGN.md §5.5's GET /mcp bullet still describes only the "
        "text/event-stream outcome — the 429 admission response is undocumented"
    )
    assert "admission" in text.lower(), "DESIGN.md never mentions stream admission"


def test_design_md_rate_limiting_counts_three_layers() -> None:
    text = _design_md()
    assert "Rate limiting — three layers" in text, (
        "DESIGN.md §6 still claims two rate-limiting layers; concurrent-stream "
        "admission is a third"
    )
    assert "Rate limiting — two layers" not in text


def test_design_md_cites_the_spec_rule_the_429_departs_from() -> None:
    """A bare issue number is not a spec citation (LRN-118): the deviation must
    name the rule it departs from."""
    text = _design_md()
    assert "mcp-protocol.md" in text, (
        "DESIGN.md records the 429 but cites no spec rule it deviates from"
    )
    assert "405" in text, "the two-outcome GET rule (stream or 405) is not cited"


def test_protocols_md_documents_the_cap_on_both_protocol_sections() -> None:
    text = _protocols_md()
    assert "429" in text and "Retry-After" in text
    assert re.search(r"429\s*`?-32000`?", text) or re.search(r"-32000`? \+ `Retry-After", text), (
        "docs/protocols.md's A2A error table has no 429 row"
    )
    # MCP section must carry its own cap bullet, not rely on the A2A one
    mcp_section = text.split("## MCP (2025-06-18")[-1].split("## Agent card")[0]
    assert "429" in mcp_section, (
        "docs/protocols.md's MCP section documents neither the cap nor the 429"
    )


def test_mcp_module_docstring_carries_the_deviation_citation() -> None:
    import agent_sdk.routes.mcp as mcp_module

    doc = _norm(mcp_module.__doc__ or "")
    assert "429" in doc, "routes/mcp.py's docstring does not record the 429 outcome"
    assert "mcp-protocol.md" in doc, (
        "routes/mcp.py records the 429 but cites no spec rule — a bare issue "
        "number is not a spec citation (LRN-118)"
    )
    assert "mcp-claude-platforms.md" in doc, (
        "the Claude.ai 'Couldn't connect' operational consequence of a 429 on "
        "this connection-critical verb is not recorded"
    )


def test_a2a_module_docstring_records_the_429() -> None:
    doc = _norm(a2a_module.__doc__ or "")
    assert "429" in doc and "Retry-After" in doc, (
        "routes/a2a.py's docstring does not record the admission 429 its "
        "streaming verbs can return"
    )
