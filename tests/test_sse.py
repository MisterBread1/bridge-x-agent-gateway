import json
import pytest
from bridge_x.sse import SSEParser, sse_data
from bridge_x.errors import BridgeError
from bridge_x.providers import GenericOpenAIProvider, TextDelta, NativeToolDelta, Finish, Failed, Done


def test_multiline_data_comments_crlf_and_utf8_chunks():
    p = SSEParser()
    raw = ": ping\r\nevent: message\r\ndata: один\r\ndata: два🧪\r\n\r\n".encode()
    got = []
    for b in raw:
        got.extend(p.feed(bytes([b])))
    assert len(got) == 1
    assert got[0].data == "один\nдва🧪"


def test_truncated_event_is_not_dispatched_at_eof():
    # HTML SSE standard: an event requires a blank-line terminator.
    p = SSEParser()
    assert p.feed(b'data: hello') == []
    assert p.finish() == []


def test_event_limit():
    with pytest.raises(BridgeError):
        SSEParser(max_event_chars=4).feed(b'data: 12345\n\n')


def test_unicode_error():
    with pytest.raises(BridgeError):
        SSEParser().feed(b'\xff')


def test_openai_delta():
    ev = SSEParser().feed(sse_data({"choices": [{"delta": {"content": "hi"}, "finish_reason": None}]}).encode())[0]
    out = GenericOpenAIProvider._decode(ev)
    assert isinstance(out[0], TextDelta)
    assert out[0].text == "hi"


def test_openai_tool_delta():
    ev = SSEParser().feed(sse_data({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "function": {"name": "Write", "arguments": '{"path":'}}]}, "finish_reason": None}]}).encode())[0]
    out = GenericOpenAIProvider._decode(ev)
    assert isinstance(out[0], NativeToolDelta)


def test_openai_error_finish():
    ev = SSEParser().feed(sse_data({"choices": [{"delta": {}, "finish_reason": "error"}]}).encode())[0]
    assert isinstance(GenericOpenAIProvider._decode(ev)[0], Failed)


def test_finish_done_not_success_on_own():
    ev = SSEParser().feed(b'data: [DONE]\n\n')[0]
    assert isinstance(GenericOpenAIProvider._decode(ev)[0], Done)


def test_upstream_error_sanitized():
    ev = SSEParser().feed(b'event: error\ndata: {"detail":"secret 123", "code":"context_length_exceeded"}\n\n')[0]
    out = GenericOpenAIProvider._decode(ev)
    assert isinstance(out[0], Failed)
    assert "secret" not in out[0].message
    assert out[0].code == "UPSTREAM_CONTEXT_LIMIT"
