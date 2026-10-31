"""End-to-end regressions: every supported model output format for Read offset."""
import json
import pytest
from bridge_x.errors import BridgeError
from bridge_x.schemas import ChatRequest
from bridge_x.tools import parse_intent, validate_native

READ = {"type": "function", "function": {"name": "Read", "parameters": {
    "type": "object", "properties": {
        "file_path": {"type": "string"},
        "offset": {"type": "integer", "minimum": 0},
        "limit": {"type": ["integer", "null"], "minimum": 1},
    }, "required": ["file_path"], "additionalProperties": False,
}}}
EDIT = {"type": "function", "function": {"name": "Edit", "parameters": {
    "type": "object", "properties": {"offset": {"type": "integer"}},
    "required": ["offset"],
}}}
STRING_READ = {"type": "function", "function": {"name": "Read", "parameters": {
    "type": "object", "properties": {"offset": {"type": "string"}, "file_path": {"type": "string"}},
    "required": ["offset"],
}}}


def req(tool=READ):
    return ChatRequest.model_validate({"messages": [{"role": "user", "content": "Read a file"}], "tools": [tool]})


def envelope(name, args):
    return json.dumps({"tool_calls": [{"name": name, "arguments": args}]})


@pytest.mark.parametrize("representation", ["json", "native", "frame", "legacy"])
def test_integer_offset_in_all_wire_formats(representation):
    args = {"file_path": "C:\\Work\\hello.py", "offset": "10", "limit": "20"}
    if representation == "json":
        result = parse_intent(envelope("Read", args), req())[0]
    elif representation == "native":
        result = validate_native([{"function": {"name": "Read", "arguments": json.dumps(args)}}], req())[0]
    elif representation == "frame":
        result = parse_intent("@@CALL_V2 Read\n@@FIELD file_path\na.txt\n@@FIELD offset\n10\n@@FIELD limit\n20\n@@END_CALL",req())[0]
    else:
        result = parse_intent("@@TOOL_CALL Read\n@@ARG file_path\na.txt\n@@END_ARG\n@@ARG offset\n10\n@@END_ARG\n@@ARG limit\n20\n@@END_ARG\n@@END_TOOL_CALL",req())[0]
    assert result.arguments["offset"] == 10 and type(result.arguments["offset"]) is int
    assert result.arguments["limit"] == 20 and type(result.arguments["limit"]) is int


@pytest.mark.parametrize("bad", ["10px", "00", "+1", "1.5", "one", "NaN", "1e3", "", "1,000", "９"])
def test_noncanonical_pagination_arguments_never_guessed(bad):
    with pytest.raises(BridgeError) as e:
        parse_intent(envelope("Read", {"file_path": "test.py", "offset": bad}), req())
    assert e.value.code == "TOOL_SCHEMA_MISMATCH"


def test_read_numeric_minimum_must_still_validate():
    with pytest.raises(BridgeError) as e:
        parse_intent(envelope("Read", {"file_path": "test.py", "offset": "-1"}), req())
    assert e.value.code == "TOOL_SCHEMA_MISMATCH"


def test_integer_conversion_limited_to_read_pagination_for_json_calls():
    with pytest.raises(BridgeError) as e:
        parse_intent(envelope("Edit", {"offset": "10"}), req(EDIT))
    assert e.value.code == "TOOL_SCHEMA_MISMATCH"


def test_read_string_schema_preserved_exactly():
    result = parse_intent(envelope("Read", {"file_path": "a", "offset": "0010"}), req(STRING_READ))[0]
    assert result.arguments["offset"] == "0010"


def test_no_change_to_already_typed_native_calls():
    result = validate_native([{"function":{"name":"Read","arguments":json.dumps({"file_path":"a","offset":10,"limit":None})}}],req())[0]
    assert result.arguments == {"file_path":"a","offset":10,"limit":None}


def test_original_values_are_not_mutated():
    args = {"file_path": "test.py", "offset": "0"}
    result = parse_intent(envelope("Read", args), req())[0]
    assert args["offset"] == "0" and result.arguments["offset"] == 0

from fastapi.testclient import TestClient
from bridge_x.config import Settings
from bridge_x.gateway import create_app
from bridge_x.providers import TextDelta, NativeToolDelta, Finish

class JsonReadProvider:
    async def generate(self, req, messages):
        body = envelope("Read", {"file_path": "index.html", "offset": "20"})
        for i in range(0, len(body), 8):
            yield TextDelta(body[i:i+8])
        yield Finish("stop")

class NativeReadProvider:
    async def generate(self, req, messages):
        yield NativeToolDelta(0, "call_test", "Read", json.dumps({"file_path": "index.html", "offset": "20"}))
        yield Finish("tool_calls")

@pytest.mark.parametrize("provider", [JsonReadProvider(), NativeReadProvider()])
@pytest.mark.parametrize("stream", [False, True])
def test_real_http_json_and_native_read_returns_integer(tmp_path, provider, stream):
    with TestClient(create_app(Settings(journal_path=str(tmp_path/'state.sqlite3')), provider=provider)) as client:
        response = client.post('/v1/chat/completions',headers={'Authorization':'Bearer molab-local'},json={
            'model':'molab-glm','messages':[{'role':'user','content':'Read from offset'}],
            'tools':[READ], 'stream':stream,
        })
    assert response.status_code == 200, response.text[:150]
    if stream:
        assert 'tool_calls' in response.text and 'data: [DONE]' in response.text
        assert '\\"offset\\":20' in response.text
    else:
        args = json.loads(response.json()['choices'][0]['message']['tool_calls'][0]['function']['arguments'])
        assert args['offset'] == 20 and type(args['offset']) is int
