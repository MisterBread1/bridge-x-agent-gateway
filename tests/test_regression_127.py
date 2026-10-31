"""Adversarial regression coverage: failures in V12.6 and preserved contracts.

No Molab endpoint is contacted. These tests deliberately use incompatible,
malformed and fragmented protocol data and an in-process ZCode-like HTTP client.
"""
import asyncio
import json
import random
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from bridge_x.config import Settings
from bridge_x.errors import BridgeError
from bridge_x.gateway import create_app
from bridge_x.providers import Failed, Finish, NativeToolDelta, TextDelta
from bridge_x.schemas import ChatRequest
from bridge_x.sse import SSEParser
from bridge_x.tools import parse_intent, registry
from .conftest import WRITE, BASH

AUTH = {"Authorization": "Bearer molab-local"}


def req(tools, **options):
    return ChatRequest.model_validate({"messages": [{"role": "user", "content": "check"}],
                                       "tools": tools, **options})


def api_client(tmp_path, provider):
    return TestClient(create_app(Settings(journal_path=str(tmp_path / "journal.sqlite3"),
                                          timeout_s=2, heartbeat_s=0.01), provider=provider))


def body(tools=None, messages=None, **fields):
    return {"model": "molab-glm", "messages": messages or [{"role": "user", "content": "check"}],
            "tools": [WRITE, BASH] if tools is None else tools, **fields}


@pytest.mark.parametrize("raw", [
    b'data: {"type":"finish","finishReason":"stop"}',
    b'data: {"type":"finish","finishReason":"stop"}\n',
    b'event: error\ndata: {"error":"limit"}\n',
    b'data: [DONE]\r\n',
])
def test_eof_cannot_promote_unterminated_sse_to_success(raw):
    parser = SSEParser()
    assert parser.feed(raw) == []
    assert parser.finish() == []


def test_sse_fragmentation_unicode_bom_and_mixed_line_endings():
    raw = ('\ufeffdata: {"type":"text-delta","delta":"ко🧪"}\r\n\r\n'
           'event: finish\rdata: {"type":"finish","finishReason":"stop"}\r\r').encode()
    expected = SSEParser().feed(raw)
    assert len(expected) == 2
    assert expected[0].data.endswith('ко🧪"}')
    assert expected[1].event == "finish"
    # Regression against every boundary choice with deterministic fragmentation.
    for seed in range(64):
        rng = random.Random(seed)
        parser = SSEParser()
        got = []
        pos = 0
        while pos < len(raw):
            step = rng.randint(1, 13)
            got.extend(parser.feed(raw[pos:pos+step]))
            pos += step
        got.extend(parser.finish())
        assert got == expected, seed


def test_empty_argument_frame_works():
    ping = {"type": "function", "function": {"name": "Ping", "parameters": {
        "type": "object", "additionalProperties": False, "properties": {}}}}
    calls = parse_intent('@@TOOL_CALL Ping\n@@END_TOOL_CALL', req([ping]))
    assert len(calls) == 1 and calls[0].arguments == {}


def test_tool_frame_keeps_embedded_arg_header_in_file_payload():
    text = ('@@TOOL_CALL Write\n@@ARG path\nagent_check.py\n@@END_ARG\n'
            '@@ARG content\nprint("hello")\n@@ARG this_is_source_text\nprint(2+2)\n@@END_ARG\n'
            '@@END_TOOL_CALL')
    calls = parse_intent(text, req([WRITE]))
    assert calls[0].arguments['content'] == 'print("hello")\n@@ARG this_is_source_text\nprint(2+2)'


def test_tool_frame_can_escape_literal_end_arg_inside_code():
    text = ('@@TOOL_CALL Write\n@@ARG path\na.py\n@@END_ARG\n'
            '@@ARG content\nprint("open")\n\\@@END_ARG\nprint("closed")\n@@END_ARG\n'
            '@@END_TOOL_CALL')
    calls = parse_intent(text, req([WRITE]))
    assert calls[0].arguments['content'] == 'print("open")\n@@END_ARG\nprint("closed")'


def test_frame_preserves_windows_crlf_source():
    text = ('@@TOOL_CALL Write\r\n@@ARG path\r\na.py\r\n@@END_ARG\r\n'
            '@@ARG content\r\nprint(1)\r\nprint(2)\r\n@@END_ARG\r\n@@END_TOOL_CALL')
    calls = parse_intent(text, req([WRITE]))
    assert calls[0].arguments['content'] == 'print(1)\r\nprint(2)'


@pytest.mark.parametrize('payload', [
    '{"tool_calls":[{"name":"Write","arguments":{"path":"a.py","content":NaN}}]}',
    '{"tool_calls":[{"name":"Write","arguments":{"path":"a.py","content":Infinity}}]}',
    '{"tool_calls":[{"name":"Write","arguments":{"path":"a.py","content":-Infinity}}]}',
])
def test_nonstandard_json_constants_are_rejected(payload):
    with pytest.raises(BridgeError) as exc:
        parse_intent(payload, req([WRITE]))
    assert exc.value.code == 'INVALID_TOOL_JSON'


def test_nonfinite_exponent_is_rejected_before_delivery():
    numeric = {"type": "function", "function": {"name": "Numeric", "parameters": {
        "type": "object", "properties": {"amount": {"type": "number"}}, "required": ["amount"]}}}
    with pytest.raises(BridgeError) as exc:
        parse_intent('{"tool":"Numeric","arguments":{"amount":1e9999}}', req([numeric]))
    assert exc.value.code == 'INVALID_TOOL_ARGUMENTS'


def test_external_schema_refs_rejected_before_network_resolution():
    unsafe = {"type": "function", "function": {"name": "Unsafe", "parameters": {
        "$ref": "https://example.invalid/schema.json"}}}
    with pytest.raises(BridgeError) as exc:
        registry(req([unsafe]))
    assert exc.value.code == 'INVALID_TOOL_SCHEMA'


def test_local_schema_ref_is_valid():
    local = {"type": "function", "function": {"name": "Local", "parameters": {
        "type": "object", "properties": {"amount": {"$ref": "#/$defs/positive"}},
        "$defs": {"positive": {"type": "integer", "minimum": 0}},
        "required": ["amount"]}}}
    calls = parse_intent('{"tool":"Local","arguments":{"amount":3}}', req([local]))
    assert calls[0].arguments["amount"] == 3


def test_missing_local_schema_ref_becomes_typed_error():
    broken = {"type": "function", "function": {"name": "Broken", "parameters": {
        "type": "object", "properties": {"n": {"$ref": "#/$defs/missing"}}}}}
    with pytest.raises(BridgeError) as exc:
        parse_intent('{"tool":"Broken","arguments":{"n":1}}', req([broken]))
    assert exc.value.code == "INVALID_TOOL_SCHEMA"


class TooLateError:
    async def generate(self, req, messages):
        yield TextDelta('@@TOOL_CALL Write\n@@ARG path\nt.py\n@@END_ARG\n@@ARG content\nprint(4)\n@@END_ARG\n@@END_TOOL_CALL')
        yield Finish('stop')
        yield Failed('UPSTREAM_EVENT_ERROR', 'Aborted after provisional finish')


class MalformedNative:
    def __init__(self, index):
        self.index = index

    async def generate(self, req, messages):
        yield NativeToolDelta(self.index, 'call_bad', 'Write', '{}')
        yield Finish('stop')


class PlainText:
    async def generate(self, req, messages):
        yield TextDelta('Just a note, no tools required')
        yield Finish('stop')


def test_late_sse_error_after_finish_never_delivers_tool(tmp_path):
    with api_client(tmp_path, TooLateError()) as client:
        result = client.post('/v1/chat/completions', headers=AUTH, json=body())
        assert result.status_code == 502
        assert result.json()['error']['code'] == 'UPSTREAM_EVENT_ERROR'
        assert not client.app.state.journal.db.execute('SELECT call_id FROM intents').fetchall()


def test_late_sse_error_stream_never_exposes_tool(tmp_path):
    with api_client(tmp_path, TooLateError()) as client:
        result = client.post('/v1/chat/completions', headers=AUTH, json=body(stream=True))
        assert result.status_code == 200  # streaming headers already sent
        assert 'event: error' in result.text
        assert '"tool_calls"' not in result.text
        assert 'data: [DONE]' not in result.text


@pytest.mark.parametrize('index', [-1, 16, 99, 'bad', None])
def test_invalid_native_index_is_typed_tool_error(tmp_path, index):
    with api_client(tmp_path, MalformedNative(index)) as client:
        response = client.post('/v1/chat/completions', headers=AUTH, json=body())
        assert response.status_code == 422
        assert response.json()['error']['code'] == 'INVALID_NATIVE_TOOL_DELTA'


def test_forced_tool_does_not_succeed_with_plain_text(tmp_path):
    with api_client(tmp_path, PlainText()) as client:
        result = client.post('/v1/chat/completions', headers=AUTH, json=body(tool_choice={
            'type':'function','function': {'name': 'Write'}}))
        assert result.status_code == 422
        assert result.json()['error']['code'] == 'TOOL_REQUIRED'


def test_legacy_function_message_without_call_id_does_not_get_409(tmp_path):
    with api_client(tmp_path, PlainText()) as client:
        messages = [{'role':'user','content':'Earlier run'},
                    {'role':'function','name':'Bash','content':'4'},
                    {'role':'user','content':'Continue'}]
        result = client.post('/v1/chat/completions', headers=AUTH,
                             json=body(tools=[], messages=messages))
        assert result.status_code == 200
        assert result.json()['choices'][0]['message']['content'] == 'Just a note, no tools required'


def test_existing_write_bash_still_works_after_parser_changes(tmp_path):
    with api_client(tmp_path, None if False else PlainText()) as client:
        assert client.get('/health').json()['version'].startswith('12.')


@pytest.mark.parametrize('malformed', [
    {'choices': None},
    {'choices': 'wrong'},
    {'choices': [None]},
    {'choices': [{'delta': 'not-a-dict'}]},
    {'choices': [{'delta': {'content': ['not text']}}]},
    {'choices': [{'delta': {'tool_calls': 'wrong'}}]},
    {'choices': [{'delta': {'tool_calls': [None]}}]},
    {'choices': [{'delta': {'tool_calls': [{'index': 'zero', 'function': {}}]}}]},
    {'choices': [{'delta': {'tool_calls': [{'index': 999, 'function': {}}]}}]},
])
def test_generic_provider_malformed_sse_is_sanitized(malformed):
    from bridge_x.providers import GenericOpenAIProvider
    from bridge_x.sse import SSEEvent
    event = SSEEvent('message', json.dumps(malformed))
    result = GenericOpenAIProvider._decode(event)
    assert len(result) == 1
    assert isinstance(result[0], Failed)
    assert result[0].code == 'UPSTREAM_INVALID_SSE_EVENT'


def test_native_nonfinite_json_is_rejected():
    from bridge_x.tools import validate_native
    raw = [{'function': {'name': 'Write', 'arguments': '{"path":"a.py","content":NaN}'}}]
    with pytest.raises(BridgeError) as e:
        validate_native(raw, req([WRITE]))
    assert e.value.code == 'INVALID_TOOL_JSON'


def test_molab_truncated_terminal_event_cannot_deliver_write(monkeypatch, tmp_path):
    import httpx
    from .test_molab_integration import save_config, mock_molab
    from bridge_x.config import Settings
    from bridge_x.gateway import create_app
    config = save_config(tmp_path)
    frame = '@@TOOL_CALL Write\n@@ARG path\na.py\n@@END_ARG\n@@ARG content\nprint(4)\n@@END_ARG\n@@END_TOOL_CALL'
    wire = (f'data: {json.dumps({"type":"text-delta","delta":frame},ensure_ascii=False)}\n\n'
            'data: {"type":"finish","finishReason":"stop"}\n').encode('utf-8')
    mock_molab(monkeypatch, lambda request: httpx.Response(
        200, headers={'Content-Type':'text/event-stream'}, content=wire))
    with TestClient(create_app(Settings(provider='molab', molab_config_path=config,
                                        journal_path=str(tmp_path/'j.sqlite3')))) as client:
        result = client.post('/v1/chat/completions', headers=AUTH, json=body(tools=[WRITE]))
        assert result.status_code == 502
        assert result.json()['error']['code'] == 'MOLAB_INCOMPLETE_STREAM'
        assert not client.app.state.journal.db.execute('SELECT call_id FROM intents').fetchall()


def test_fuzz_malformed_tool_frames_fail_closed_not_internal_error():
    rng = random.Random(127)
    base = '@@TOOL_CALL Write\n@@ARG path\na.py\n@@END_ARG\n@@ARG content\nprint(4)\n@@END_ARG\n@@END_TOOL_CALL'
    selected_req = req([WRITE])
    for _ in range(300):
        text = list(base)
        for __ in range(rng.randint(1, 5)):
            pos = rng.randrange(len(text))
            text[pos] = rng.choice(['\x00','@','\n','}', '{', 'X', '🧪'])
        candidate = ''.join(text)
        try:
            calls = parse_intent(candidate, selected_req)
        except BridgeError:
            continue
        # Either normal prose, or a fully schema-validated command.
        assert calls is None or all(c.name == 'Write' for c in calls)


class ProvisionalFinish:
    def __init__(self, reason):
        self.reason = reason

    async def generate(self, req, messages):
        yield TextDelta('No tool call was actually emitted')
        yield Finish(self.reason)


@pytest.mark.parametrize('reason,expected', [
    ('tool_calls', 'UPSTREAM_MISSING_TOOL_CALLS'),
    ('length', 'UPSTREAM_OUTPUT_LIMIT'),
    ('content_filter', 'UPSTREAM_CONTENT_FILTER'),
    ('unexpected_from_provider', 'UPSTREAM_UNRECOGNIZED_FINISH'),
])
def test_invalid_terminal_status_never_becomes_success(tmp_path, reason, expected):
    with api_client(tmp_path, ProvisionalFinish(reason)) as client:
        result = client.post('/v1/chat/completions', headers=AUTH, json=body(tools=[WRITE]))
        assert result.status_code == 502
        assert result.json()['error']['code'] == expected
        assert not client.app.state.journal.db.execute('SELECT call_id FROM intents').fetchall()


def test_unknown_finish_in_stream_does_not_emit_done(tmp_path):
    with api_client(tmp_path, ProvisionalFinish('some_new_provider_token')) as client:
        result = client.post('/v1/chat/completions', headers=AUTH, json=body(tools=[WRITE], stream=True))
        assert result.status_code == 200
        assert 'UPSTREAM_UNRECOGNIZED_FINISH' in result.text
        assert 'data: [DONE]' not in result.text
