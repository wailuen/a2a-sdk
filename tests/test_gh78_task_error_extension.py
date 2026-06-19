"""GH#78 — build_agent_card() must declare the task-error SDK extension.

TaskStatus.error (WireError) is an intentional SDK extension not present in
the A2A v0.3.0 spec.  The card must advertise it so clients that understand
it can surface structured error detail, while spec-only clients can safely
ignore the entry.
"""

from __future__ import annotations

TASK_ERROR_EXT_URI = "https://agent-sdk.dev/extensions/task-error/v1"


async def test_task_error_extension_in_build_agent_card(app):
    """build_agent_card() must include the task-error extension URI."""
    card = app.state.agent_card
    ext_uris = [e["uri"] for e in card["capabilities"]["extensions"]]
    assert TASK_ERROR_EXT_URI in ext_uris, (
        f"{TASK_ERROR_EXT_URI!r} must appear in capabilities.extensions; got {ext_uris}"
    )


async def test_task_error_extension_not_required(app):
    """The task-error extension must be optional (required=False)."""
    card = app.state.agent_card
    ext = next(
        (e for e in card["capabilities"]["extensions"] if e["uri"] == TASK_ERROR_EXT_URI),
        None,
    )
    assert ext is not None, f"{TASK_ERROR_EXT_URI!r} extension missing from card"
    assert ext.get("required") is False, (
        f"task-error extension must have required=False; got {ext.get('required')!r}"
    )


async def test_task_error_extension_in_live_card(client):
    """The served card must include the task-error extension URI."""
    r = await client.get("/.well-known/agent-card.json")
    assert r.status_code == 200
    card = r.json()
    ext_uris = [e["uri"] for e in card["capabilities"]["extensions"]]
    assert TASK_ERROR_EXT_URI in ext_uris, (
        f"{TASK_ERROR_EXT_URI!r} must appear in capabilities.extensions; got {ext_uris}"
    )
