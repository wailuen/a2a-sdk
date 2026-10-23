"""GH-216: console resumes AG-UI interrupts per the interrupt's responseSchema."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from agent_sdk import Agent, BaseAgentSettings
from agent_sdk.agent.loop import ToolInterrupt
from agent_sdk.agent.registry import ToolSet
from agent_sdk.contrib.action_gate.gate import DEFAULT_CONFIRM_SCHEMA, Outcome, parse_decision
from agent_sdk.testing import reply, tool_call

from .conftest import sse_frames

STATIC = Path(__file__).resolve().parent.parent / "agent_sdk" / "console" / "static"
CHAT_JS = (STATIC / "chat.js").read_text()

DRIVER = r"""
import { buildResumePayload, buildPayloadFromValues, formFields } from "%s";
const one = (t) => ({ type: "object", properties: { row_number: { type: t } } });
const out = {
  int: buildResumePayload(one("integer"), "2"),
  intBad: buildResumePayload(one("integer"), "abc"),
  intFloat: buildResumePayload(one("integer"), "2.5"),
  num: buildResumePayload(one("number"), "2.5"),
  numBad: buildResumePayload(one("number"), "x"),
  bool: buildResumePayload(one("boolean"), "yes"),
  boolBad: buildResumePayload(one("boolean"), "maybe"),
  enumOk: buildResumePayload({ properties: { c: { enum: ["a", "b"] } } }, "b"),
  enumBad: buildResumePayload({ properties: { c: { enum: ["a", "b"] } } }, "z"),
  gate: buildResumePayload(%s, "approved"),
  none: buildResumePayload(undefined, "hello"),
  emptyObj: buildResumePayload({ type: "object" }, "hello"),
  multiText: buildResumePayload({ properties: { a: {type: "string"}, b: {type: "integer"} } }, "x"),
};
const multi = { properties: { a: { type: "string" }, b: { type: "integer" } }, required: ["b"] };
out.fields = formFields(multi);
out.singleFields = formFields(one("integer"));
out.form = buildPayloadFromValues(multi, { a: "hi", b: "3" });
out.formBad = buildPayloadFromValues(multi, { a: "hi", b: "q" });
out.formMissing = buildPayloadFromValues(multi, { a: "hi", b: "" });
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory: pytest.TempPathFactory) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    f = tmp_path_factory.mktemp("js") / "driver.mjs"
    f.write_text(DRIVER % ((STATIC / "interrupt.js").as_posix(), json.dumps(DEFAULT_CONFIRM_SCHEMA)))
    p = subprocess.run([node, str(f)], capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_single_property_coerced(js: dict) -> None:
    assert js["int"] == {"ok": True, "payload": {"row_number": 2}}
    assert js["num"]["payload"] == {"row_number": 2.5}
    assert js["bool"]["payload"] == {"row_number": True}
    assert js["enumOk"]["payload"] == {"c": "b"}


@pytest.mark.parametrize("key", ["intBad", "intFloat", "numBad", "boolBad", "enumBad", "multiText"])
def test_bad_input_is_error(js: dict, key: str) -> None:
    assert js[key]["ok"] is False and js[key]["error"]


def test_gate_and_no_schema_use_decision(js: dict) -> None:
    assert js["gate"]["payload"] == {"decision": "approved"}
    assert js["none"]["payload"] == {"decision": "hello"}
    assert js["emptyObj"]["payload"] == {"decision": "hello"}


def test_multi_property_form(js: dict) -> None:
    assert js["fields"] == ["a", "b"] and js["singleFields"] is None
    assert js["form"]["payload"] == {"a": "hi", "b": 3}
    assert js["formBad"]["ok"] is False
    assert js["formMissing"]["ok"] is False


def test_chat_js_keeps_schema_and_blocks_bad_input() -> None:
    assert "responseSchema: interrupts[0].responseSchema" in CHAT_JS
    assert "buildResumePayload(responseSchema, text)" in CHAT_JS
    bad = CHAT_JS.index("invalid response")
    clear = CHAT_JS.index("pendingInterrupt = null;", bad)
    assert CHAT_JS[bad:clear].count("return;") == 1


def test_action_gate_resume_is_approved() -> None:
    d = parse_decision({"status": "resolved", "payload": {"decision": "approved"}})
    assert d.outcome is Outcome.APPROVED


tools = ToolSet()
received: list[Any] = []


class NoInput(BaseModel):
    pass


async def _handler(value: Any) -> dict[str, Any]:
    received.append(value)
    return {"ok": True}


@tools.tool(tier=1)
async def pick_row(inp: NoInput) -> dict[str, Any]:
    """Ask which row."""
    raise ToolInterrupt(
        "need_row",
        "which row?",
        response_schema={"type": "object", "properties": {"row_number": {"type": "integer"}}},
        resume_handler=_handler,
    )


class Model:
    async def converse(self, *, system, messages, tools, max_tokens=4096, tool_choice="auto"):
        done = any(
            isinstance(b, dict) and "toolResult" in b
            for m in messages
            for b in (m.get("content") or [])
        )
        return reply("done") if done else tool_call("pick_row", {})


@pytest.mark.asyncio
async def test_integer_resume_delivers_int_to_tool(tmp_path) -> None:
    received.clear()
    settings = BaseAgentSettings(DEV_MODE=True, DATA_DIR=str(tmp_path / "d"), AGENT_NAME="g216")
    app = Agent(
        settings=settings,
        persona="g216",
        skills_dir=Path(__file__).parent.parent / "agent_sdk" / "example" / "skills",
        toolsets=[tools],
        model_client=Model(),
    ).build_app()
    try:
        async with app.router.lifespan_context(app):
            _, tok = app.state.auth.api_keys.mint("alice")
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers={"Authorization": f"Bearer {tok}"},
            ) as c:
                def body(**extra: Any) -> dict:
                    return {
                        "threadId": "t1", "runId": "r1",
                        "messages": [{"id": "m1", "role": "user", "content": "go"}],
                        "state": {}, "tools": [], "context": [], "forwardedProps": {}, **extra,
                    }

                frames = sse_frames((await c.post("/ag-ui/run", json=body())).text)
                intr = frames[-1]["outcome"]["interrupts"][0]
                assert intr["responseSchema"]["properties"]["row_number"]["type"] == "integer"
                r = await c.post(
                    "/ag-ui/run",
                    json=body(resume=[{
                        "interruptId": intr["id"], "status": "resolved",
                        "payload": {"row_number": 2},
                    }]),
                )
                assert sse_frames(r.text)[-1]["type"] == "RUN_FINISHED"
                assert received[0]["payload"] == {"row_number": 2}
    finally:
        app.state.credential_store.close()
