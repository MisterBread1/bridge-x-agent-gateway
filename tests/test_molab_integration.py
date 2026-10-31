"""Tests for real Molab wire FORMAT using a simulated upstream.

No network or real auth is used; these tests do not prove live access.
"""
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from bridge_x.config import Settings
from bridge_x.errors import BridgeError, UpstreamError
from bridge_x.molab_provider import (read_molab_config, build_molab_payload,
                                     decode_molab_event, MolabProvider)
from bridge_x.providers import TextDelta, Failed, Finish, make_provider
from bridge_x.gateway import create_app
from bridge_x.schemas import ChatRequest
from .conftest import WRITE, BASH


def save_config(tmp_path, **patch):
    raw = {"notebook_url": "https://molab.marimo.io/notebooks/test",
           "chat_url": "https://sb-test.sb.molab.run/api/ai/chat",
           "marimo_session_id": "s_correct", "marimo_server_token": "", "http_headers": {}}
    raw.update(patch)
    path = tmp_path / ".molab_local.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return str(path)


def response_stream(*events):
    return ("".join("data: " + json.dumps(event, ensure_ascii=False) + "\n\n" for event in events)).encode()


def request_factory(tools=None, messages=None, stream=False):
    return ChatRequest.model_validate({"model": "molab-glm", "stream": stream,
                                       "messages": messages or [{"role": "user", "content": "Create agent_check.py"}],
                                       "tools": tools or []})


def mock_molab(monkeypatch, callback):
    real = httpx.AsyncClient
    transport = httpx.MockTransport(callback)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real(transport=transport, **{k:v for k,v in kwargs.items() if k != "transport"}))


def new_provider(tmp_path):
    cfg = save_config(tmp_path)
    settings = Settings(provider="molab", molab_config_path=cfg, journal_path=":memory:", heartbeat_s=0.02)
    return MolabProvider(settings), settings


def test_config_reads_operator_file(tmp_path):
    cfg = read_molab_config(save_config(tmp_path))
    assert cfg.session_id == "s_correct"
    assert cfg.server_token == ""


@pytest.mark.parametrize("bad", [
    {"chat_url": "http://sb-test.sb.molab.run/api/ai/chat"},
    {"chat_url": "https://example.com/api/ai/chat"},
    {"chat_url": "https://sb-test.sb.molab.run/other"},
    {"chat_url": "https://sb-test.sb.molab.run:abc/api/ai/chat"},
    {"marimo_session_id": ""},
    {"marimo_session_id": "bad\r\nheader:x"},
    {"http_headers": {"host": "example.com"}},
    {"http_headers": {"X-Foo": "line\nmore"}},
])
def test_reject_malformed_or_untrusted_configuration(tmp_path, bad):
    with pytest.raises(BridgeError) as ex:
        read_molab_config(save_config(tmp_path, **bad))
    assert ex.value.code == "MOLAB_CONFIG_INVALID"
    assert "example.com" not in ex.value.message


def test_config_missing_is_explicit(tmp_path):
    with pytest.raises(BridgeError) as ex:
        read_molab_config(str(tmp_path / "missing.json"))
    assert ex.value.code == "MOLAB_CONFIG_MISSING"


def test_ui_payload_matches_browser_shape_and_tool_receipts(tmp_path):
    cfg = read_molab_config(save_config(tmp_path))
    req = request_factory([WRITE, BASH], [
        {"role": "system", "content": "Code safely"},
        {"role": "user", "content": "Create agent_check.py and run it"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_one", "type": "function", "function": {"name": "Write", "arguments": '{"path":"agent_check.py","content":"print(2 + 2)"}'}}]},
        {"role": "tool", "tool_call_id": "call_one", "content": '{"success":true}'}
    ])
    payload = build_molab_payload(req, [m.model_dump(exclude_none=True) for m in req.messages], cfg)
    assert set(payload) == {"api", "body", "headers", "id", "includeOtherCode", "messages", "uiMessages", "tools", "trigger", "options"}
    assert payload["uiMessages"] == payload["messages"]
    assert payload["tools"] == []
    assert payload["trigger"] == "submit-message"
    assert payload["headers"]["marimo-session-id"] == "s_correct"
    assert payload["options"] == {"webSearch": False}
    combined = "\n".join(m["parts"][0]["text"] for m in payload["messages"])
    assert "<tool_result id=\"call_one\">" in combined
    assert "Conversation history only" in combined
    assert "<previous_tool_calls>" not in combined
    assert "Write" in combined and "Bash" in combined
    assert "Code safely" in combined


def test_tools_not_executed_by_provider(tmp_path):
    cfg = read_molab_config(save_config(tmp_path))
    req = request_factory([WRITE, BASH])
    packet = build_molab_payload(req, [m.model_dump(exclude_none=True) for m in req.messages], cfg)
    assert all(m["role"] in ("assistant", "user") for m in packet["messages"])


def test_decode_text_and_success_finish():
    assert decode_molab_event('{"type":"text-delta","delta":"Привет"}') == [TextDelta("Привет")]
    assert decode_molab_event('{"type":"finish","finishReason":"stop"}') == [("finish", "stop")]


def test_decode_nested_finish_error_without_content_leak():
    out = decode_molab_event(json.dumps({"type": "finish", "finishReason": "error", "error": {"cause": {"code": "context_length_exceeded", "message": "private secret"}}}))
    assert isinstance(out[0], Failed)
    assert out[0].code == "UPSTREAM_CONTEXT_LIMIT"
    assert "private secret" not in out[0].message


@pytest.mark.parametrize("event,code", [
    ({"type": "finish", "finishReason": "length"}, "UPSTREAM_OUTPUT_LIMIT"),
    ({"type": "error", "error": {"statusCode": 429}}, "UPSTREAM_RATE_LIMIT"),
    ({"type": "finish", "finishReason": "error"}, "UPSTREAM_FINISH_ERROR"),
    ({"type": "abort", "detail": "private"}, "UPSTREAM_ABORTED"),
])
def test_decode_failure_types(event, code):
    got = decode_molab_event(json.dumps(event))
    assert isinstance(got[0], Failed)
    assert got[0].code == code


@pytest.mark.asyncio
async def test_real_molab_adapter_streams_text_and_validates_headers(monkeypatch, tmp_path):
    calls = []
    def handler(req):
        calls.append(req)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=response_stream(
            {"type": "text-delta", "delta": "Хорошо"}, {"type": "finish", "finishReason": "stop"}))
    mock_molab(monkeypatch, handler)
    provider, _ = new_provider(tmp_path)
    request = request_factory()
    result = [x async for x in provider.generate(request, [m.model_dump(exclude_none=True) for m in request.messages])]
    assert result == [TextDelta("Хорошо"), Finish("stop")]
    assert len(calls) == 1
    assert calls[0].headers["marimo-session-id"] == "s_correct"
    assert calls[0].url.path == "/api/ai/chat"
    posted = json.loads(calls[0].content)
    assert posted["uiMessages"][0]["parts"][0]["text"] == "Create agent_check.py"


@pytest.mark.asyncio
async def test_late_finish_error_never_returns_success(monkeypatch, tmp_path):
    mock_molab(monkeypatch, lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=response_stream(
        {"type": "text-delta", "delta": "PARTIAL"},
        {"type": "finish", "finishReason": "stop"},
        {"type": "finish", "finishReason": "error", "error": {"code": "internal"}})))
    provider, _ = new_provider(tmp_path)
    req = request_factory()
    out = [e async for e in provider.generate(req, [m.model_dump(exclude_none=True) for m in req.messages])]
    assert isinstance(out[-1], Failed)
    assert not any(isinstance(item, Finish) for item in out)


@pytest.mark.asyncio
async def test_stream_must_have_terminal(monkeypatch, tmp_path):
    mock_molab(monkeypatch, lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=response_stream(
        {"type": "text-delta", "delta": "not complete"})))
    provider, _ = new_provider(tmp_path)
    req = request_factory()
    out = [e async for e in provider.generate(req, [m.model_dump(exclude_none=True) for m in req.messages])]
    assert out[-1] == Failed("MOLAB_INCOMPLETE_STREAM", "Molab stream ended without terminal finish or DONE")


@pytest.mark.asyncio
async def test_config_runtime_gone_has_410(monkeypatch, tmp_path):
    mock_molab(monkeypatch, lambda request: httpx.Response(410, content=b"private token"))
    provider, _ = new_provider(tmp_path)
    req = request_factory()
    with pytest.raises(UpstreamError) as ex:
        [e async for e in provider.generate(req, [m.model_dump(exclude_none=True) for m in req.messages])]
    assert ex.value.code == "MOLAB_RUNTIME_GONE" and ex.value.status == 410
    assert "token" not in ex.value.message


@pytest.mark.asyncio
async def test_molab_http_500_is_explicit(monkeypatch, tmp_path):
    mock_molab(monkeypatch, lambda request: httpx.Response(500, content=b'{"detail":"secret user content"}'))
    provider, _ = new_provider(tmp_path)
    req = request_factory()
    with pytest.raises(UpstreamError) as ex:
        [e async for e in provider.generate(req, [m.model_dump(exclude_none=True) for m in req.messages])]
    assert ex.value.code == "MOLAB_HTTP_ERROR"
    assert "secret" not in ex.value.message


def test_provider_selection_and_readiness(tmp_path):
    cfg = save_config(tmp_path)
    settings = Settings(provider="molab", molab_config_path=cfg, journal_path=":memory:")
    assert isinstance(make_provider(settings), MolabProvider)
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").json()["provider"] == "molab"
        assert client.get("/ready").json()["molab_adapter_available"] is True
        assert client.get("/v1/models", headers={"Authorization": "Bearer molab-local"}).json()["data"][0]["id"] == "molab-glm"


def test_real_gateway_with_molab_wire_and_tool_call(monkeypatch, tmp_path):
    observed = []
    proposed = json.dumps({"tool_calls": [{"name": "Write", "arguments": {"path": "agent_check.py", "content": "print(2 + 2)\n"}}]})
    def handler(request):
        observed.append(json.loads(request.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=response_stream({"type": "text-delta", "delta": proposed}, {"type": "finish", "finishReason": "stop"}))
    mock_molab(monkeypatch, handler)
    cfg = save_config(tmp_path)
    settings = Settings(provider="molab", molab_config_path=cfg, journal_path=":memory:")
    with TestClient(create_app(settings)) as client:
        response = client.post("/v1/chat/completions", json={"model": "molab-glm", "messages": [{"role": "user", "content": "Create agent_check.py"}], "tools": [WRITE, BASH]}, headers={"Authorization": "Bearer molab-local"})
        assert response.status_code == 200, response.text
        msg = response.json()["choices"][0]["message"]
        assert msg["tool_calls"][0]["function"]["name"] == "Write"
        assert json.loads(msg["tool_calls"][0]["function"]["arguments"])["path"] == "agent_check.py"
        assert len(observed) == 1
        assert observed[0]["messages"][0]["role"] == "user"


def test_gateway_error_after_partial_tool_intent_has_no_fake_done(monkeypatch, tmp_path):
    text = '{"tool_calls":[{"name":"Write","arguments":{"path":"agent_check.py","content":"bad"}}]}'
    mock_molab(monkeypatch, lambda request: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=response_stream(
        {"type": "text-delta", "delta": text}, {"type": "finish", "finishReason": "error"})))
    cfg = save_config(tmp_path)
    settings = Settings(provider="molab", molab_config_path=cfg, journal_path=":memory:", heartbeat_s=0.01)
    with TestClient(create_app(settings)) as client:
        response = client.post("/v1/chat/completions", json={"model": "molab-glm", "stream": True,
                  "messages": [{"role": "user", "content": "Create file"}], "tools": [WRITE, BASH]}, headers={"Authorization": "Bearer molab-local"})
        assert response.status_code == 200
        assert "UPSTREAM_FINISH_ERROR" in response.text
        assert '"name":"Write"' not in response.text
        assert "data: [DONE]" not in response.text


def test_molab_mode_does_not_fall_back_to_fake(monkeypatch, tmp_path):
    mock_molab(monkeypatch, lambda req: httpx.Response(503))
    cfg = save_config(tmp_path)
    settings = Settings(provider="molab", molab_config_path=cfg, journal_path=":memory:")
    with TestClient(create_app(settings)) as client:
        response = client.post("/v1/chat/completions", json={"model": "molab-glm", "messages": [{"role": "user", "content": "hi"}]}, headers={"Authorization": "Bearer molab-local"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "MOLAB_HTTP_ERROR"
        assert "fake" not in response.text.lower()


def test_legacy_stream_parser():
    from bridge_x.molab_provider import MolabSSEParser
    parser = MolabSSEParser()
    events = parser.feed(b'0:"Hello legacy"\n') + parser.feed(b'd:{"finishReason":"stop"}\n')
    assert [x.event for x in events] == ["legacy-text", "legacy-finish"]
    assert decode_molab_event(events[0].data, events[0].event) == [TextDelta("Hello legacy")]
    assert decode_molab_event(events[1].data, events[1].event) == [("finish", "stop")]


@pytest.mark.parametrize("frame,code", [
    ("@@TOOL_CALL Write\n@@ARG path\nfile.py\n@@END_ARG\n@@ARG content\nprint(2+2)\n@@END_ARG\n@@END_TOOL_CALL", None),
    ("@@TOOL_CALL Write\n@@ARG path\nfile.py\n@@END_ARG\n@@ARG path\nother.py\n@@END_ARG\n@@END_TOOL_CALL", "INVALID_TOOL_FRAME"),
    ("@@TOOL_CALL Write\n@@ARG path\nfile.py\n@@END_ARG", "INVALID_TOOL_FRAME"),
    ("@@TOOL_CALL NoSuchTool\n@@ARG path\na\n@@END_ARG\n@@END_TOOL_CALL", "TOOL_NOT_AVAILABLE"),
])
def test_raw_frame_validation(frame, code):
    from bridge_x.tools import parse_intent
    req = request_factory([WRITE, BASH])
    if code:
        with pytest.raises(BridgeError) as e:
            parse_intent(frame, req)
        assert e.value.code == code
    else:
        calls = parse_intent(frame, req)
        assert calls[0].name == "Write"
        assert calls[0].arguments == {"path": "file.py", "content": "print(2+2)"}


def test_end_to_end_molab_wire_write_bash_and_confirmed_output(monkeypatch, tmp_path):
    """Mock server speaks Molab SSE. Client executes tools, not the bridge."""
    import sys
    from bridge_x_test_runner.runner import Sandbox
    sandbox = Sandbox(tmp_path)
    seen = []
    def handler(request):
        payload = json.loads(request.content)
        seen.append(payload)
        combined = "\n".join(m["parts"][0]["text"] for m in payload["messages"])
        if "<tool_result" not in combined:
            answer = {"tool_calls": [{"name": "Write", "arguments": {"path": "agent_check.py", "content": "print(2 + 2)\n"}}]}
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=response_stream({"type": "text-delta", "delta": json.dumps(answer)},
                                                          {"type": "finish", "finishReason": "stop"}))
        if combined.count("<tool_result") == 1:
            answer = {"tool_calls": [{"name": "Bash", "arguments": {"command": "python agent_check.py"}}]}
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=response_stream({"type": "text-delta", "delta": json.dumps(answer)},
                                                          {"type": "finish", "finishReason": "stop"}))
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=response_stream({"type": "text-delta", "delta": "Проверено: 4"},
                                                      {"type": "finish", "finishReason": "stop"}))
    mock_molab(monkeypatch, handler)
    settings = Settings(provider="molab", molab_config_path=save_config(tmp_path), journal_path=":memory:")
    history = [{"role": "user", "content": "Create agent_check.py and run it"}]
    with TestClient(create_app(settings)) as client:
        for step in range(3):
            res = client.post("/v1/chat/completions", headers={"Authorization": "Bearer molab-local"},
                              json={"model": "molab-glm", "messages": history, "tools": [WRITE, BASH], "conversation_id": "integration"})
            assert res.status_code == 200, res.text
            message = res.json()["choices"][0]["message"]
            history.append(message)
            calls = message.get("tool_calls") or []
            if step < 2:
                assert len(calls) == 1
                args = json.loads(calls[0]["function"]["arguments"])
                if step == 0:
                    assert calls[0]["function"]["name"] == "Write"
                    result = sandbox.write(args["path"], args["content"])
                    assert (tmp_path / "agent_check.py").exists()
                else:
                    assert calls[0]["function"]["name"] == "Bash"
                    assert args["command"] == "python agent_check.py"
                    receipt = sandbox.run_python("agent_check.py", timeout=5)
                    assert receipt.stdout.strip() == "4" and receipt.exit_code == 0
                    result = {"exit_code": receipt.exit_code, "stdout": receipt.stdout}
                history.append({"role": "tool", "tool_call_id": calls[0]["id"], "content": json.dumps(result)})
            else:
                assert not calls
                assert message["content"] == "Проверено: 4"
    assert len(seen) == 3


def test_123_event_codes_and_safe_nested_classification():
    assert decode_molab_event('{"type":"abort","error":{"message":"private-value"}}')[0].code == "UPSTREAM_ABORTED"
    assert decode_molab_event('{"type":"error","error":{"message":"private-value"}}')[0].code == "UPSTREAM_EVENT_ERROR"
    assert decode_molab_event('{"type":"finish","finishReason":"error","error":{"data":{"statusCode":429,"message":"private-value"}}}')[0].code == "UPSTREAM_RATE_LIMIT"
    assert decode_molab_event('{"type":"finish","finishReason":"error","providerMetadata":{"errorText":"context_length_exceeded private-value"}}')[0].code == "UPSTREAM_CONTEXT_LIMIT"
    assert decode_molab_event('{"type":"finish","finishReason":"error","error":{"code":"max_output_tokens"}}')[0].code == "UPSTREAM_OUTPUT_LIMIT"


def test_123_tool_prompt_not_duplicated_for_molab(monkeypatch, tmp_path):
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=response_stream({"type":"text-delta", "delta":"hello"}, {"type":"finish", "finishReason":"stop"}))
    mock_molab(monkeypatch, handler)
    cfg = save_config(tmp_path)
    settings = Settings(provider="molab", molab_config_path=cfg, journal_path=":memory:")
    with TestClient(create_app(settings)) as client:
        resp = client.post("/v1/chat/completions", json={"model":"molab-glm", "messages":[{"role":"user","content":"Create file"}], "tools":[WRITE,BASH]}, headers={"Authorization":"Bearer molab-local"})
        assert resp.status_code == 200
        content = "\n".join(m["parts"][0]["text"] for m in captured[0]["messages"])
        assert "Bridge X tool protocol:" not in content
        assert "Exact schemas for the most relevant tools" in content
        assert "tool_calls JSON" not in content
        assert content.count("Declared tool names:") == 1


def test_123_sse_trace_distinguishes_abort_and_redacts_content(monkeypatch, tmp_path):
    private = "THIS_IS_PRIVATE_FROM_UPSTREAM_DO_NOT_LOG"
    mock_molab(monkeypatch, lambda request: httpx.Response(200, headers={"content-type":"text/event-stream"}, content=response_stream(
        {"type":"text-delta", "delta":"partial"}, {"type":"abort", "error":{"message":private}})))
    cfg = save_config(tmp_path)
    settings = Settings(provider="molab", molab_config_path=cfg, journal_path=str(tmp_path / "journal.sqlite3"))
    with TestClient(create_app(settings)) as client:
        resp = client.post("/v1/chat/completions", json={"model":"molab-glm", "messages":[{"role":"user","content":"test"}], "tools":[WRITE]}, headers={"Authorization":"Bearer molab-local"})
        assert resp.status_code == 502
        assert resp.json()["error"]["code"] == "UPSTREAM_ABORTED"
        diag = client.get("/diagnostics", headers={"Authorization":"Bearer molab-local"})
        assert diag.status_code == 200
        record = diag.json()["recent_upstream_failures"][0]
        assert record["upstream_event"] == "abort"
        assert record["upstream_status"] == 200
        assert record["sse_event_count"] == 2
        assert record["sse_partial_text_chars"] == len("partial")
        assert record["input_tool_count"] == 1
        assert record["upstream_request_bytes"] > 100
        assert private not in diag.text
        assert private not in resp.text
    assert private.encode() not in (tmp_path / "journal.sqlite3").read_bytes()


def test_123_finishing_error_traced_even_after_partial_output(monkeypatch, tmp_path):
    mock_molab(monkeypatch, lambda request: httpx.Response(200, headers={"content-type":"text/event-stream"}, content=response_stream(
        {"type":"text-delta", "delta":"PREMATURE"}, {"type":"finish", "finishReason":"error"})))
    cfg = save_config(tmp_path)
    settings = Settings(provider="molab", molab_config_path=cfg, journal_path=":memory:")
    with TestClient(create_app(settings)) as client:
        res = client.post("/v1/chat/completions", json={"model":"molab-glm", "messages":[{"role":"user","content":"hello"}]}, headers={"Authorization":"Bearer molab-local"})
        assert res.status_code == 502
        assert res.json()["error"]["code"] == "UPSTREAM_FINISH_ERROR"
        assert "PREMATURE" not in res.text
        trace = client.get("/diagnostics", headers={"Authorization":"Bearer molab-local"}).json()["recent_upstream_failures"][0]
        assert trace["upstream_event"] == "finish"
        assert trace["sse_partial_text_chars"] == len("PREMATURE")


def test_123_stream_error_never_delivers_tool_call(monkeypatch, tmp_path):
    proposal = json.dumps({"tool_calls":[{"name":"Write","arguments":{"path":"file.txt","content":"bad"}}]})
    mock_molab(monkeypatch, lambda request: httpx.Response(200, headers={"content-type":"text/event-stream"}, content=response_stream(
        {"type":"text-delta", "delta":proposal}, {"type":"abort"})))
    cfg=save_config(tmp_path)
    settings=Settings(provider="molab", molab_config_path=cfg, journal_path=":memory:")
    with TestClient(create_app(settings)) as client:
        res=client.post("/v1/chat/completions", json={"model":"molab-glm", "stream": True, "messages":[{"role":"user", "content":"create file"}], "tools":[WRITE]}, headers={"Authorization":"Bearer molab-local"})
        assert '"name":"Write"' not in res.text
        assert "UPSTREAM_ABORTED" in res.text
        assert "data: [DONE]" not in res.text
