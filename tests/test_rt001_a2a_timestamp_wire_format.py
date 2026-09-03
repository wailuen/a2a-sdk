"""RT-001 — A2A TaskStatus.timestamp wire-format regression.

A prior wave (w032) bundled an untracked switch of the A2A
``TaskStatus.timestamp`` field from microsecond-precision, explicit-offset
ISO-8601 (``datetime.now(timezone.utc).isoformat()``, e.g.
``2026-...+00:00``) to the ``iso_utc`` helper's fixed-width
second-precision ``Z``-suffixed form (e.g. ``2026-...Z``) inside GH-110's
Origin-hardening todo — a stable-core wire behavior change (DESIGN.md §4.0)
with no CHANGELOG entry, no tracked todo, and no conformance test. Reverted;
this test pins the pre-existing wire format so any future consolidation of
``runner.py``'s ``_now()`` onto ``iso_utc`` must do so under its own tracked
todo + CHANGELOG + test update, not silently.
"""

from __future__ import annotations

import re

from agent_sdk.testing import reply, tool_call

from .conftest import wait_for_state
from .test_a2a import send_body

_MICROSECOND_OFFSET_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?\+00:00$"
)


async def test_message_send_task_status_timestamp_is_microsecond_offset_form(
    client, fake_model
):
    fake_model.script(reply("done"))
    r = await client.post("/v1/message:send", json=send_body("hi"))
    task = await wait_for_state(client, r.json()["id"])
    timestamp = task["status"]["timestamp"]
    assert _MICROSECOND_OFFSET_TIMESTAMP.match(timestamp), timestamp
    assert not timestamp.endswith("Z")


async def test_cancel_task_status_timestamp_is_microsecond_offset_form(client, fake_model):
    fake_model.script(tool_call("publish_note", {"note": "x"}))
    r = await client.post("/v1/message:send", json=send_body("publish"))
    task_id = r.json()["id"]
    await wait_for_state(client, task_id, states=("input-required",))
    r = await client.post(f"/v1/tasks/{task_id}:cancel")
    assert r.status_code == 200
    timestamp = r.json()["status"]["timestamp"]
    assert _MICROSECOND_OFFSET_TIMESTAMP.match(timestamp), timestamp
    assert not timestamp.endswith("Z")
