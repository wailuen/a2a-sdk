"""contrib.commitments — durable scheduled tool execution.

Layers:
  1. store     — add/claim/mark/cancel/get/list/reap over a real temp SQLite DB:
                 at-most-once claim, canonical fire_at, identity binding, and
                 SECRETS HYGIENE (secret-in-args refused, auth_context masked).
  2. executor  — fires due commitments via a fake registry+adapters: happy path,
                 unknown tool, AgentError vs generic-exception failure (no leak),
                 fire_auth hook ordering, future-not-fired, at-most-once.
  3. source    — CommitmentsSource: schedule (require_future), typed validation
                 errors, identity-scoped cancel/get/list, non-HTTP, aclose.
  4. lifespan  — commitments_lifespan: reuses a source store / stands up its own,
                 sets app.state.commitment_store, cancels the poller on exit.
"""

from __future__ import annotations

import gc
import os
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agent_sdk.models.errors import AgentError, ErrorCategory
from agent_sdk.contrib.commitments import (
    Commitment,
    CommitmentBackend,
    CommitmentExecutor,
    CommitmentStore,
    CommitmentsSource,
    commitments_lifespan,
    STATUS_FAILED,
    STATUS_FIRED,
    STATUS_FIRING,
    STATUS_PENDING,
)


# ── helpers ──
def _store(tmp_path) -> CommitmentStore:
    s = CommitmentStore(os.path.join(tmp_path, "commitments.db"))
    s.initialize()
    return s


def _past(seconds: int = 60) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _future(seconds: int = 3600) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


@pytest.fixture()
def tmp_path_str():
    with tempfile.TemporaryDirectory() as d:
        yield d


class FakeEntry:
    """Stands in for agent.registry.ToolEntry — records invocations."""

    def __init__(self, fn):
        self._fn = fn
        self.calls: list[tuple] = []

    async def invoke(self, args, adapters):
        self.calls.append((args, adapters))
        return await self._fn(args, adapters)


class FakeRegistry:
    def __init__(self, entries: dict):
        self._entries = entries

    def get(self, name):
        return self._entries.get(name)


# ── 1. store ──
def test_add_normalizes_fire_at_to_canonical_utc(tmp_path_str):
    s = _store(tmp_path_str)
    # offset form must round-trip to the equivalent UTC Z instant
    cid = s.add(tool="t", args={}, fire_at="2020-01-01T05:00:00+05:00")
    c = s.get(cid)
    assert c.fire_at == "2020-01-01T00:00:00Z"
    assert c.status == STATUS_PENDING


def test_claim_due_returns_only_due_pending(tmp_path_str):
    s = _store(tmp_path_str)
    due_id = s.add(tool="t", args={"n": 1}, fire_at=_past())
    s.add(tool="t", args={"n": 2}, fire_at=_future())  # not due
    claimed = s.claim_due()
    assert [c.id for c in claimed] == [due_id]
    assert claimed[0].status == STATUS_FIRING
    assert claimed[0].args == {"n": 1}
    assert claimed[0].attempts == 1


def test_claim_due_is_at_most_once(tmp_path_str):
    s = _store(tmp_path_str)
    s.add(tool="t", args={}, fire_at=_past())
    first = s.claim_due()
    second = s.claim_due()  # already 'firing' → not re-claimed
    assert len(first) == 1
    assert second == []


def test_claim_due_now_override_selects_by_injected_clock(tmp_path_str):
    # Validates the ``now`` parameter of claim_due(): an injected UTC timestamp
    # controls what is "due", enabling deterministic testing without wall-clock
    # dependency.  Also proves the canonical-UTC comparison works end-to-end.
    s = _store(tmp_path_str)
    # fire_at is fixed in "the future" relative to real wall-clock time
    target_fire_at = "2099-01-01T12:00:00Z"
    cid = s.add(tool="t", args={"n": 99}, fire_at=target_fire_at)
    # Without override: the commitment is not due yet
    assert s.claim_due() == []
    # With injected now beyond fire_at: the commitment becomes due
    claimed = s.claim_due(now="2099-01-01T13:00:00Z")
    assert [c.id for c in claimed] == [cid]
    assert claimed[0].status == STATUS_FIRING
    assert claimed[0].args == {"n": 99}


def test_mark_fired_and_failed_are_terminal(tmp_path_str):
    s = _store(tmp_path_str)
    a = s.add(tool="t", args={}, fire_at=_past())
    b = s.add(tool="t", args={}, fire_at=_past())
    s.claim_due()
    s.mark_fired(a)
    s.mark_failed(b, "upstream")
    assert s.get(a).status == STATUS_FIRED
    bad = s.get(b)
    assert bad.status == STATUS_FAILED


def test_cancel_pending_then_not_fired(tmp_path_str):
    s = _store(tmp_path_str)
    cid = s.add(tool="t", args={}, fire_at=_past())
    assert s.cancel(cid) is True
    assert s.claim_due() == []  # cancelled rows are never due
    # cancelling again (no longer pending) is a no-op
    assert s.cancel(cid) is False


def test_cancel_is_identity_scoped(tmp_path_str):
    s = _store(tmp_path_str)
    cid = s.add(tool="t", args={}, fire_at=_future(), identity_binding="user:alice")
    # wrong identity cannot cancel (no-op, existence not leaked)
    assert s.cancel(cid, identity_binding="user:bob") is False
    assert s.get(cid).status == STATUS_PENDING
    # correct identity cancels
    assert s.cancel(cid, identity_binding="user:alice") is True


def test_get_is_identity_bound(tmp_path_str):
    s = _store(tmp_path_str)
    cid = s.add(tool="t", args={}, fire_at=_future(), identity_binding="user:alice")
    assert s.get(cid, identity_binding="user:bob") is None  # mismatch → None
    assert s.get(cid, identity_binding="user:alice").id == cid
    assert s.get(cid).id == cid  # None binding bypasses (admin/unbound)


def test_list_is_identity_scoped_and_status_filtered(tmp_path_str):
    s = _store(tmp_path_str)
    s.add(tool="t", args={}, fire_at=_future(), identity_binding="user:alice")
    s.add(tool="t", args={}, fire_at=_future(), identity_binding="user:alice")
    s.add(tool="t", args={}, fire_at=_future(), identity_binding="user:bob")
    alice = s.list(identity_binding="user:alice")
    assert len(alice) == 2 and all(c.identity_binding == "user:alice" for c in alice)
    assert len(s.list()) == 3  # unscoped sees all
    assert s.list(status=STATUS_PENDING, identity_binding="user:bob")[0].identity_binding == "user:bob"


def test_reap_stale_firing_fails_not_retries(tmp_path_str):
    s = _store(tmp_path_str)
    cid = s.add(tool="t", args={}, fire_at=_past())
    s.claim_due()  # → firing, claimed_at = now
    # white-box: age the claim so it is older than the lease
    s._conn.execute(
        "UPDATE commitments SET claimed_at=? WHERE id=?",
        ("2000-01-01T00:00:00Z", cid),
    )
    s._conn.commit()
    reaped = s.reap_stale_firing(lease_seconds=300)
    assert reaped == 1
    # reaped → failed (NOT back to pending — never auto-retried)
    failed = s.get(cid)
    assert failed.status == STATUS_FAILED
    assert s.claim_due() == []


def test_recent_firing_is_not_reaped(tmp_path_str):
    s = _store(tmp_path_str)
    cid = s.add(tool="t", args={}, fire_at=_past())
    s.claim_due()
    assert s.reap_stale_firing(lease_seconds=300) == 0  # just claimed → within lease
    assert s.get(cid).status == STATUS_FIRING


def test_secret_named_key_in_args_is_refused(tmp_path_str):
    s = _store(tmp_path_str)
    SENTINEL = "ZZ-SECRET-VALUE-ZZ"  # distinctive so it can't appear in a generic msg
    cases = (
        {"access_token": SENTINEL},
        {"nested": {"api_key": SENTINEL}},
        {"password": SENTINEL},
    )
    for bad in cases:
        with pytest.raises(ValueError) as ei:
            s.add(tool="t", args=bad, fire_at=_future())
        # generic message — never echoes the offending value
        assert SENTINEL not in str(ei.value)


def test_auth_context_secret_values_masked_on_persist(tmp_path_str):
    s = _store(tmp_path_str)
    cid = s.add(
        tool="t",
        args={},
        fire_at=_future(),
        auth_context={"home_account_id": "oid.tid", "refresh_token": "SECRET"},
    )
    ctx = s.get(cid).auth_context
    assert ctx["home_account_id"] == "oid.tid"  # non-secret reference preserved
    assert ctx["refresh_token"] == "[redacted]"  # secret-named value masked
    assert "SECRET" not in str(ctx)


def test_deeply_nested_secret_is_refused_fail_closed(tmp_path_str):
    # A secret buried deeper than the inspection cap must still be refused — the
    # refusal must not be laxer than redact()'s fail-closed masking.
    s = _store(tmp_path_str)
    deep = cur = {}
    for _ in range(15):
        cur["x"] = {}
        cur = cur["x"]
    cur["access_token"] = "ZZ-DEEP-SECRET-ZZ"
    with pytest.raises(ValueError):
        s.add(tool="t", args=deep, fire_at=_future())


def test_non_serializable_args_raise_valueerror_not_typeerror(tmp_path_str):
    # bytes/set/objects are not JSON-serializable; the boundary must map that to
    # ValueError (→ AgentError VALIDATION at the source), never an untyped crash.
    s = _store(tmp_path_str)
    for bad in ({"blob": b"raw"}, {"s": {1, 2, 3}}, {"o": object()}):
        with pytest.raises(ValueError):
            s.add(tool="t", args=bad, fire_at=_future())


def test_oversize_args_rejected(tmp_path_str):
    s = _store(tmp_path_str)
    with pytest.raises(ValueError):
        s.add(tool="t", args={"big": "x" * (64 * 1024 + 1)}, fire_at=_future())


def test_blank_identity_binding_rejected(tmp_path_str):
    # An empty/blank binding would bucket all "unknown identity" callers together
    # (cross-user read/cancel/re-mint). Force None or a real owner key.
    s = _store(tmp_path_str)
    for blank in ("", "   "):
        with pytest.raises(ValueError):
            s.add(tool="t", args={}, fire_at=_future(), identity_binding=blank)
    # None is still allowed (explicit admin/unbound path)
    assert s.add(tool="t", args={}, fire_at=_future(), identity_binding=None)


def test_invalid_fire_at_raises_valueerror(tmp_path_str):
    s = _store(tmp_path_str)
    with pytest.raises(ValueError):
        s.add(tool="t", args={}, fire_at="not-a-timestamp")


def test_terminal_transition_is_guarded_on_firing(tmp_path_str):
    # mark_fired/mark_failed only complete a row still 'firing'; a row that never
    # claimed (still 'pending') is untouched and the call reports it didn't win.
    s = _store(tmp_path_str)
    cid = s.add(tool="t", args={}, fire_at=_future())  # pending, never claimed
    assert s.mark_fired(cid) is False
    assert s.get(cid).status == STATUS_PENDING
    assert s.mark_failed(cid, "x") is False
    assert s.get(cid).status == STATUS_PENDING


def test_late_mark_fired_cannot_relabel_reaped_row(tmp_path_str):
    # The reaper/firer race: a row reaped to 'failed' must not be flipped back to
    # 'fired' by a late completion. mark_fired returns False and the row stays.
    s = _store(tmp_path_str)
    cid = s.add(tool="t", args={}, fire_at=_past())
    s.claim_due()  # → firing
    s._conn.execute(
        "UPDATE commitments SET claimed_at=? WHERE id=?", ("2000-01-01T00:00:00Z", cid)
    )
    s._conn.commit()
    assert s.reap_stale_firing(lease_seconds=300) == 1  # → failed
    assert s.mark_fired(cid) is False  # late completion loses
    assert s.get(cid).status == STATUS_FAILED


def test_mark_failed_scrubs_and_truncates_reason(tmp_path_str):
    # Defense-in-depth: even if a caller passes a leaky reason, the sink scrubs
    # bearer tokens and bounds length before it reaches the DB.
    s = _store(tmp_path_str)
    cid = s.add(tool="t", args={}, fire_at=_past())
    s.claim_due()  # → firing
    s.mark_failed(cid, "Bearer eyJraw.token.value extra " + "z" * 500)
    row = s._fetch_row(cid)
    assert "eyJraw.token.value" not in row["last_error"]  # bearer scrubbed
    assert "[redacted]" in row["last_error"]
    assert len(row["last_error"]) <= 200  # truncated


def test_store_methods_raise_after_close(tmp_path_str):
    s = _store(tmp_path_str)
    s.close()
    with pytest.raises(RuntimeError):
        s.add(tool="t", args={}, fire_at=_future())
    with pytest.raises(RuntimeError):
        s.claim_due()
    with pytest.raises(RuntimeError):
        s.get("nope")


def test_close_is_idempotent(tmp_path_str):
    s = _store(tmp_path_str)
    s.close()
    s.close()  # must not raise
    assert s._closed is True


def test_store_del_tolerates_partial_init_before_lock():
    s = CommitmentStore.__new__(CommitmentStore)
    s._closed = False
    s.__del__()  # must not raise if __init__ failed before _lock/_conn
    assert s._closed is True


def test_store_constructor_failure_has_quiet_del(tmp_path):
    parent_as_file = tmp_path / "not-a-directory"
    parent_as_file.write_text("x")
    with pytest.raises(FileExistsError):
        CommitmentStore(parent_as_file / "commitments.db")
    gc.collect()


# ── 2. executor ──
async def _ok_tool(args, adapters):
    return {"ok": True}


async def test_executor_fires_due_commitment(tmp_path_str):
    s = _store(tmp_path_str)
    cid = s.add(tool="send", args={"x": 1}, fire_at=_past())
    entry = FakeEntry(_ok_tool)
    ex = CommitmentExecutor(s, FakeRegistry({"send": entry}), {})
    fired = await ex.tick_once()
    assert fired == 1
    assert entry.calls == [({"x": 1}, {})]
    assert s.get(cid).status == STATUS_FIRED


async def test_executor_future_commitment_not_fired(tmp_path_str):
    s = _store(tmp_path_str)
    cid = s.add(tool="send", args={}, fire_at=_future())
    entry = FakeEntry(_ok_tool)
    ex = CommitmentExecutor(s, FakeRegistry({"send": entry}), {})
    assert await ex.tick_once() == 0
    assert entry.calls == []
    assert s.get(cid).status == STATUS_PENDING


async def test_executor_unknown_tool_marked_failed(tmp_path_str):
    s = _store(tmp_path_str)
    cid = s.add(tool="missing", args={}, fire_at=_past())
    ex = CommitmentExecutor(s, FakeRegistry({}), {})
    await ex.tick_once()
    assert s.get(cid).status == STATUS_FAILED


async def test_executor_agenterror_records_category(tmp_path_str):
    s = _store(tmp_path_str)
    cid = s.add(tool="boom", args={}, fire_at=_past())

    async def _raise(args, adapters):
        raise AgentError(ErrorCategory.UPSTREAM, "upstream blew up with secret xyz")

    ex = CommitmentExecutor(s, FakeRegistry({"boom": FakeEntry(_raise)}), {})
    await ex.tick_once()
    c = s.get(cid)
    assert c.status == STATUS_FAILED


async def test_executor_generic_exception_does_not_leak_message(tmp_path_str):
    s = _store(tmp_path_str)
    cid = s.add(tool="boom", args={}, fire_at=_past())
    secret = "SUPER-SECRET-IN-MESSAGE"

    async def _raise(args, adapters):
        raise RuntimeError(secret)

    ex = CommitmentExecutor(s, FakeRegistry({"boom": FakeEntry(_raise)}), {})
    await ex.tick_once()
    # the stored last_error is the exception TYPE only — message never persisted
    row = s._fetch_row(cid)
    assert row["status"] == STATUS_FAILED
    assert row["last_error"] == "RuntimeError"
    assert secret not in str(dict(row))


async def test_executor_fire_auth_wraps_invocation(tmp_path_str):
    s = _store(tmp_path_str)
    s.add(tool="send", args={}, fire_at=_past())
    events: list[str] = []

    async def _tool(args, adapters):
        events.append("invoke")

    @asynccontextmanager
    async def fire_auth(commitment):
        events.append("enter")
        try:
            yield
        finally:
            events.append("exit")

    ex = CommitmentExecutor(
        s, FakeRegistry({"send": FakeEntry(_tool)}), {}, fire_auth=fire_auth
    )
    await ex.tick_once()
    assert events == ["enter", "invoke", "exit"]


async def test_executor_fire_auth_exit_runs_on_tool_failure(tmp_path_str):
    s = _store(tmp_path_str)
    cid = s.add(tool="send", args={}, fire_at=_past())
    events: list[str] = []

    async def _tool(args, adapters):
        raise RuntimeError("nope")

    @asynccontextmanager
    async def fire_auth(commitment):
        events.append("enter")
        try:
            yield
        finally:
            events.append("exit")

    ex = CommitmentExecutor(
        s, FakeRegistry({"send": FakeEntry(_tool)}), {}, fire_auth=fire_auth
    )
    await ex.tick_once()
    assert events == ["enter", "exit"]  # cleanup ran despite the failure
    assert s.get(cid).status == STATUS_FAILED


async def test_executor_does_not_double_fire(tmp_path_str):
    s = _store(tmp_path_str)
    s.add(tool="send", args={}, fire_at=_past())
    entry = FakeEntry(_ok_tool)
    ex = CommitmentExecutor(s, FakeRegistry({"send": entry}), {})
    await ex.tick_once()
    await ex.tick_once()  # already fired → nothing due
    assert len(entry.calls) == 1


async def test_executor_completion_after_reap_does_not_raise(tmp_path_str):
    # If the row is reaped (→ failed) while the tool is still running, the late
    # mark_fired returns False; the executor logs and moves on, never raising and
    # never re-firing. We simulate by reaping mid-invoke from inside the tool.
    s = _store(tmp_path_str)
    cid = s.add(tool="send", args={}, fire_at=_past())

    async def _tool(args, adapters):
        s._conn.execute(
            "UPDATE commitments SET claimed_at=? WHERE id=?",
            ("2000-01-01T00:00:00Z", cid),
        )
        s._conn.commit()
        s.reap_stale_firing(lease_seconds=300)  # row → failed mid-fire

    ex = CommitmentExecutor(s, FakeRegistry({"send": FakeEntry(_tool)}), {})
    fired = await ex.tick_once()  # must not raise
    assert fired == 1
    assert s.get(cid).status == STATUS_FAILED  # reaper's verdict stands, no relabel


async def test_executor_safe_reap_swallows_store_error(tmp_path_str):
    # A reap that raises must not abort the tick or kill the poller.
    s = _store(tmp_path_str)

    class _BoomReap:
        def reap_stale_firing(self, lease):
            raise RuntimeError("locked")

        def claim_due(self, now=None, limit=50):
            return []

    ex = CommitmentExecutor(_BoomReap(), FakeRegistry({}), {})
    assert await ex.tick_once() == 0  # swallowed, claim still ran


# ── 3. source ──
def _source(tmp_path_str, **kwargs) -> CommitmentsSource:
    settings = SimpleNamespace(data_dir=tmp_path_str)
    return CommitmentsSource(settings, lambda _s, _f: None, **kwargs)


async def test_source_schedule_persists_and_returns_id(tmp_path_str):
    src = _source(tmp_path_str)
    cid = await src.schedule(
        tool="send", args={"x": 1}, fire_at=_future(), identity_binding="user:alice"
    )
    c = await src.get(cid, identity_binding="user:alice")
    assert isinstance(c, Commitment) and c.tool == "send"
    await src.aclose()


async def test_source_schedule_rejects_past_when_require_future(tmp_path_str):
    src = _source(tmp_path_str)
    with pytest.raises(AgentError) as ei:
        await src.schedule(tool="send", args={}, fire_at=_past())
    assert ei.value.category is ErrorCategory.VALIDATION
    await src.aclose()


async def test_source_schedule_allows_past_when_disabled(tmp_path_str):
    src = _source(tmp_path_str, require_future=False)
    cid = await src.schedule(tool="send", args={}, fire_at=_past())
    assert await src.get(cid) is not None
    await src.aclose()


async def test_source_schedule_secret_in_args_is_validation_error(tmp_path_str):
    src = _source(tmp_path_str)
    with pytest.raises(AgentError) as ei:
        await src.schedule(tool="send", args={"api_key": "x"}, fire_at=_future())
    assert ei.value.category is ErrorCategory.VALIDATION
    await src.aclose()


async def test_source_schedule_invalid_fire_at_is_validation_error(tmp_path_str):
    src = _source(tmp_path_str)
    with pytest.raises(AgentError) as ei:
        await src.schedule(tool="send", args={}, fire_at="garbage")
    assert ei.value.category is ErrorCategory.VALIDATION
    await src.aclose()


async def test_source_schedule_non_serializable_args_is_validation_error(tmp_path_str):
    src = _source(tmp_path_str)
    with pytest.raises(AgentError) as ei:
        await src.schedule(tool="send", args={"blob": b"raw"}, fire_at=_future())
    assert ei.value.category is ErrorCategory.VALIDATION
    await src.aclose()


async def test_source_schedule_blank_identity_binding_is_validation_error(tmp_path_str):
    src = _source(tmp_path_str)
    with pytest.raises(AgentError) as ei:
        await src.schedule(
            tool="send", args={}, fire_at=_future(), identity_binding="   "
        )
    assert ei.value.category is ErrorCategory.VALIDATION
    await src.aclose()


async def test_source_cancel_and_list_identity_scoped(tmp_path_str):
    src = _source(tmp_path_str)
    cid = await src.schedule(
        tool="send", args={}, fire_at=_future(), identity_binding="user:alice"
    )
    assert await src.cancel(cid, identity_binding="user:bob") is False
    assert await src.cancel(cid, identity_binding="user:alice") is True
    assert await src.list(identity_binding="user:bob") == []
    await src.aclose()


async def test_source_is_non_http_and_closes_store(tmp_path_str):
    src = _source(tmp_path_str)
    # never made an outbound request → the httpx client was never created
    assert src._client is None
    assert src.allowed_hosts == []
    await src.aclose()
    assert src.store._closed is True


# ── 4. lifespan wiring ──
def _fake_app(tmp_path_str, *, adapters, registry):
    state = SimpleNamespace(
        settings=SimpleNamespace(data_dir=tmp_path_str),
        adapters=adapters,
        registry=registry,
    )
    return SimpleNamespace(state=state)


async def test_lifespan_reuses_source_store_and_leaves_it_open(tmp_path_str):
    src = _source(tmp_path_str)
    app = _fake_app(tmp_path_str, adapters={CommitmentsSource: src}, registry=FakeRegistry({}))
    lifespan = commitments_lifespan(poll_interval=1000)  # parks in sleep; never ticks
    async with lifespan(app):
        assert app.state.commitment_store is src.store
    # executor cancelled on exit; the source-owned store is NOT closed here
    assert src.store._closed is False
    await src.aclose()
    assert src.store._closed is True


async def test_lifespan_standalone_store_is_closed_on_exit(tmp_path_str):
    app = _fake_app(tmp_path_str, adapters={}, registry=FakeRegistry({}))
    lifespan = commitments_lifespan(poll_interval=1000)
    async with lifespan(app):
        store = app.state.commitment_store
        assert store._closed is False
    assert store._closed is True  # executor owns it → closed on shutdown


async def test_lifespan_executor_actually_fires(tmp_path_str):
    # End-to-end through the lifespan: a due commitment fires on a fast tick.
    src = _source(tmp_path_str, require_future=False)
    await src.schedule(tool="send", args={"x": 9}, fire_at=_past())
    entry = FakeEntry(_ok_tool)
    app = _fake_app(
        tmp_path_str,
        adapters={CommitmentsSource: src},
        registry=FakeRegistry({"send": entry}),
    )
    lifespan = commitments_lifespan(poll_interval=1000)
    async with lifespan(app):
        # drive one tick deterministically rather than waiting for poll_interval
        store = app.state.commitment_store
        ex = CommitmentExecutor(store, app.state.registry, app.state.adapters)
        fired = await ex.tick_once()
    assert fired == 1
    assert entry.calls == [({"x": 9}, {CommitmentsSource: src})]
    await src.aclose()


# ── 5. ABC contract ──


def test_commitment_backend_abc_rejects_incomplete_subclass():
    """A subclass that omits any abstract method must fail at instantiation."""

    class _Incomplete(CommitmentBackend):
        # Implements all abstract methods except `close`, which is omitted to
        # verify that the ABC enforces the full interface contract.
        def add(self, *, tool, args, fire_at, identity_binding=None, auth_context=None):
            ...

        def claim_due(self, now=None, limit=50):
            ...

        def mark_fired(self, commitment_id):
            ...

        def mark_failed(self, commitment_id, reason: str | None):
            ...

        def cancel(self, commitment_id, *, identity_binding=None):
            ...

        def reap_stale_firing(self, lease_seconds):
            ...

        def get(self, commitment_id, *, identity_binding=None):
            ...

        def list(self, *, identity_binding=None, status=None, limit=100):
            ...

        def initialize(self):
            ...

        # `close` intentionally omitted — must trigger TypeError

    with pytest.raises(TypeError):
        _Incomplete()
