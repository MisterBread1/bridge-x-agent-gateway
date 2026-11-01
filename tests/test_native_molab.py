"""Native Molab client-tools contract, independent of textual JSON intents."""
import html
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from bridge_x.config import Settings
from bridge_x.errors import BridgeError
from bridge_x.gateway import create_app
from bridge_x.molab_native import NativeToolAssembler, native_messages, native_tools
from bridge_x.molab_provider import read_molab_config, build_molab_payload
from bridge_x.molab_runtime import ensure_native_mode
from bridge_x.schemas import ChatRequest
from .conftest import WRITE, BASH
from .test_molab_integration import mock_molab, save_config, response_stream

AUTH = {"Authorization": "Bearer molab-local"}


def request(**overrides):
    return ChatRequest.model_validate({"messages": [{"role": "user", "content": "edit"}], "tools": [WRITE, BASH], **overrides})


def events(values=None, name="Write", call_id="native-1"):
    values = values if values is not None else {"path": "a.html", "content": 'CSS { content: "quoted"; }\n'}
    return [{"type": "tool-input-start", "toolCallId": call_id, "toolName": name},
            {"type": "tool-input-delta", "toolCallId": call_id, "inputTextDelta": json.dumps(values)},
            {"type": "tool-input-available", "toolCallId": call_id, "toolName": name, "input": values}]


def test_cli_defaults_to_native_without_changing_library_compatibility(monkeypatch):
    monkeypatch.delenv("BRIDGEX_MOLAB_TOOL_MODE", raising=False)
    assert Settings.from_env().molab_tool_mode == "native"
    assert Settings().molab_tool_mode == "structured"


def test_frontend_tool_definitions_use_original_dynamic_schemas():
    definitions = native_tools(request())
    assert [t["name"] for t in definitions] == ["Write", "Bash"]
    assert definitions[0]["parameters"] == WRITE["function"]["parameters"]
    assert all(t["source"] == "frontend" for t in definitions)
    assert native_tools(request(tool_choice="none")) == []
    assert len(native_tools(request(tool_choice={"type": "function", "function": {"name": "Bash"}}))) == 1


def test_native_payload_does_not_ask_for_json_text(tmp_path):
    req = request()
    payload = build_molab_payload(req, [m.model_dump() for m in req.messages], read_molab_config(save_config(tmp_path)), protocol="native")
    assert payload["tools"][0]["source"] == "frontend"
    assert payload["tools"][0]["parameters"] == WRITE["function"]["parameters"]
    text = payload["messages"][0]["parts"][0]["text"]
    assert "Use the provided native function tools" in text
    assert "return ONLY one complete strict JSON" not in text


def test_native_history_pairs_executor_result_with_call_instead_of_user_prose():
    values = {"path": "x.html", "content": "original"}
    history = [{"role": "user", "content": "edit"}, {"role": "assistant", "tool_calls": [
        {"id": "c1", "function": {"name": "Write", "arguments": json.dumps(values)}}]},
        {"role": "tool", "tool_call_id": "c1", "content": '{"success":true}'}]
    messages = native_messages(request(), history, 2200)
    part = messages[-1]["parts"][0]
    assert part == {"type": "dynamic-tool", "toolName": "Write", "toolCallId": "c1",
                    "state": "output-available", "input": values, "output": {"success": True}}
    assert "<tool_result" not in json.dumps(messages)


def test_older_completed_native_cycles_keep_the_same_structured_provenance_as_recent_ones():
    history = [{"role": "user", "content": "goal"}]
    for i in range(4):
        history += [{"role": "assistant", "tool_calls": [{"id": f"c{i}", "function": {
            "name": "Write", "arguments": json.dumps({"path": "a", "content": f"private-source-{i}"})}}]},
            {"role": "tool", "tool_call_id": f"c{i}", "content": '{"success":true}'}]
    serialized = json.dumps(native_messages(request(), history, 2200))
    for i in range(4):
        assert f"private-source-{i}" in serialized
    parts = [p for m in native_messages(request(), history, 2200) for p in m["parts"] if p["type"] == "dynamic-tool"]
    assert len(parts) == 4 and all(p["state"] == "output-available" for p in parts)


def test_native_stream_snapshot_and_argument_types_are_preserved():
    assembler = NativeToolAssembler(request(), 10000)
    for event in events():
        assembler.feed(event)
    calls = assembler.finish()
    assert len(calls) == 1 and calls[0].name == "Write"
    assert json.loads(calls[0].arguments)["content"] == 'CSS { content: "quoted"; }\n'


@pytest.mark.parametrize("mutation", ["missing_start", "missing_available", "duplicate_start", "late_delta", "changed_input", "undeclared", "server_executed"])
def test_malformed_native_sequences_never_authorize_an_action(mutation):
    stream = events()
    if mutation == "missing_start": stream = stream[1:]
    elif mutation == "missing_available": stream = stream[:-1]
    elif mutation == "duplicate_start": stream.insert(1, stream[0])
    elif mutation == "late_delta": stream.append(stream[1])
    elif mutation == "changed_input": stream[-1] = {**stream[-1], "input": {"path": "different", "content": "x"}}
    elif mutation == "undeclared": stream[0] = {**stream[0], "toolName": "execute_code"}
    else: stream.append({"type": "tool-output-available", "toolCallId": "native-1", "output": "server executed"})
    assembler = NativeToolAssembler(request(), 10000)
    with pytest.raises(BridgeError):
        for event in stream: assembler.feed(event)
        assembler.finish()


@pytest.mark.parametrize("streaming", [False, True])
def test_native_molab_events_become_real_openai_tool_calls(monkeypatch, tmp_path, streaming):
    captured = []
    def respond(req):
        captured.append(json.loads(req.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=response_stream(
            *events(), {"type": "finish", "finishReason": "tool-calls"}))
    mock_molab(monkeypatch, respond)
    settings = Settings(provider="molab", molab_config_path=save_config(tmp_path), journal_path=":memory:", molab_tool_mode="native")
    with TestClient(create_app(settings)) as client:
        response = client.post("/v1/chat/completions", headers=AUTH, json={"messages": [{"role": "user", "content": "write"}], "tools": [WRITE], "stream": streaming})
        assert response.status_code == 200
        if streaming:
            assert '"name":"Write"' in response.text and "data: [DONE]" in response.text
        else:
            call = response.json()["choices"][0]["message"]["tool_calls"][0]
            assert json.loads(call["function"]["arguments"])["path"] == "a.html"
        assert client.get("/v1/capabilities", headers=AUTH).json()["native_tools"] is True
    assert captured[0]["tools"][0]["source"] == "frontend"


@pytest.mark.parametrize("text", ['{"tool_calls":[{"name":"Write","arguments":{"content":"broken"}',
                                  '{\n  "tool_calls": [', '```json\n{"tool_calls": []}\n```'])
def test_invalid_json_text_is_never_executed_in_native_mode(monkeypatch, tmp_path, text):
    mock_molab(monkeypatch, lambda _: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=response_stream(
        {"type": "text-delta", "delta": text},
        {"type": "finish", "finishReason": "stop"})))
    settings = Settings(provider="molab", molab_config_path=save_config(tmp_path), journal_path=":memory:", molab_tool_mode="native")
    with TestClient(create_app(settings)) as client:
        response = client.post("/v1/chat/completions", headers=AUTH, json={"messages": [{"role": "user"}], "tools": [WRITE]})
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "MOLAB_NATIVE_TOOL_EXPECTED"
        assert client.app.state.journal.db.execute("SELECT count(*) FROM operations").fetchone()[0] == 0


def test_late_error_never_releases_native_tool(monkeypatch, tmp_path):
    mock_molab(monkeypatch, lambda _: httpx.Response(200, headers={"content-type": "text/event-stream"}, content=response_stream(
        *events(), {"type": "finish", "finishReason": "tool-calls"}, {"type": "error", "errorText": "abort"})))
    settings = Settings(provider="molab", molab_config_path=save_config(tmp_path), journal_path=":memory:", molab_tool_mode="native")
    with TestClient(create_app(settings)) as client:
        response = client.post("/v1/chat/completions", headers=AUTH, json={"messages": [{"role": "user"}], "tools": [WRITE], "stream": True})
        assert "event: error" in response.text and "data: [DONE]" not in response.text
        assert '"name":"Write"' not in response.text


def test_zcode_session_header_enables_dispatch_deduplication():
    from .test_agent_recovery import Proposals
    provider = Proposals([("Write", {"path": "a", "content": "x"})])
    with TestClient(create_app(Settings(journal_path=":memory:"), provider=provider)) as client:
        body = {"messages": [{"role": "user"}], "tools": [WRITE]}
        headers = {**AUTH, "x-session-id": "sess-real-zcode"}
        assert client.post("/v1/chat/completions", headers=headers, json=body).status_code == 200
        assert client.post("/v1/chat/completions", headers=headers, json=body).status_code == 409
        assert provider.requests == 1


def test_runtime_mode_setup_changes_only_the_ai_mode(monkeypatch, tmp_path):
    state = {"mode": "code_mode"}; requests = []
    def respond(req):
        requests.append(req)
        if req.method == "GET":
            config = html.escape(json.dumps({"ai": {"mode": state["mode"]}}), quote=True)
            return httpx.Response(200, text=f'<marimo-user-config data-config="{config}"></marimo-user-config>')
        assert req.url.path == "/api/kernel/save_user_config"
        assert json.loads(req.content) == {"config": {"ai": {"mode": "manual"}}}
        state["mode"] = "manual"
        return httpx.Response(200, json={"success": True})
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(respond), **kw))
    config = read_molab_config(save_config(tmp_path))
    result = ensure_native_mode(config)
    assert result["changed"] and result["mode"] == "manual"
    assert len(requests) == 3
    requests.clear()
    assert not ensure_native_mode(config)["changed"]
    assert len(requests) == 1


def test_code_mode_is_rejected_before_any_model_request(monkeypatch, tmp_path):
    methods = []
    def respond(req):
        methods.append(req.method)
        return httpx.Response(200, text='<marimo-user-config data-config="{&quot;ai&quot;:{&quot;mode&quot;:&quot;code_mode&quot;}}"></marimo-user-config>')
    mock_molab(monkeypatch, respond)
    settings = Settings(provider="molab", molab_config_path=save_config(tmp_path), journal_path=":memory:",
                        molab_tool_mode="native", verify_molab_native_mode=True)
    with TestClient(create_app(settings)) as client:
        response = client.post("/v1/chat/completions", headers=AUTH, json={"messages": [{"role": "user"}], "tools": [WRITE]})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "MOLAB_NATIVE_MODE_REQUIRED"
    assert methods == ["GET"]


@pytest.mark.parametrize("status,html,code", [
    (410, "runtime expired", "MOLAB_RUNTIME_GONE"),
    (401, "access denied", "MOLAB_ACCESS_DENIED"),
    (503, "unavailable", "MOLAB_HTTP_ERROR"),
    (200, "<html>login page</html>", "MOLAB_NATIVE_MODE_UNKNOWN"),
])
def test_mode_check_does_not_mislabel_runtime_failures(monkeypatch, tmp_path, status, html, code):
    requests = []
    def handler(request):
        requests.append(request.method)
        return httpx.Response(status, text=html)
    mock_molab(monkeypatch, handler)
    settings = Settings(provider="molab", molab_tool_mode="native", verify_molab_native_mode=True,
                        molab_config_path=save_config(tmp_path), journal_path=":memory:")
    with TestClient(create_app(settings)) as client:
        response = client.post("/v1/chat/completions", headers=AUTH, json={"messages": [{"role":"user","content":"edit"}], "tools":[WRITE]})
        assert response.json()["error"]["code"] == code
    assert requests == ["GET"]
