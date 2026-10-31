"""Regression checks against V11 behavior: text tool proposals, long prompts, 429 SSE."""
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from bridge_x.schemas import ChatRequest
from bridge_x.tools import parse_intent
from bridge_x.errors import BridgeError
from bridge_x.config import Settings
from bridge_x.gateway import create_app
from bridge_x.molab_provider import _tool_prompt, build_molab_payload, read_molab_config
from .test_molab_integration import save_config, mock_molab, response_stream
from .conftest import WRITE, BASH


def request_for(tools, text="Создай файл и запусти тест"):
    return ChatRequest.model_validate({"model": "molab-glm", "tools": tools, "messages": [{"role": "user", "content": text}]})


def test_frame_file_with_windows_path_and_multiline_code():
    value = 'C:\\ExampleProject\\file.py'
    program = 'print("one")\nprint("two")'
    frame = f'@@TOOL_CALL Write\n@@ARG path\n{value}\n@@END_ARG\n@@ARG content\n{program}\n@@END_ARG\n@@END_TOOL_CALL'
    calls = parse_intent(frame, request_for([WRITE, BASH]))
    assert len(calls) == 1
    assert calls[0].arguments == {"path": value, "content": program}
    assert json.loads(calls[0].openai()["function"]["arguments"]) == calls[0].arguments


def test_frame_bash_no_json_envelope():
    frame = '@@TOOL_CALL Bash\n@@ARG command\npython agent_check.py\n@@END_ARG\n@@END_TOOL_CALL'
    calls = parse_intent(frame, request_for([WRITE, BASH]))
    assert calls[0].arguments == {"command": "python agent_check.py"}


def test_frame_mixed_structured_arguments():
    complex_tool = {"type": "function", "function": {"name": "Batch", "parameters": {
        "type": "object", "additionalProperties": False, "required": ["label", "files", "count"],
        "properties": {"label": {"type": "string"}, "files": {"type": "array", "items": {"type": "string"}}, "count": {"type": "integer"}}}}}
    frame = ('@@TOOL_CALL Batch\n@@ARG label\ncheck\n@@END_ARG\n'
             '@@VALUE files\n["a.py", "b.py"]\n@@END_VALUE\n'
             '@@VALUE count\n2\n@@END_VALUE\n@@END_TOOL_CALL')
    calls = parse_intent(frame, request_for([complex_tool]))
    assert calls[0].arguments == {"label": "check", "files": ["a.py", "b.py"], "count": 2}


def test_frame_reject_invalid_typed_value():
    req = request_for([WRITE])
    frame = '@@TOOL_CALL Write\n@@VALUE path\n{broken\n@@END_VALUE\n@@END_TOOL_CALL'
    with pytest.raises(BridgeError) as exc:
        parse_intent(frame, req)
    assert exc.value.code == "INVALID_TOOL_VALUE"


def test_frame_never_accepts_unknown_extra_field():
    frame = ('@@TOOL_CALL Bash\n@@ARG command\npython test.py\n@@END_ARG\n'
             '@@ARG dangerous\nextra\n@@END_ARG\n@@END_TOOL_CALL')
    with pytest.raises(BridgeError) as exc:
        parse_intent(frame, request_for([BASH]))
    assert exc.value.code == "TOOL_SCHEMA_MISMATCH"


def test_prompt_compact_for_55_tools_and_never_requests_json_envelope():
    tools = [WRITE, BASH]
    for n in range(53):
        tools.append({"type":"function", "function":{"name":f"ExtraTool{n}",
                      "description": "Extended tool " * 100,
                      "parameters":{"type":"object", "properties":{"sample":{"type":"string"}}, "required":["sample"]}}})
    req = request_for(tools)
    prompt = _tool_prompt(req, [{"role": "user", "content": "Создай файл и запусти тест"}])
    assert len(prompt.encode("utf-8")) < 4200
    assert "@@TOOL_CALL" in prompt
    assert '"tool_calls"' not in prompt
    assert "Write: " in prompt and "Bash: " in prompt


def test_outgoing_molab_payload_contains_frame_instructions_not_json_tool_commands(tmp_path):
    cfg = read_molab_config(save_config(tmp_path))
    req = request_for([WRITE, BASH])
    wire = build_molab_payload(req, [m.model_dump(exclude_none=True) for m in req.messages], cfg)
    assert wire["tools"] == []
    combined = "\n".join(x["parts"][0]["text"] for x in wire["messages"])
    assert "@@TOOL_CALL" in combined
    assert "respond with tool_calls JSON" not in combined


def test_molab_frame_write_then_bash_end_to_end(monkeypatch, tmp_path):
    seen = []
    def handler(request):
        wire = json.loads(request.content)
        text = "\n".join(msg["parts"][0]["text"] for msg in wire["messages"])
        seen.append(text)
        if "<tool_result" not in text:
            answer = '@@TOOL_CALL Write\n@@ARG path\nagent_check.py\n@@END_ARG\n@@ARG content\nprint(2 + 2)\n@@END_ARG\n@@END_TOOL_CALL'
        else:
            answer = '@@TOOL_CALL Bash\n@@ARG command\npython agent_check.py\n@@END_ARG\n@@END_TOOL_CALL'
        return httpx.Response(200, headers={"content-type":"text/event-stream"}, content=response_stream(
            {"type":"text-delta", "delta":answer}, {"type":"finish", "finishReason":"stop"}))
    mock_molab(monkeypatch, handler)
    cfg = save_config(tmp_path)
    settings = Settings(provider="molab", molab_config_path=cfg, journal_path=":memory:")
    with TestClient(create_app(settings)) as client:
        messages = [{"role":"user", "content":"Создай файл agent_check.py, затем запусти его"}]
        result = client.post("/v1/chat/completions", json={"model":"molab-glm","messages":messages,"tools":[WRITE, BASH]}, headers={"Authorization":"Bearer molab-local"})
        assert result.status_code == 200, result.text
        first = result.json()["choices"][0]["message"]["tool_calls"][0]
        assert first["function"]["name"] == "Write"
        args = json.loads(first["function"]["arguments"])
        assert args == {"path":"agent_check.py", "content":"print(2 + 2)"}
        messages += [{"role": "assistant", "tool_calls":[first]},
                     {"role":"tool", "tool_call_id":first["id"], "content":'{"success":true}'}]
        second = client.post("/v1/chat/completions", json={"model":"molab-glm","messages":messages,"tools":[WRITE, BASH]}, headers={"Authorization":"Bearer molab-local"})
        assert second.status_code == 200, second.text
        call2 = second.json()["choices"][0]["message"]["tool_calls"][0]
        assert call2["function"]["name"] == "Bash"
    assert len(seen) == 2


def test_rate_limit_sse_is_reported_not_retried_or_bypassed(monkeypatch, tmp_path):
    count = [0]
    def handler(request):
        count[0] += 1
        return httpx.Response(200, headers={"content-type":"text/event-stream"}, content=response_stream(
            {"type":"error", "error":{"statusCode":429, "message":"rate limit reached"}}))
    mock_molab(monkeypatch, handler)
    cfg = save_config(tmp_path)
    settings = Settings(provider="molab", molab_config_path=cfg, journal_path=":memory:")
    with TestClient(create_app(settings)) as client:
        res = client.post("/v1/chat/completions", headers={"Authorization":"Bearer molab-local"}, json={
            "model":"molab-glm", "messages":[{"role":"user", "content":"Hello"}], "tools":[WRITE]})
        assert res.status_code == 429
        assert res.json()["error"]["code"] == "UPSTREAM_RATE_LIMIT"
        assert count[0] == 1


def test_frame_streaming_is_zcode_compatible(monkeypatch, tmp_path):
    frame = '@@TOOL_CALL Write\n@@ARG path\nagent_check.py\n@@END_ARG\n@@ARG content\nprint(2 + 2)\n@@END_ARG\n@@END_TOOL_CALL'
    mock_molab(monkeypatch, lambda request: httpx.Response(
        200, headers={"content-type":"text/event-stream"}, content=response_stream(
            {"type":"text-delta", "delta":frame[:27]},
            {"type":"text-delta", "delta":frame[27:]},
            {"type":"finish", "finishReason":"stop"})))
    cfg=save_config(tmp_path)
    with TestClient(create_app(Settings(provider="molab", molab_config_path=cfg, journal_path=":memory:"))) as client:
        res=client.post('/v1/chat/completions', headers={"Authorization":"Bearer molab-local"},
            json={"model":"molab-glm", "stream":True,
                  "messages":[{"role":"user","content":"Создай файл"}],"tools":[WRITE,BASH]})
        assert res.status_code == 200, res.text
        assert '"name":"Write"' in res.text
        assert '"finish_reason":"tool_calls"' in res.text
        assert 'data: [DONE]' in res.text
        assert '@@TOOL_CALL' not in res.text


def test_late_rate_limit_never_releases_partial_tool(monkeypatch, tmp_path):
    frame = '@@TOOL_CALL Bash\n@@ARG command\npython test.py\n@@END_ARG\n@@END_TOOL_CALL'
    mock_molab(monkeypatch, lambda request: httpx.Response(200, headers={"content-type":"text/event-stream"},
        content=response_stream({"type":"text-delta", "delta":frame},
                                {"type":"error", "error":{"statusCode":429}})))
    cfg=save_config(tmp_path)
    with TestClient(create_app(Settings(provider="molab", molab_config_path=cfg, journal_path=":memory:"))) as client:
        res=client.post('/v1/chat/completions', headers={"Authorization":"Bearer molab-local"},
            json={"model":"molab-glm", "stream":True,
                  "messages":[{"role":"user","content":"Запусти python"}],"tools":[BASH]})
        assert res.status_code == 200
        assert 'event: error' in res.text
        assert 'UPSTREAM_RATE_LIMIT' in res.text
        assert '"name":"Bash"' not in res.text
        assert 'data: [DONE]' not in res.text
