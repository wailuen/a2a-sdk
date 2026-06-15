"""contrib.action_gate — the confirmation helper over the SDK interrupt seam.

Three layers:
  1. parse_decision — the default-deny core (A2A string + AG-UI dict shapes).
  2. confirmation_required — guards + which on_* callback fires.
  3. end to end through the REAL loop/runner: a gated tool's side effect runs
     ONLY on an explicit approval, over both A2A and AG-UI resume transports.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, Field

from agent_sdk import BaseAgentSettings, ToolSet
from agent_sdk.app import Agent
from agent_sdk.agent.loop import ToolInterrupt
from agent_sdk.contrib.action_gate import (
    DEFAULT_CONFIRM_SCHEMA,
    Decision,
    Outcome,
    confirmation_required,
    declined_result,
    parse_decision,
)
from agent_sdk.testing import reply, tool_call

from .conftest import sse_frames, wait_for_state


# ── 1. parse_decision: default-deny over both transports ──
@pytest.mark.parametrize(
    "value,expected",
    [
        # A2A: free text, exact-match affirmative/negative
        ("yes", Outcome.APPROVED),
        ("  YES  ", Outcome.APPROVED),
        ("confirm.", Outcome.APPROVED),
        ("Approve!", Outcome.APPROVED),
        ("no", Outcome.REJECTED),
        ("Cancel", Outcome.REJECTED),
        ("deny", Outcome.REJECTED),
        # ambiguous free text NEVER approves (the safety property)
        ("yes but not to bob", Outcome.UNCLEAR),
        ("maybe later", Outcome.UNCLEAR),
        ("send it tomorrow instead", Outcome.UNCLEAR),
        ("", Outcome.UNCLEAR),
        # AG-UI, SDK convention: decision in the `status` field
        ({"status": "approved", "payload": {}}, Outcome.APPROVED),
        ({"status": "rejected"}, Outcome.REJECTED),
        ({"status": "denied"}, Outcome.REJECTED),
        ({"status": "cancelled"}, Outcome.REJECTED),
        ({"status": "something-else"}, Outcome.UNCLEAR),
        ({"status": None, "payload": {"note": "hi"}}, Outcome.UNCLEAR),
        ({"payload": {}}, Outcome.UNCLEAR),
        # AG-UI, canonical: protocol status + decision in `payload`
        ({"status": "resolved", "payload": {"decision": "approved"}}, Outcome.APPROVED),
        ({"status": "resolved", "payload": {"decision": "rejected"}}, Outcome.REJECTED),
        ({"status": "resolved", "payload": {}}, Outcome.UNCLEAR),
        ({"payload": {"decision": "approved"}}, Outcome.APPROVED),
        # contradiction → REJECT-WINS (default-deny)
        ({"status": "cancelled", "payload": {"decision": "approved"}}, Outcome.REJECTED),
        # AG-UI status normalization parity with A2A (case / whitespace / punct)
        ({"status": "approved\n"}, Outcome.APPROVED),
        ({"status": "  approve  "}, Outcome.APPROVED),
        ({"status": "APPROVE"}, Outcome.APPROVED),
        # non-string status must not fail open (bool is int — str() coercion)
        ({"status": True}, Outcome.UNCLEAR),
        ({"status": 1}, Outcome.UNCLEAR),
        # nested-status injection: only top-level status / payload.decision count
        ({"payload": {"status": "approved"}}, Outcome.UNCLEAR),
        ({"status": "rejected", "payload": {"status": "approved"}}, Outcome.REJECTED),
        # unicode look-alike must fail closed (no NFKC widening)
        ({"status": "ｙｅｓ"}, Outcome.UNCLEAR),
        ("ｙｅｓ", Outcome.UNCLEAR),
        # negative vocab never approves
        ("abort", Outcome.REJECTED),
        ("nope", Outcome.REJECTED),
        # junk → default-deny
        (None, Outcome.UNCLEAR),
        (42, Outcome.UNCLEAR),
        (["yes"], Outcome.UNCLEAR),
    ],
)
def test_parse_decision_default_deny(value, expected):
    assert parse_decision(value).outcome is expected


def test_declined_result_never_echoes_user_text():
    # secrets hygiene: an ambiguous reply's text must not leak into the result
    d = parse_decision("yes but not to bob")
    assert d.text == "yes but not to bob"  # available to callbacks…
    assert "bob" not in str(declined_result(d))  # …but never in the safe result


def test_decision_carries_text_only_for_a2a():
    # A2A text is preserved on the Decision (callback may inspect it)…
    assert parse_decision("yes please").text == "yes please"
    # …AG-UI structured payload is preserved, text is not synthesized
    d = parse_decision({"status": "approved", "payload": {"note": "go"}})
    assert d.text is None and d.payload == {"note": "go"}
    # a non-dict payload is dropped, never coerced
    assert parse_decision({"status": "approved", "payload": "oops"}).payload is None


def test_decision_helpers():
    assert Decision(Outcome.APPROVED).approved is True
    assert Decision(Outcome.REJECTED).rejected is True
    assert Decision(Outcome.UNCLEAR).approved is False
    assert declined_result(Decision(Outcome.UNCLEAR)) == {
        "confirmed": False,
        "outcome": "unclear",
    }


# ── 2. confirmation_required: guards + dispatch ──
def test_rejects_empty_summary():
    with pytest.raises(ValueError, match="summary"):
        confirmation_required(summary="   ", on_confirm=_noop)


def test_rejects_auth_reason():
    # 'auth' in reason would route to auth-required, a different lifecycle state
    with pytest.raises(ValueError, match="auth"):
        confirmation_required(summary="ok?", on_confirm=_noop, reason="reauth")


def test_default_schema_and_shape():
    intr = confirmation_required(summary="Proceed?", on_confirm=_noop)
    assert isinstance(intr, ToolInterrupt)
    assert intr.reason == "confirmation"  # → input-required, not auth-required
    assert "auth" not in intr.reason
    assert intr.message == "Proceed?"
    assert intr.response_schema is DEFAULT_CONFIRM_SCHEMA
    assert intr.resume_handler is not None


async def test_dispatch_routes_to_correct_handler():
    seen: dict[str, Decision] = {}

    async def cap(name):
        async def _h(decision):
            seen[name] = decision
            return {"handler": name}
        return _h

    intr = confirmation_required(
        summary="go?",
        on_confirm=await cap("confirm"),
        on_reject=await cap("reject"),
        on_unclear=await cap("unclear"),
    )
    assert (await intr.resume_handler("yes"))["handler"] == "confirm"
    assert (await intr.resume_handler("no"))["handler"] == "reject"
    assert (await intr.resume_handler("hmm wait"))["handler"] == "unclear"
    assert seen["confirm"].approved


async def test_unclear_falls_through_to_reject_then_default():
    # no on_unclear → UNCLEAR routes to on_reject
    async def rej(d):
        return {"handler": "reject"}

    intr = confirmation_required(summary="go?", on_confirm=_noop, on_reject=rej)
    assert (await intr.resume_handler("maybe"))["handler"] == "reject"

    # neither on_unclear nor on_reject → safe declined_result, no execution
    intr2 = confirmation_required(summary="go?", on_confirm=_noop)
    assert await intr2.resume_handler("maybe") == {"confirmed": False, "outcome": "unclear"}


async def _noop(decision: Decision) -> Any:  # pragma: no cover - placeholder
    return None


# ── 3. end to end: a gated tool through the real loop, both transports ──
_executed: list[str] = []  # observable side-effect sink

gtools = ToolSet()


class BookInput(BaseModel):
    title: str = Field(description="Meeting title")


@gtools.tool(tier=2)
async def book_meeting(inp: BookInput) -> dict[str, Any]:
    """Book a meeting (side-effecting — gated behind confirmation)."""

    async def _execute(decision: Decision) -> dict[str, Any]:
        _executed.append(inp.title)  # MUST NOT run unless approved
        return {"booked": True, "title": inp.title}

    raise confirmation_required(
        summary=f"Book a meeting titled {inp.title!r}?",
        on_confirm=_execute,
    )


@pytest.fixture(autouse=True)
def _reset_sink():
    _executed.clear()
    yield
    _executed.clear()


@pytest.fixture
def app(settings: BaseAgentSettings, fake_model):
    # module-local app overrides conftest's example agent → registers the gated tool
    agent = Agent(
        settings=settings,
        persona="You are a scheduling assistant.",
        toolsets=[gtools],
        model_client=fake_model,
    )
    built = agent.build_app()
    yield built
    built.state.credential_store.close()


def _send(text: str, task_id: str | None = None) -> dict:
    msg: dict[str, Any] = {
        "role": "user",
        "parts": [{"kind": "text", "text": text}],
        "messageId": "m-" + text[:6].replace(" ", ""),
    }
    if task_id:
        msg["taskId"] = task_id
    return {"message": msg}


def _run_body(text: str = "book it", **extra) -> dict:
    return {
        "threadId": "t1", "runId": "r1",
        "messages": [{"id": "m1", "role": "user", "content": text}],
        "state": {}, "tools": [], "context": [], "forwardedProps": {},
        **extra,
    }


async def test_a2a_approval_executes_side_effect(client, fake_model):
    fake_model.script(tool_call("book_meeting", {"title": "Q3 sync"}), reply("Booked."))
    r = await client.post("/v1/message:send", json=_send("book a meeting"))
    task_id = r.json()["id"]

    task = await wait_for_state(client, task_id, states=("input-required",))
    meta = task["status"]["message"]["metadata"]
    assert meta["interruptId"]
    # the proposal surface: human summary + the default confirm schema
    assert "Book a meeting" in task["status"]["message"]["parts"][0]["text"]
    # responseSchema describes the AG-UI payload form (a `decision` field)
    assert meta["responseSchema"]["properties"]["decision"]["enum"] == ["approved", "rejected"]
    assert _executed == []  # nothing booked before confirmation

    r = await client.post("/v1/message:send", json=_send("approved", task_id))
    assert r.status_code == 200, r.text
    done = await wait_for_state(client, task_id)
    assert done["status"]["state"] == "completed"
    assert _executed == ["Q3 sync"]  # side effect ran exactly once, on approval


async def test_a2a_rejection_skips_side_effect(client, fake_model):
    fake_model.script(tool_call("book_meeting", {"title": "skip me"}), reply("Okay, cancelled."))
    r = await client.post("/v1/message:send", json=_send("book a meeting"))
    task_id = r.json()["id"]
    await wait_for_state(client, task_id, states=("input-required",))

    r = await client.post("/v1/message:send", json=_send("no", task_id))
    assert r.status_code == 200
    done = await wait_for_state(client, task_id)
    assert done["status"]["state"] == "completed"
    assert _executed == []  # default-deny held


async def test_a2a_ambiguous_does_not_execute(client, fake_model):
    fake_model.script(tool_call("book_meeting", {"title": "ambiguous"}), reply("Let me re-check."))
    r = await client.post("/v1/message:send", json=_send("book a meeting"))
    task_id = r.json()["id"]
    await wait_for_state(client, task_id, states=("input-required",))

    # a reply that merely contains 'yes' must NOT execute (the safety property)
    r = await client.post("/v1/message:send", json=_send("yes but move it to friday", task_id))
    done = await wait_for_state(client, task_id)
    assert done["status"]["state"] == "completed"
    assert _executed == []


async def test_ag_ui_approval_executes(client, fake_model):
    fake_model.script(tool_call("book_meeting", {"title": "via ag-ui"}), reply("Booked."))
    frames = sse_frames((await client.post("/ag-ui/run", json=_run_body())).text)
    intr = frames[-1]["outcome"]["interrupts"][0]
    assert intr["responseSchema"]["properties"]["decision"]["enum"] == ["approved", "rejected"]
    assert _executed == []

    r = await client.post(
        "/ag-ui/run",
        json=_run_body(resume=[{"interrupt_id": intr["id"], "status": "approved", "payload": {}}]),
    )
    types = [f["type"] for f in sse_frames(r.text)]
    assert types[-1] == "RUN_FINISHED"
    assert "TOOL_CALL_RESULT" in types
    assert _executed == ["via ag-ui"]


async def test_ag_ui_rejection_skips(client, fake_model):
    fake_model.script(tool_call("book_meeting", {"title": "nope"}), reply("Cancelled."))
    frames = sse_frames((await client.post("/ag-ui/run", json=_run_body())).text)
    intr = frames[-1]["outcome"]["interrupts"][0]

    r = await client.post(
        "/ag-ui/run",
        json=_run_body(resume=[{"interrupt_id": intr["id"], "status": "rejected"}]),
    )
    assert sse_frames(r.text)[-1]["type"] == "RUN_FINISHED"
    assert _executed == []


async def test_ag_ui_canonical_payload_decision_executes(client, fake_model):
    # canonical AG-UI: protocol status="resolved", decision lives in payload
    fake_model.script(tool_call("book_meeting", {"title": "canonical"}), reply("Booked."))
    frames = sse_frames((await client.post("/ag-ui/run", json=_run_body())).text)
    intr = frames[-1]["outcome"]["interrupts"][0]

    r = await client.post(
        "/ag-ui/run",
        json=_run_body(resume=[{
            "interrupt_id": intr["id"], "status": "resolved",
            "payload": {"decision": "approved"},
        }]),
    )
    assert sse_frames(r.text)[-1]["type"] == "RUN_FINISHED"
    assert _executed == ["canonical"]


async def _wait_new_interrupt(client, task_id, prev_id, timeout=5.0):
    """Poll until the task is input-required under a DIFFERENT interrupt id than
    ``prev_id`` — distinguishes a fresh proposal from the stale first one (the
    resume POST returns before the worker re-suspends, so a plain state poll
    could observe the prior input-required)."""
    import asyncio as _a

    deadline = _a.get_event_loop().time() + timeout
    while True:
        r = await client.get(f"/v1/tasks/{task_id}")
        task = r.json()
        msg = task["status"].get("message") or {}
        intr = (msg.get("metadata") or {}).get("interruptId")
        if task["status"]["state"] == "input-required" and intr and intr != prev_id:
            return task
        if _a.get_event_loop().time() > deadline:
            raise AssertionError(f"no new interrupt; state={task['status']['state']}")
        await _a.sleep(0.02)


async def test_approval_does_not_cache_replay(client, fake_model):
    # a gated tool re-prompts on a second call — approval is never cached/replayed
    fake_model.script(
        tool_call("book_meeting", {"title": "once"}),
        tool_call("book_meeting", {"title": "once"}),  # same args, after first approval
        reply("done"),
    )
    r = await client.post("/v1/message:send", json=_send("book it"))
    task_id = r.json()["id"]
    t1 = await wait_for_state(client, task_id, states=("input-required",))
    intr1 = t1["status"]["message"]["metadata"]["interruptId"]
    await client.post("/v1/message:send", json=_send("approved", task_id))

    # the second identical call re-parks under a NEW interrupt — it does not
    # auto-fire from the earlier approval.
    await _wait_new_interrupt(client, task_id, intr1)
    assert _executed == ["once"]  # only the first, confirmed call ran
    await client.post("/v1/message:send", json=_send("no", task_id))
    done = await wait_for_state(client, task_id)
    assert done["status"]["state"] == "completed"
    assert _executed == ["once"]  # second call was declined, no replay
