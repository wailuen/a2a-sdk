"""contrib.webhooks — inbound Microsoft Graph change-notification receiver.

Layers:
  1. models     — parse_batch: change/lifecycle split, tolerance, truncation,
                  dedup_key fallback.
  2. dispatcher — WebhookDispatcher: constant-time + fail-closed clientState,
                  replay dedup (in-mem + durable hook), named routing, lifecycle
                  routing (+ wildcard, no-dedup), handler isolation (no leak),
                  202-fast schedule()/aclose()/max_in_flight backpressure.
  3. router     — build_graph_webhook_router over a live ASGI app: validation
                  handshake (echo, URL-decode, oversize 400), always-202 intake,
                  non-JSON dropped, background dispatch drains.
  4. subs       — validators, SubscriptionStore (no secret persisted),
                  GraphSubscriptionManager create/renew/reauthorize/delete over a
                  fake Graph poster, secrets hygiene, expiration coercion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from agent_sdk.models.errors import AgentError, ErrorCategory
from agent_sdk.contrib.webhooks import (
    ChangeNotification,
    GraphSubscriptionManager,
    LifecycleNotification,
    SubscriptionBackend,
    SubscriptionStore,
    WebhookDispatcher,
    build_graph_webhook_router,
    parse_batch,
    validate_change_type,
    validate_guid,
    validate_notification_url,
    validate_resource,
)

GUID = "11111111-2222-3333-4444-555555555555"
SECRET = "ZZ-CLIENT-STATE-SECRET-ZZ"


# ── helpers ──
def change_item(*, id="n1", sub=GUID, client_state=SECRET, change_type="updated",
                resource="users/x/messages", **extra):
    item = {
        "id": id,
        "subscriptionId": sub,
        "changeType": change_type,
        "resource": resource,
        "clientState": client_state,
        "tenantId": "t1",
        "resourceData": {"id": "msg1", "@odata.etag": "etag"},
    }
    item.update(extra)
    return item


def lifecycle_item(*, sub=GUID, client_state=SECRET, event="reauthorizationRequired"):
    return {
        "subscriptionId": sub,
        "lifecycleEvent": event,
        "clientState": client_state,
        "tenantId": "t1",
    }


def batch(*items):
    return {"value": list(items)}


# ───────────────────────── 1. models / parse_batch ─────────────────────────
def test_parse_splits_change_and_lifecycle():
    p = parse_batch(batch(change_item(), lifecycle_item()))
    assert len(p.changes) == 1 and len(p.lifecycles) == 1
    assert isinstance(p.changes[0], ChangeNotification)
    assert isinstance(p.lifecycles[0], LifecycleNotification)
    assert p.changes[0].change_type == "updated"
    assert p.lifecycles[0].lifecycle_event == "reauthorizationRequired"


def test_parse_is_tolerant_of_malformed_entries():
    p = parse_batch(batch(
        change_item(),
        "not-a-dict",
        {"subscriptionId": GUID},  # change missing changeType/resource
        {"lifecycleEvent": "missed"},  # lifecycle missing subscriptionId
    ))
    assert len(p.changes) == 1
    assert p.skipped == 3


def test_parse_non_dict_body_and_missing_value_are_empty():
    assert parse_batch(None).changes == []
    assert parse_batch({"no_value": 1}).changes == []
    assert parse_batch("garbage").skipped == 0


def test_parse_truncates_oversized_batch():
    p = parse_batch(batch(*[change_item(id=f"n{i}") for i in range(10)]), max_items=4)
    assert len(p.changes) == 4
    assert p.truncated == 6


def test_dedup_key_prefers_id_then_falls_back():
    with_id = ChangeNotification.from_item(change_item(id="abc"))
    assert with_id.dedup_key == "abc"
    no_id = ChangeNotification.from_item({k: v for k, v in change_item().items() if k != "id"})
    assert no_id.dedup_key == f"{GUID}:updated:users/x/messages"


# ───────────────────────── 2. dispatcher ─────────────────────────
async def test_clientState_match_dispatches_mismatch_drops():
    seen: list[ChangeNotification] = []
    d = WebhookDispatcher(expected_client_state=SECRET)
    d.on("default", _record_handler(seen))

    ok = await d.handle_payload(batch(change_item(client_state=SECRET)))
    bad = await d.handle_payload(batch(change_item(id="n2", client_state="WRONG")))
    assert ok.changes_dispatched == 1
    assert bad.changes_dropped == 1 and bad.changes_dispatched == 0
    assert len(seen) == 1


async def test_fail_closed_when_no_secret_configured():
    d = WebhookDispatcher()  # expected=None, require_client_state=True (default)
    d.on("default", _record_handler([]))
    r = await d.handle_payload(batch(change_item()))
    assert r.changes_dispatched == 0 and r.changes_dropped == 1


async def test_explicit_opt_out_accepts_without_secret():
    got: list = []
    d = WebhookDispatcher(require_client_state=False)
    d.on("default", _record_handler(got))
    r = await d.handle_payload(batch(change_item(client_state=None)))
    assert r.changes_dispatched == 1 and len(got) == 1


async def test_per_subscription_resolver_used():
    got: list = []
    secrets = {GUID: SECRET, "other": "different"}
    d = WebhookDispatcher(expected_client_state=lambda sub: secrets.get(sub))
    d.on("default", _record_handler(got))
    ok = await d.handle_payload(batch(change_item(sub=GUID, client_state=SECRET)))
    bad = await d.handle_payload(batch(change_item(id="n2", sub="other", client_state=SECRET)))
    assert ok.changes_dispatched == 1
    assert bad.changes_dropped == 1  # wrong secret for that subscription


async def test_replay_dedup_drops_repeat():
    got: list = []
    d = WebhookDispatcher(expected_client_state=SECRET)
    d.on("default", _record_handler(got))
    first = await d.handle_payload(batch(change_item(id="dup")))
    again = await d.handle_payload(batch(change_item(id="dup")))
    assert first.changes_dispatched == 1
    assert again.changes_dropped == 1
    assert len(got) == 1


async def test_durable_seen_hook_used_and_failure_is_at_least_once():
    got: list = []
    calls = {"n": 0}

    async def flaky_seen(key: str) -> bool:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("redis down")
        return False  # never-seen

    d = WebhookDispatcher(expected_client_state=SECRET, seen=flaky_seen)
    d.on("default", _record_handler(got))
    r = await d.handle_payload(batch(change_item()))
    # The seen hook raised → treat as not-seen → still processed (at-least-once).
    assert r.changes_dispatched == 1 and len(got) == 1


async def test_named_routing_and_unknown_name_drops():
    mail: list = []
    d = WebhookDispatcher(
        expected_client_state=SECRET,
        route=lambda n: "mail" if "messages" in n.resource else "missing",
    )
    d.on("mail", _record_handler(mail))
    ok = await d.handle_payload(batch(change_item(resource="users/x/messages")))
    drop = await d.handle_payload(batch(change_item(id="n2", resource="users/x/events")))
    assert ok.changes_dispatched == 1 and len(mail) == 1
    assert drop.changes_dropped == 1  # routed to unregistered "missing"


async def test_lifecycle_routing_wildcard_and_no_dedup():
    reauth: list = []
    other: list = []
    d = WebhookDispatcher(expected_client_state=SECRET)
    d.on_lifecycle("reauthorizationRequired", _record_handler(reauth))
    d.on_lifecycle("*", _record_handler(other))

    r1 = await d.handle_payload(batch(lifecycle_item(event="reauthorizationRequired")))
    r2 = await d.handle_payload(batch(lifecycle_item(event="missed")))
    # lifecycle is NOT de-duplicated — same event twice handled twice
    r3 = await d.handle_payload(batch(lifecycle_item(event="reauthorizationRequired")))
    assert r1.lifecycles_dispatched == 1
    assert r2.lifecycles_dispatched == 1 and len(other) == 1  # missed → wildcard
    # reauthorizationRequired fired twice (r1, r3) — lifecycle is NOT de-duped
    assert r3.lifecycles_dispatched == 1 and len(reauth) == 2


async def test_lifecycle_no_handler_drops():
    d = WebhookDispatcher(expected_client_state=SECRET)
    r = await d.handle_payload(batch(lifecycle_item(event="missed")))
    assert r.lifecycles_dropped == 1


async def test_handler_exception_isolated_and_counted():
    async def boom(_n):
        raise RuntimeError("handler blew up")

    d = WebhookDispatcher(expected_client_state=SECRET)
    d.on("default", boom)
    r = await d.handle_payload(batch(change_item(id="a"), change_item(id="b")))
    # both invoked, both failed, batch did not abort
    assert r.handler_errors == 2 and r.changes_dispatched == 0


async def test_secret_never_logged():
    d = WebhookDispatcher(expected_client_state=SECRET)
    d.on("default", _record_handler([]))
    with _capture_webhook_logs() as sink:
        await d.handle_payload(batch(change_item(client_state=SECRET)))
        await d.handle_payload(batch(change_item(id="n2", client_state="WRONG")))
    text = "\n".join(sink)
    assert SECRET not in text
    assert "WRONG" not in text


async def test_schedule_is_fast_and_aclose_drains():
    got: list = []
    d = WebhookDispatcher(expected_client_state=SECRET)
    d.on("default", _record_handler(got))
    assert d.schedule(batch(change_item())) is True
    await d.aclose()  # drains the background task
    assert len(got) == 1


async def test_max_in_flight_sheds():
    d = WebhookDispatcher(expected_client_state=SECRET, max_in_flight=1)

    async def slow(_n):
        import asyncio
        await asyncio.sleep(0.05)

    d.on("default", slow)
    first = d.schedule(batch(change_item(id="a")))
    second = d.schedule(batch(change_item(id="b")))  # cap reached
    assert first is True and second is False
    await d.aclose()


# ── red-team regression: hardening fixes ──
async def test_non_ascii_clientState_fails_closed_not_raises():
    # hmac.compare_digest raises TypeError on a non-ASCII str; the attacker-
    # controlled clientState must DROP (fail closed), never raise/poison batch.
    got: list = []
    d = WebhookDispatcher(expected_client_state=SECRET)
    d.on("default", _record_handler(got))
    r = await d.handle_payload(batch(change_item(client_state="café")))
    assert r.changes_dropped == 1 and r.changes_dispatched == 0
    assert len(got) == 0


async def test_hostile_first_item_does_not_drop_the_rest():
    # A bad item placed first must not abort processing of the good items.
    got: list = []
    d = WebhookDispatcher(expected_client_state=SECRET)
    d.on("default", _record_handler(got))
    r = await d.handle_payload(batch(
        change_item(id="bad", client_state="café☃"),  # would-be poison
        change_item(id="good"),
    ))
    assert r.changes_dispatched == 1 and len(got) == 1
    assert got[0].notification_id == "good"


async def test_dedup_releases_claim_when_handler_fails():
    # First delivery: handler raises → claim released. Re-delivery (Graph
    # at-least-once) of the SAME id must get a second chance, not be dropped.
    attempts = {"n": 0}

    async def flaky(_n):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("transient downstream outage")

    d = WebhookDispatcher(expected_client_state=SECRET)
    d.on("default", flaky)
    r1 = await d.handle_payload(batch(change_item(id="evt")))
    r2 = await d.handle_payload(batch(change_item(id="evt")))  # redelivery
    assert r1.handler_errors == 1 and r1.changes_dispatched == 0
    assert r2.changes_dispatched == 1  # retried, not dropped as duplicate
    assert attempts["n"] == 2


async def test_subscription_id_with_newline_is_escaped_in_logs():
    # Attacker-controlled subscriptionId must not inject forged log lines.
    # Capture from the module logger directly (the app may set propagate=False
    # with its own JSON handler, so a root-attached caplog would see nothing).
    messages = _capture_webhook_logs()
    d = WebhookDispatcher(expected_client_state=SECRET)
    d.on("default", _record_handler([]))
    with messages as sink:
        await d.handle_payload(batch(change_item(
            sub="sub\nFORGED-LINE attacker=1", client_state="WRONG",
        )))
    text = "\n".join(sink)
    # %r escapes the newline (-> two chars '\n') → no raw forged line.
    assert "\nFORGED-LINE" not in text
    assert "FORGED-LINE" in text  # still present, but escaped/quoted


async def test_resource_data_accessors():
    n = ChangeNotification.from_item(change_item())
    assert n.resource_data_id == "msg1"
    assert n.resource_etag == "etag"
    bare = ChangeNotification.from_item(
        {**change_item(), "resourceData": {}}
    )
    assert bare.resource_data_id is None and bare.resource_etag is None


def test_recommended_action_for_lifecycle_events():
    from agent_sdk.contrib.webhooks import recommended_action
    assert "resync" in recommended_action("missed")
    assert "recreate" in recommended_action("subscriptionRemoved")
    assert "reauthorize" in recommended_action("reauthorizationRequired").lower()
    assert recommended_action("unknown") is None


# ───────────────────────── 3. router (ASGI) ─────────────────────────
def _router_app(dispatcher: WebhookDispatcher) -> FastAPI:
    app = FastAPI()
    app.include_router(build_graph_webhook_router(dispatcher, path="/webhooks/graph"))
    return app


async def test_validation_handshake_echoes_decoded_token():
    app = _router_app(WebhookDispatcher(expected_client_state=SECRET))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post("/webhooks/graph", params={"validationToken": "tok 123"})
    assert r.status_code == 200
    assert r.text == "tok 123"  # URL-decoded (space, not %20)
    assert r.headers["content-type"].startswith("text/plain")


async def test_validation_token_oversize_rejected():
    app = _router_app(WebhookDispatcher(expected_client_state=SECRET))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post("/webhooks/graph", params={"validationToken": "x" * 5000})
    assert r.status_code == 400


async def test_validation_token_not_logged():
    app = _router_app(WebhookDispatcher(expected_client_state=SECRET))
    with _capture_webhook_logs() as sink:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            await c.post("/webhooks/graph", params={"validationToken": "SECRET-TOK"})
    assert "SECRET-TOK" not in "\n".join(sink)


async def test_notification_post_returns_202_and_dispatches():
    got: list = []
    d = WebhookDispatcher(expected_client_state=SECRET)
    d.on("default", _record_handler(got))
    app = _router_app(d)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post("/webhooks/graph", json=batch(change_item()))
    assert r.status_code == 202
    await d.aclose()  # drain the scheduled background task
    assert len(got) == 1


async def test_oversized_body_capped_and_dropped():
    got: list = []
    d = WebhookDispatcher(expected_client_state=SECRET)
    d.on("default", _record_handler(got))
    app = FastAPI()
    # tiny cap so a normal batch trips it; streamed read aborts past the cap
    app.include_router(build_graph_webhook_router(d, max_body_bytes=64))
    big = batch(*[change_item(id=f"n{i}", resource="users/x/messages") for i in range(50)])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post("/webhooks/graph", json=big)
    assert r.status_code == 202  # always 202, even when dropped
    await d.aclose()
    assert len(got) == 0  # never parsed/dispatched


async def test_non_json_body_dropped_still_202():
    d = WebhookDispatcher(expected_client_state=SECRET)
    d.on("default", _record_handler([]))
    app = _router_app(d)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/webhooks/graph", content=b"not json", headers={"content-type": "application/json"}
        )
    assert r.status_code == 202
    await d.aclose()


# ───────────────────────── 4. subscriptions ─────────────────────────
def test_validate_guid():
    assert validate_guid(GUID) == GUID
    with pytest.raises(AgentError) as ei:
        validate_guid("not-a-guid")
    assert ei.value.category == ErrorCategory.VALIDATION


def test_validate_change_type():
    assert validate_change_type("created,updated") == "created,updated"
    with pytest.raises(AgentError):
        validate_change_type("deleted,exploded")


def test_validate_resource_rejects_control_chars_and_urls():
    assert validate_resource("users/x/messages") == "users/x/messages"
    with pytest.raises(AgentError):
        validate_resource("users/x\nmessages")
    with pytest.raises(AgentError):
        validate_resource("https://evil.example/")


def test_validate_notification_url_requires_https_no_creds():
    assert validate_notification_url("https://h/cb") == "https://h/cb"
    with pytest.raises(AgentError):
        validate_notification_url("http://h/cb")
    with pytest.raises(AgentError):
        validate_notification_url("https://user:pw@h/cb")


def test_subscription_store_roundtrip_no_secret_column(tmp_path):
    store = SubscriptionStore(tmp_path / "subs.db")
    store.initialize()
    store.upsert(
        id=GUID, resource="users/x/messages", change_type="updated",
        notification_url="https://h/cb", expiration="2030-01-01T00:00:00Z",
        extra={"foo": "bar"},
    )
    rec = store.get(GUID)
    assert rec["resource"] == "users/x/messages"
    assert rec["extra"] == {"foo": "bar"}
    # No column anywhere holds a clientState secret.
    assert not any("client_state" == k and "ref" not in k for k in rec)
    assert "client_state_ref" in rec
    store.close()


def test_subscription_store_due_for_renewal(tmp_path):
    store = SubscriptionStore(tmp_path / "subs.db")
    store.initialize()
    store.upsert(id=GUID, resource="r", change_type="updated",
                 notification_url="https://h/cb", expiration="2020-01-01T00:00:00Z")
    store.upsert(id="22222222-2222-3333-4444-555555555555", resource="r",
                 change_type="updated", notification_url="https://h/cb",
                 expiration="2099-01-01T00:00:00Z")
    due = store.due_for_renewal("2025-01-01T00:00:00Z")
    assert [d["id"] for d in due] == [GUID]
    store.close()


@dataclass
class _FakeResp:
    _data: dict
    @property
    def content(self) -> bytes:
        import json
        return json.dumps(self._data).encode() if self._data else b""
    def json(self) -> dict:
        return self._data


class _FakeGraph:
    def __init__(self, response: dict | None = None):
        self.calls: list[tuple[str, str, dict]] = []
        self._response = response or {}
    async def graph_request(self, method: str, path: str, **kwargs: Any):
        self.calls.append((method, path, kwargs))
        return _FakeResp(self._response)


def _manager(tmp_path, response=None):
    store = SubscriptionStore(tmp_path / "subs.db")
    store.initialize()
    graph = _FakeGraph(response)
    mgr = GraphSubscriptionManager(graph, store, client_state=SECRET)
    return mgr, graph, store


async def test_manager_create_posts_secret_persists_no_secret(tmp_path):
    mgr, graph, store = _manager(
        tmp_path, {"id": GUID, "expirationDateTime": "2030-01-01T00:00:00Z"}
    )
    with _capture_webhook_logs() as sink:
        created = await mgr.create(
            resource="users/x/messages", change_type="updated",
            notification_url="https://h/cb",
            expiration=datetime(2030, 1, 1, tzinfo=timezone.utc),
        )
    method, path, kwargs = graph.calls[0]
    assert (method, path) == ("POST", "subscriptions")
    assert kwargs["json"]["clientState"] == SECRET  # secret sent to Graph
    assert created["id"] == GUID
    # persisted record carries NO secret, and the secret never hit the logs
    rec = store.get(GUID)
    assert SECRET not in str(rec)
    assert SECRET not in "\n".join(sink)
    store.close()


async def test_manager_create_validation_error(tmp_path):
    mgr, _g, store = _manager(tmp_path)
    with pytest.raises(AgentError) as ei:
        await mgr.create(resource="r", change_type="updated",
                         notification_url="http://insecure/cb",
                         expiration=datetime(2030, 1, 1, tzinfo=timezone.utc))
    assert ei.value.category == ErrorCategory.VALIDATION
    store.close()


async def test_manager_renew_patches_and_updates_store(tmp_path):
    mgr, graph, store = _manager(
        tmp_path, {"id": GUID, "expirationDateTime": "2031-01-01T00:00:00Z"}
    )
    store.upsert(id=GUID, resource="r", change_type="updated",
                 notification_url="https://h/cb", expiration="2030-01-01T00:00:00Z")
    await mgr.renew(GUID, datetime(2031, 1, 1, tzinfo=timezone.utc))
    method, path, _ = graph.calls[0]
    assert method == "PATCH" and path == f"subscriptions/{GUID}"
    assert store.get(GUID)["expiration"] == "2031-01-01T00:00:00Z"
    store.close()


async def test_manager_reauthorize_and_delete(tmp_path):
    mgr, graph, store = _manager(tmp_path)
    store.upsert(id=GUID, resource="r", change_type="updated",
                 notification_url="https://h/cb", expiration="2030-01-01T00:00:00Z")
    await mgr.reauthorize(GUID)
    await mgr.delete(GUID)
    methods = [(m, p) for m, p, _ in graph.calls]
    assert ("POST", f"subscriptions/{GUID}/reauthorize") in methods
    assert ("DELETE", f"subscriptions/{GUID}") in methods
    assert store.get(GUID) is None  # delete removes the record
    store.close()


async def test_manager_requires_client_state(tmp_path):
    store = SubscriptionStore(tmp_path / "subs.db")
    store.initialize()
    with pytest.raises(ValueError):
        GraphSubscriptionManager(_FakeGraph(), store, client_state="")
    store.close()


async def test_expiration_in_past_rejected(tmp_path):
    mgr, _g, store = _manager(tmp_path)
    with pytest.raises(AgentError) as ei:
        await mgr.create(resource="users/x/messages", change_type="updated",
                         notification_url="https://h/cb",
                         expiration=datetime(2000, 1, 1, tzinfo=timezone.utc))
    assert ei.value.category == ErrorCategory.VALIDATION
    store.close()


def test_store_raises_after_close(tmp_path):
    store = SubscriptionStore(tmp_path / "subs.db")
    store.initialize()
    store.close()
    with pytest.raises(RuntimeError):
        store.get(GUID)


# ── small async helpers ──
async def _noop():
    return None


def _record_handler(sink: list):
    async def handler(note):
        sink.append(note)
    return handler


from contextlib import contextmanager  # noqa: E402


@contextmanager
def _capture_webhook_logs():
    """Capture formatted messages from the webhooks logger directly — robust to
    the app setting propagate=False with its own JSON handler (which would make a
    root-attached caplog silently capture nothing, turning negative assertions
    vacuous)."""
    wlog = logging.getLogger("agent_sdk.contrib.webhooks")
    sink: list[str] = []

    class _H(logging.Handler):
        def emit(self, record):
            try:
                sink.append(record.getMessage())  # applies msg % args → %r escapes
            except Exception:
                sink.append(str(record.msg))

    handler = _H(level=logging.DEBUG)
    old_level = wlog.level
    wlog.setLevel(logging.DEBUG)
    wlog.addHandler(handler)
    try:
        yield sink
    finally:
        wlog.removeHandler(handler)
        wlog.setLevel(old_level)


# ── 5. ABC contract ──


def test_subscription_backend_abc_rejects_incomplete_subclass():
    """A subclass that omits any abstract method must fail at instantiation."""

    class _Incomplete(SubscriptionBackend):
        # Implements all abstract methods except `close`, which is omitted to
        # verify that the ABC enforces the full interface contract.
        def initialize(self):
            ...

        def upsert(self, *, id, resource, change_type, notification_url,
                   expiration, lifecycle_url=None, client_state_ref="default",
                   extra=None):
            ...

        def set_expiration(self, id, expiration):
            ...

        def delete(self, id):
            ...

        def get(self, id):
            ...

        def list(self):
            ...

        def due_for_renewal(self, before_iso):
            ...

        # `close` intentionally omitted — must trigger TypeError

    with pytest.raises(TypeError):
        _Incomplete()
