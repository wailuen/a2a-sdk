"""OpenAIModelClient Converse↔OpenAI translation (no network).

The loop speaks Bedrock Converse shapes; this backend must translate them to
OpenAI chat-completions and back without the loop noticing. These tests pin the
translation — the only place a port bug could silently corrupt tool-calling.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from agent_sdk.agent.openai_client import OpenAIModelClient


def test_system_and_user_query():
    msgs = OpenAIModelClient._to_openai_messages(
        "You are a climate analyst.",
        [{"role": "user", "content": [{"text": "risk for London?"}]}],
    )
    assert msgs[0] == {"role": "system", "content": "You are a climate analyst."}
    assert msgs[1] == {"role": "user", "content": "risk for London?"}


def test_assistant_tool_use_translates_to_tool_calls():
    converse = [
        {"role": "user", "content": [{"text": "scores for London"}]},
        {
            "role": "assistant",
            "content": [
                {"text": "Looking that up."},
                {"toolUse": {"toolUseId": "call_1", "name": "get_scores", "input": {"address": "London"}}},
            ],
        },
    ]
    msgs = OpenAIModelClient._to_openai_messages("", converse)
    assistant = msgs[-1]
    assert assistant["role"] == "assistant"
    assert assistant["content"] == "Looking that up."
    tc = assistant["tool_calls"][0]
    assert tc["id"] == "call_1"
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "get_scores"
    assert json.loads(tc["function"]["arguments"]) == {"address": "London"}


def test_assistant_pure_tool_use_has_null_content():
    msgs = OpenAIModelClient._to_openai_messages(
        "",
        [{"role": "assistant", "content": [
            {"toolUse": {"toolUseId": "c1", "name": "t", "input": {}}}
        ]}],
    )
    assert msgs[0]["content"] is None
    assert msgs[0]["tool_calls"][0]["id"] == "c1"


def test_tool_result_becomes_tool_message():
    converse = [
        {
            "role": "user",
            "content": [
                {"toolResult": {
                    "toolUseId": "call_1",
                    "content": [{"json": {"score": 7}}],
                    "status": "success",
                }}
            ],
        }
    ]
    msgs = OpenAIModelClient._to_openai_messages("", converse)
    assert msgs[0]["role"] == "tool"
    assert msgs[0]["tool_call_id"] == "call_1"
    assert json.loads(msgs[0]["content"]) == {"score": 7}


def test_tool_result_text_block():
    converse = [
        {"role": "user", "content": [
            {"toolResult": {"toolUseId": "c", "content": [{"text": "no data"}], "status": "error"}}
        ]}
    ]
    msgs = OpenAIModelClient._to_openai_messages("", converse)
    assert msgs[0] == {"role": "tool", "tool_call_id": "c", "content": "no data"}


def test_tools_translation():
    tools = [{"name": "get_scores", "description": "Climate scores",
              "input_schema": {"type": "object", "properties": {"address": {"type": "string"}}}}]
    out = OpenAIModelClient._to_openai_tools(tools)
    assert out[0]["type"] == "function"
    assert out[0]["function"]["name"] == "get_scores"
    assert out[0]["function"]["parameters"]["properties"]["address"]["type"] == "string"


# ── OpenAI response → ModelResponse ──

def _resp(content=None, tool_calls=None, finish_reason="stop", prompt=10, completion=5):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    usage = SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion)
    return SimpleNamespace(choices=[choice], usage=usage)


def test_parse_text_response():
    out = OpenAIModelClient._parse(_resp(content="Risk is moderate.", finish_reason="stop"))
    assert out.text_segments == ["Risk is moderate."]
    assert out.tool_calls == []
    assert out.stop_reason == "end_turn"
    assert (out.input_tokens, out.output_tokens) == (10, 5)


def test_parse_tool_call_response():
    tc = SimpleNamespace(
        id="call_9",
        function=SimpleNamespace(name="get_scores", arguments='{"address": "Paris"}'),
    )
    out = OpenAIModelClient._parse(_resp(tool_calls=[tc], finish_reason="tool_calls"))
    assert out.stop_reason == "tool_use"
    assert out.tool_calls[0].tool_call_id == "call_9"
    assert out.tool_calls[0].name == "get_scores"
    assert out.tool_calls[0].arguments == {"address": "Paris"}


def test_parse_malformed_arguments_fall_back_to_empty():
    tc = SimpleNamespace(id="c", function=SimpleNamespace(name="t", arguments="not json"))
    out = OpenAIModelClient._parse(_resp(tool_calls=[tc], finish_reason="tool_calls"))
    assert out.tool_calls[0].arguments == {}


def test_parse_length_finish_reason():
    out = OpenAIModelClient._parse(_resp(content="...", finish_reason="length"))
    assert out.stop_reason == "max_tokens"


def test_satisfies_model_client_protocol():
    from agent_sdk.agent.model_client import ModelClient

    client = OpenAIModelClient(model="gpt-5", api_key="x")
    assert isinstance(client, ModelClient)
