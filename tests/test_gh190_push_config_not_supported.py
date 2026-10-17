"""GH-190: the four pushNotificationConfigs routes answer 501 / -32003."""

from __future__ import annotations

import pytest

from agent_sdk.auth.identity import Identity
from agent_sdk.agent.runner import new_task

_ROUTES = [
    ("post", "/v1/tasks/{id}/pushNotificationConfigs"),
    ("get", "/v1/tasks/{id}/pushNotificationConfigs"),
    ("get", "/v1/tasks/{id}/pushNotificationConfigs/cfg-1"),
    ("delete", "/v1/tasks/{id}/pushNotificationConfigs/cfg-1"),
]
_IDS = [f"{m.upper()} {p.split('/', 4)[-1]}" for m, p in _ROUTES]


def _call(client, method, path, **kw):
    return getattr(client, method)(path, **kw)


@pytest.mark.parametrize(("method", "path"), _ROUTES, ids=_IDS)
async def test_unknown_task_gets_501(client, method, path):
    r = await _call(client, method, path.format(id="nope"))
    assert r.status_code == 501
    assert r.json()["error"]["code"] == -32003


@pytest.mark.parametrize(("method", "path"), _ROUTES, ids=_IDS)
async def test_same_reply_for_existing_and_foreign_task(client, method, path):
    store = client.app.state.task_store
    owner = Identity(kind="api_key", subject="someone-else", admin=False)
    record = store.create(new_task("ctx"), owner)
    mine = await _call(client, method, path.format(id=record.task.id))
    unknown = await _call(client, method, path.format(id="nope"))
    assert mine.status_code == unknown.status_code == 501
    assert mine.json() == unknown.json()


@pytest.mark.parametrize(("method", "path"), _ROUTES, ids=_IDS)
async def test_requires_identity(client, method, path):
    r = await _call(client, method, path.format(id="t"), headers={"Authorization": ""})
    assert r.status_code == 401
    assert r.headers.get("www-authenticate")


@pytest.mark.parametrize(("method", "path"), _ROUTES, ids=_IDS)
async def test_origin_guard_applies(client, method, path):
    r = await _call(client, method, path.format(id="t"), headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


async def test_post_body_not_parsed_or_echoed(client):
    path = "/v1/tasks/t/pushNotificationConfigs"
    r = await client.post(path, content=b"{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 501
    secret = "s3cret-token-value"
    r = await client.post(path, json={"pushNotificationConfig": {"url": "https://x", "token": secret}})
    assert r.status_code == 501
    assert secret not in r.text
