"""Regression: the text frame's @@FIELD must not make integer Read offset fail.

The upstream model may choose @@FIELD offset\\n10, which creates a string;
normalization is allowed only when the ZCode-declared schema says integer.
"""
import json

import pytest
from fastapi.testclient import TestClient

from bridge_x.config import Settings
from bridge_x.errors import BridgeError
from bridge_x.gateway import create_app
from bridge_x.molab_provider import _tool_prompt
from bridge_x.providers import TextDelta, Finish
from bridge_x.schemas import ChatRequest
from bridge_x.tools import parse_intent, validate_native

READ = {"type":"function", "function": {"name":"Read", "parameters": {
    "type":"object", "properties": {
        "file_path":{"type":"string"},
        "offset":{"type":"integer", "minimum":0},
        "limit":{"type":["integer","null"], "minimum":1}
    }, "required":["file_path"], "additionalProperties":False
}}}

STRING_OFFSET = {"type":"function", "function": {"name":"Lookup", "parameters": {
    "type":"object", "properties":{"offset":{"type":"string"}}, "required":["offset"]
}}}

NESTED = {"type":"function", "function": {"name":"LookupNested", "parameters": {
    "type":"object", "properties": {"options":{"type":"object", "properties":{
        "offset":{"type":"integer"}}, "required":["offset"]}}, "required":["options"]
}}}


def req(tool=READ):
    return ChatRequest.model_validate({"messages":[{"role":"user","content":"Read file from offset"}],
                                       "tools":[tool]})


def frame(value, path="C:\\Work\\7\\index.html", kind="FIELD"):
    return (f"@@CALL_V2 Read\n@@FIELD file_path\n{path}\n"
            f"@@{kind} offset\n{value}\n@@END_CALL")


def test_v2_read_offset_integer_from_field():
    result = parse_intent(frame("10"), req())[0]
    assert result.arguments == {"file_path":"C:\\Work\\7\\index.html", "offset":10}
    assert isinstance(result.arguments["offset"], int)


def test_v2_read_offset_limit_both_integers():
    raw = frame('0').replace('@@END_CALL', '@@FIELD limit\n500\n@@END_CALL')
    result = parse_intent(raw, req())[0]
    assert result.arguments["offset"] == 0
    assert result.arguments["limit"] == 500


def test_read_json_numeric_still_supported():
    assert parse_intent(frame("10", kind="JSON"), req())[0].arguments["offset"] == 10


def test_legacy_text_frame_typed_integer_normalization():
    raw = ('@@TOOL_CALL Read\n@@ARG file_path\na.txt\n@@END_ARG\n'
           '@@ARG offset\n10\n@@END_ARG\n@@END_TOOL_CALL')
    assert parse_intent(raw, req())[0].arguments["offset"] == 10


@pytest.mark.parametrize('bad', ['10px','1.5','1e2','+5','1,000','NaN','Infinity','one','',
                                 '00','０','-1','9'*40])
def test_ambiguous_invalid_or_negative_offset_is_not_repaired(bad):
    with pytest.raises(BridgeError) as e:
        parse_intent(frame(bad), req())
    assert e.value.code in ('TOOL_SCHEMA_MISMATCH', 'INVALID_TOOL_ARGUMENTS')


def test_numeric_path_remains_string_when_schema_says_string():
    args = parse_intent(frame('12', path='0012'), req())[0].arguments
    assert args['file_path'] == '0012' and args['offset'] == 12


def test_string_typed_offset_never_converted():
    raw = '@@CALL_V2 Lookup\n@@FIELD offset\n0012\n@@END_CALL'
    assert parse_intent(raw, req(STRING_OFFSET))[0].arguments['offset'] == '0012'


def test_nested_fields_are_not_coerced_from_invalid_json():
    raw = '@@CALL_V2 LookupNested\n@@JSON options\n{"offset":"10"}\n@@END_CALL'
    with pytest.raises(BridgeError) as e:
        parse_intent(raw, req(NESTED))
    assert e.value.code == 'TOOL_SCHEMA_MISMATCH'


def test_native_and_json_envelope_read_pagination_compatibility():
    # V12.10.2: when Molab chooses a JSON envelope or native output, the
    # same schema-guided conversion must apply to Read.offset/Read.limit.
    native = [{"function":{"name":"Read","arguments":json.dumps({"file_path":"a", "offset":"10", "limit":"50"})}}]
    assert validate_native(native, req())[0].arguments == {'file_path':'a', 'offset':10, 'limit':50}
    envelope = json.dumps({'tool_calls':[{'name':'Read', 'arguments':{'file_path':'a','offset':'10'}}]})
    assert parse_intent(envelope, req())[0].arguments == {'file_path':'a', 'offset':10}


def test_prompt_explicitly_demonstrates_integer_json_literal():
    prompt=_tool_prompt(req(),[{"role":"user","content":"Read file from offset"}])
    assert 'IMPORTANT: @@FIELD sends a string' in prompt
    assert '@@JSON offset followed by 0' in prompt
    assert 'Read:' in prompt
    assert '"offset":{"type":"integer"' in prompt


class Provider:
    async def generate(self, request, messages):
        raw = frame('10', path='index.html')
        for i in range(0,len(raw),13):
            yield TextDelta(raw[i:i+13])
        yield Finish('stop')


@pytest.mark.parametrize('stream',[False, True])
def test_real_http_gateway_read_from_text_frame(tmp_path,stream):
    with TestClient(create_app(Settings(journal_path=str(tmp_path/'j.sqlite3')), provider=Provider())) as client:
        response=client.post('/v1/chat/completions',headers={'Authorization':'Bearer molab-local'},json={
            'model':'molab-glm','messages':[{'role':'user','content':'Read file from offset 10'}],
            'tools':[READ], 'stream':stream,
        })
    assert response.status_code == 200
    if stream:
        assert 'tool_calls' in response.text
        assert '\\\"offset\\\":10' in response.text or '\\\"offset\\\":10' in response.text
        assert 'data: [DONE]' in response.text
    else:
        call = response.json()['choices'][0]['message']['tool_calls'][0]
        assert json.loads(call['function']['arguments']) == {'file_path':'index.html', 'offset':10}
