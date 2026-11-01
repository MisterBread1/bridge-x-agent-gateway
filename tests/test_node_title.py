"""Regression: a required Node REPL display title must not abort valid code."""
import copy
import json
import pytest
from fastapi.testclient import TestClient
from bridge_x.config import Settings
from bridge_x.errors import BridgeError
from bridge_x.gateway import create_app
from bridge_x.providers import NativeToolDelta, Finish
from bridge_x.schemas import ChatRequest
from bridge_x.tools import parse_intent, validate_native
from bridge_x.molab_native import native_tools


TOOL = {"type": "function", "function": {"name": "mcp__node_repl__js", "parameters": {
    "type": "object", "additionalProperties": False, "required": ["code", "title"],
    "properties": {"code": {"type": "string"}, "title": {"type": "string"},
                   "timeout_ms": {"type": "integer"}}}}}


def request(tool=None, **overrides):
    return ChatRequest.model_validate({"model": "molab-glm", "tools": [tool or TOOL],
        "messages": [{"role": "user", "content": "Run a JavaScript check"}], **overrides})


@pytest.mark.parametrize("protocol", ["native", "json", "text"])
def test_missing_display_title_is_normalized_without_changing_code(protocol):
    code = 'nodeRepl.write("check\\n\\\"quoted\\\"");'
    args = {"code": code, "timeout_ms": 1000}
    if protocol == "native":
        calls = validate_native([{"function": {"name": TOOL["function"]["name"],
                                    "arguments": json.dumps(args)}}], request())
    elif protocol == "json":
        calls = parse_intent(json.dumps({"tool": TOOL["function"]["name"], "arguments": args}), request())
    else:
        calls = parse_intent('@@TOOL_CALL mcp__node_repl__js\n@@ARG code\n' + code +
                             '\n@@END_ARG\n@@VALUE timeout_ms\n1000\n@@END_VALUE\n@@END_TOOL_CALL', request())
    assert calls[0].arguments == {**args, "title": "Run JavaScript"}
    assert native_tools(request())[0]["parameters"] == TOOL["function"]["parameters"]


@pytest.mark.parametrize("change,args", [
    ("other_tool", {"code": "x"}), ("restricted_title", {"code": "x"}),
    ("ordinary", {}), ("ordinary", {"code": "x", "title": 12}),
    ("ordinary", {"code": "x", "unexpected": "private value"}),
])
def test_executable_fields_and_other_schema_constraints_remain_strict(change, args):
    tool = copy.deepcopy(TOOL)
    if change == "other_tool":
        tool["function"]["name"] = "OtherTool"
    if change == "restricted_title":
        tool["function"]["parameters"]["properties"]["title"]["enum"] = ["Only allowed title"]
    with pytest.raises(BridgeError) as caught:
        parse_intent(json.dumps({"tool": tool["function"]["name"], "arguments": args}), request(tool))
    assert caught.value.code == "TOOL_SCHEMA_MISMATCH"
    assert "private value" not in caught.value.message


def test_supplied_title_is_preserved():
    args = {"code": "x", "title": "Inspect module exports"}
    calls = parse_intent(json.dumps({"tool": TOOL["function"]["name"], "arguments": args}), request())
    assert calls[0].arguments == args


@pytest.mark.parametrize("stream", [False, True])
def test_gateway_delivers_complete_call_once_after_full_validation(stream):
    class Provider:
        async def generate(self, req, messages):
            yield NativeToolDelta(0, "original", TOOL["function"]["name"], '{"code":')
            yield NativeToolDelta(0, None, None, '"nodeRepl.write(42)"}')
            yield Finish("tool_calls")

    with TestClient(create_app(Settings(journal_path=":memory:"), Provider())) as client:
        response = client.post("/v1/chat/completions", headers={"Authorization": "Bearer molab-local"},
                               json=request(stream=stream).model_dump())
        assert response.status_code == 200
        if stream:
            events = [json.loads(line[6:]) for line in response.text.splitlines()
                      if line.startswith("data: ") and line != "data: [DONE]"]
            fragments = [call["function"].get("arguments", "") for event in events
                         for call in event["choices"][0]["delta"].get("tool_calls", [])]
            args = json.loads("".join(fragments))
            assert response.text.count('"finish_reason": "tool_calls"') <= 1
        else:
            calls = response.json()["choices"][0]["message"]["tool_calls"]
            assert len(calls) == 1
            args = json.loads(calls[0]["function"]["arguments"])
        assert args == {"code": "nodeRepl.write(42)", "title": "Run JavaScript"}
