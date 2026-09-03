"""RT-B-011: X-A2A-Extensions echo parity across every A2A route.

message_send, message_stream and tasks_resubscribe already call
_echo_extensions; tasks_cancel, tasks_get and tasks_list did not, so a client
that activated an extension on a session got an inconsistent echo depending
on which endpoint it hit. Locks the fix: all six routes echo the same
activated subset per §5.1 on their SUCCESS responses.

RT-B-005: the original fix above covered success responses only —
a2a_error(...) builds its own JSONResponse with no headers argument, so
every error return (task-not-found, task-not-cancelable, invalid params,
unsupported operation, ...) on every route still dropped the echo. Also
locks that follow-up fix: error responses carry the same echo.

RT-B-203 (supersedes this module's original RT-006 paragraph): the
request-header-acknowledgement echo on ``tasks/get``/``tasks/list`` described
above was itself a spec conformance bug, not a documented deliberate
exception — ``X-A2A-Extensions`` on a response means an extension was
ACTIVATED (§5.1), and neither read-only route runs any extension logic at
all (no ``_capabilities()`` call, nothing forwarded). RT-006's own test
``test_tasks_get_echoes_activated_extension`` proved the point unintentionally:
it echoed ``CRED_FWD_URI`` off a route that can never activate it. Both
routes now echo `A2UI_EXTENSION_URI` only when a Task actually being
returned carries a real A2UI part (``_echo_a2ui_if_present``,
``routes/a2a.py``) and never echo the credential-forwarding URI at all —
locked below and in ``tests/test_rtb203_a2ui_echo_activation_only.py``.

RT-002 (debug round 4): RT-B-203's "the other four routes can each genuinely
activate an extension on its own request" was false for two of them.
``tasks/cancel`` and ``tasks/resubscribe`` never call ``_capabilities()`` and
never call ``forwarding.bind`` / ``forwarding.parse_header`` — only
``message:send`` and ``message:stream`` do (the latter pair via
``_start_worker``) — yet both were returning ``X-A2A-Extensions:
<credential-forwarding URI>`` on responses where nothing had been forwarded.
The activation rule is per ROUTE, against what that route actually runs, not
per "mutating vs read-only" surface. ``tasks/cancel`` returns a Task, so it
now uses ``_echo_a2ui_if_present`` exactly like ``tasks/get``;
``tasks/resubscribe`` keeps A2UI request-gated (its replayed frames genuinely
can carry A2UI DataParts) but no longer echoes the credential URI. The two
tests below that pinned the old shape asserted the false activation itself,
and are rewritten accordingly.

RT-005: even after the above, ``message:send``/``message:stream`` still
called ``_echo_extensions`` with the FULL activatable set from the route
PROLOGUE — before the body was parsed and before the resume-vs-new-task
branch was known. Every parse/config-error return and the entire resume
branch (``_resume_or_error``, which never calls ``_capabilities()`` or
``forwarding.bind``) reused that same pre-computed header, so all of them
echoed the credential-forwarding URI — and could echo A2UI — as ACTIVATED
even though nothing was forwarded and no fresh capabilities check ever ran.
Fixed by deferring the echo until the branch that actually reached
``_capabilities()``/``_start_worker`` is known: only the fresh-task path
echoes the full set; parse/config errors echo nothing; the resume branch
echoes A2UI only via ``_echo_a2ui_if_present`` (never credential-forwarding).
``test_message_send_config_error_echoes_activated_extension`` and
``test_message_send_resume_not_found_echoes_activated_extension`` pinned the
false-activation behaviour under names asserting the opposite and are
rewritten below, alongside new coverage for the resume-success and
``message:stream`` cases.
"""

from __future__ import annotations

import uuid

import pytest

from agent_sdk.credentials.card import EXTENSION_URI as CRED_FWD_URI
from agent_sdk.models.content_types import A2UI_EXTENSION_URI
from agent_sdk.testing import reply, tool_call

from .conftest import wait_for_state


def send_body(text: str, task_id: str | None = None) -> dict:
    msg = {
        "role": "user",
        "parts": [{"kind": "text", "text": text}],
        "messageId": uuid.uuid4().hex,
    }
    if task_id:
        msg["taskId"] = task_id
    return {"message": msg}


async def test_tasks_get_never_echoes_credential_forwarding(client, fake_model):
    """RT-B-203: tasks/get runs no extension logic — never activate
    credential forwarding there, since nothing is forwarded on a read."""
    fake_model.script(reply("done"))
    r = await client.post("/v1/message:send", json=send_body("hi"))
    task_id = r.json()["id"]
    await wait_for_state(client, task_id)

    r = await client.get(
        f"/v1/tasks/{task_id}", headers={"X-A2A-Extensions": CRED_FWD_URI}
    )
    assert r.status_code == 200, r.text
    assert "x-a2a-extensions" not in r.headers


async def test_tasks_list_never_echoes_credential_forwarding(client, fake_model):
    """RT-B-203: tasks/list runs no extension logic — never activate
    credential forwarding there, since nothing is forwarded on a read."""
    fake_model.script(reply("done"))
    r = await client.post("/v1/message:send", json=send_body("hi"))
    await wait_for_state(client, r.json()["id"])

    r = await client.get("/v1/tasks", headers={"X-A2A-Extensions": CRED_FWD_URI})
    assert r.status_code == 200, r.text
    assert "x-a2a-extensions" not in r.headers


async def test_tasks_cancel_never_echoes_credential_forwarding(client, fake_model):
    """RT-002 (debug round 4): tasks/cancel activates NEITHER extension — it
    never calls _capabilities() and never calls forwarding.bind/parse_header,
    so nothing is forwarded on a cancel. Echoing the credential-forwarding URI
    back as "activated" is the identical false-activation signal RT-B-203
    removed from tasks/get; the previous version of this test asserted that
    exact shape and so proved the point unintentionally, just as RT-006's
    tasks/get test had."""
    fake_model.script(tool_call("publish_note", {"note": "x"}))
    r = await client.post("/v1/message:send", json=send_body("publish"))
    task_id = r.json()["id"]
    await wait_for_state(client, task_id, states=("input-required",))

    r = await client.post(
        f"/v1/tasks/{task_id}:cancel", headers={"X-A2A-Extensions": CRED_FWD_URI}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"]["state"] == "canceled"
    assert "x-a2a-extensions" not in r.headers


async def test_tasks_get_unknown_uri_not_echoed(client, fake_model):
    fake_model.script(reply("done"))
    r = await client.post("/v1/message:send", json=send_body("hi"))
    task_id = r.json()["id"]
    await wait_for_state(client, task_id)

    r = await client.get(
        f"/v1/tasks/{task_id}", headers={"X-A2A-Extensions": "https://unknown.example/ext"}
    )
    assert r.status_code == 200, r.text
    assert "x-a2a-extensions" not in r.headers


# ── RT-B-005: error responses ──


async def test_tasks_get_not_found_never_echoes_credential_forwarding(client):
    """RT-B-203: no task means nothing to check for an A2UI part, and
    credential forwarding is never echoed by tasks/get regardless."""
    r = await client.get(
        "/v1/tasks/does-not-exist", headers={"X-A2A-Extensions": CRED_FWD_URI}
    )
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == -32001
    assert "x-a2a-extensions" not in r.headers


async def test_tasks_cancel_not_cancelable_never_echoes_credential_forwarding(
    client, fake_model
):
    """RT-002 (debug round 4): and least of all on an error response, where
    the cancel did not even happen. Mirrors
    test_tasks_get_not_found_never_echoes_credential_forwarding."""
    fake_model.script(reply("done"))
    r = await client.post("/v1/message:send", json=send_body("hi"))
    task_id = r.json()["id"]
    await wait_for_state(client, task_id)  # completed: terminal already

    r = await client.post(
        f"/v1/tasks/{task_id}:cancel", headers={"X-A2A-Extensions": CRED_FWD_URI}
    )
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == -32002
    assert "x-a2a-extensions" not in r.headers


async def test_tasks_resubscribe_never_echoes_credential_forwarding(client, fake_model):
    """RT-002 (debug round 4): a resubscribe forwards nothing either — it
    never calls forwarding.bind/parse_header. A2UI stays request-gated there
    (the replayed frames genuinely can carry A2UI DataParts), but the
    credential-forwarding URI must never come back as activated."""
    # a COMPLETED task: _open_stream's terminal branch emits the snapshot plus
    # the closing final:true frame and returns, so the stream ends on its own
    # rather than staying open for a live worker.
    fake_model.script(reply("done"))
    r = await client.post("/v1/message:send", json=send_body("hi"))
    task_id = r.json()["id"]
    await wait_for_state(client, task_id)

    r = await client.post(
        f"/v1/tasks/{task_id}:subscribe", headers={"X-A2A-Extensions": CRED_FWD_URI}
    )
    assert r.status_code == 200, r.text
    assert "x-a2a-extensions" not in r.headers


async def test_message_send_config_error_never_echoes_credential_forwarding(client):
    """RT-005: a config error is returned before _parse_send even resolves a
    branch — neither _capabilities() nor forwarding.bind ever ran, so nothing
    was activated for this response."""
    body = send_body("hi")
    body["configuration"] = {"pushNotificationConfig": {"url": "https://example.com/hook"}}

    r = await client.post(
        "/v1/message:send", json=body, headers={"X-A2A-Extensions": CRED_FWD_URI}
    )
    assert r.status_code == 501, r.text
    assert r.json()["error"]["code"] == -32003
    assert "x-a2a-extensions" not in r.headers


async def test_message_send_resume_not_found_never_echoes_credential_forwarding(client):
    """RT-005: _resume_or_error's task-not-found return never calls
    forwarding.bind — nothing was forwarded, so nothing is echoed."""
    r = await client.post(
        "/v1/message:send",
        json=send_body("hi", task_id="does-not-exist"),
        headers={"X-A2A-Extensions": CRED_FWD_URI},
    )
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == -32001
    assert "x-a2a-extensions" not in r.headers


async def test_message_send_resume_success_never_echoes_credential_forwarding(client, fake_model):
    """RT-005: a successful resume still never calls forwarding.bind (that
    only runs in _start_worker, on the fresh-task path) — the resumed Task's
    response must never echo the credential-forwarding URI as activated."""
    fake_model.script(
        tool_call("publish_note", {"note": "hello"}),
        reply("published!"),
    )
    r = await client.post("/v1/message:send", json=send_body("publish hello"))
    task_id = r.json()["id"]
    await wait_for_state(client, task_id, states=("input-required",))

    r = await client.post(
        "/v1/message:send",
        json=send_body("approved", task_id=task_id),
        headers={"X-A2A-Extensions": CRED_FWD_URI},
    )
    assert r.status_code == 200, r.text
    assert "x-a2a-extensions" not in r.headers


async def test_message_send_resume_success_echoes_a2ui_only_when_task_carries_it(
    client, fake_model
):
    """RT-005: a resume never calls _capabilities() either, so A2UI is echoed
    on a resume response only via _echo_a2ui_if_present — the resumed Task's
    OWN artifacts genuinely carrying an A2UI part — and the credential-
    forwarding URI must still never come back, even when both are requested."""
    fake_model.script(
        tool_call("demo_kpis", {"title": "Q2"}),
        tool_call("publish_note", {"note": "hello"}),
        reply("published!"),
    )
    r = await client.post(
        "/v1/message:send",
        json=send_body("kpis then publish"),
        headers={"X-A2A-Extensions": A2UI_EXTENSION_URI},
    )
    task_id = r.json()["id"]
    await wait_for_state(client, task_id, states=("input-required",))

    r = await client.post(
        "/v1/message:send",
        json=send_body("approved", task_id=task_id),
        headers={"X-A2A-Extensions": f"{A2UI_EXTENSION_URI}, {CRED_FWD_URI}"},
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("x-a2a-extensions") == A2UI_EXTENSION_URI


# ── RT-005: message:stream mirrors message:send ────────────────────────────


async def test_message_stream_config_error_never_echoes_credential_forwarding(client):
    body = send_body("hi")
    body["configuration"] = {"pushNotificationConfig": {"url": "https://example.com/hook"}}

    r = await client.post(
        "/v1/message:stream", json=body, headers={"X-A2A-Extensions": CRED_FWD_URI}
    )
    assert r.status_code == 501, r.text
    assert r.json()["error"]["code"] == -32003
    assert "x-a2a-extensions" not in r.headers


async def test_message_stream_resume_not_found_never_echoes_credential_forwarding(client):
    r = await client.post(
        "/v1/message:stream",
        json=send_body("hi", task_id="does-not-exist"),
        headers={"X-A2A-Extensions": CRED_FWD_URI},
    )
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == -32001
    assert "x-a2a-extensions" not in r.headers


async def test_message_stream_resume_success_never_echoes_credential_forwarding(
    client, fake_model
):
    fake_model.script(
        tool_call("publish_note", {"note": "hello"}),
        reply("published!"),
    )
    r = await client.post("/v1/message:send", json=send_body("publish hello"))
    task_id = r.json()["id"]
    await wait_for_state(client, task_id, states=("input-required",))

    r = await client.post(
        "/v1/message:stream",
        json=send_body("approved", task_id=task_id),
        headers={"X-A2A-Extensions": CRED_FWD_URI},
    )
    assert r.status_code == 200, r.text
    assert "x-a2a-extensions" not in r.headers


async def test_message_stream_resume_success_echoes_a2ui_only_when_task_carries_it(
    client, fake_model
):
    fake_model.script(
        tool_call("demo_kpis", {"title": "Q2"}),
        tool_call("publish_note", {"note": "hello"}),
        reply("published!"),
    )
    r = await client.post(
        "/v1/message:send",
        json=send_body("kpis then publish"),
        headers={"X-A2A-Extensions": A2UI_EXTENSION_URI},
    )
    task_id = r.json()["id"]
    await wait_for_state(client, task_id, states=("input-required",))

    r = await client.post(
        "/v1/message:stream",
        json=send_body("approved", task_id=task_id),
        headers={"X-A2A-Extensions": f"{A2UI_EXTENSION_URI}, {CRED_FWD_URI}"},
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("x-a2a-extensions") == A2UI_EXTENSION_URI
