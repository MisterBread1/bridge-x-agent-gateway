import json
import sys
import subprocess
from pathlib import Path
import asyncio
import pytest
from fastapi.testclient import TestClient
from bridge_x.config import Settings
from bridge_x.gateway import create_app
from bridge_x.journal import Journal
from bridge_x.providers import TextDelta, Finish, Failed
from .conftest import WRITE, BASH


def new_client(tmp_path, provider=None, **settings_kw):
    s = Settings(journal_path=str(tmp_path / "journal.db"), heartbeat_s=0.01, **settings_kw)
    app = create_app(s, provider=provider)
    return TestClient(app)


def request_body(tools=None, messages=None, stream=False, conversation_id="a"):
    return {"model": "bridge-x-fake", "stream": stream,
            "messages": messages if messages is not None else [{"role": "user", "content": "Create agent_check.py and execute"}],
            "tools": tools if tools is not None else [WRITE, BASH],
            "conversation_id": conversation_id}


def token():
    return {"Authorization": "Bearer molab-local"}


def test_local_auth(tmp_path):
    with new_client(tmp_path) as client:
        assert client.post("/v1/chat/completions", json=request_body()).status_code == 401
        assert client.post("/v1/chat/completions", headers=token(), json=request_body()).status_code == 200
        assert client.get("/diagnostics").status_code == 401


def test_health_ready(tmp_path):
    with new_client(tmp_path) as client:
        from bridge_x import __version__
        assert client.get("/health").json()["version"] == __version__
        assert client.get("/ready").json()["molab_adapter_available"] is False


def test_full_write_bash_procedure_with_real_file_and_terminal(tmp_path):
    # The simulator suggests tool calls; the test CLIENT, never the gateway, executes.
    with new_client(tmp_path) as client:
        conversation = request_body()
        first = client.post("/v1/chat/completions", headers=token(), json=conversation)
        assert first.status_code == 200, first.text
        call1 = first.json()["choices"][0]["message"]["tool_calls"][0]
        assert call1["function"]["name"] == "Write"
        args = json.loads(call1["function"]["arguments"])
        file_path = (tmp_path / args["path"]).resolve()
        assert file_path.is_relative_to(tmp_path.resolve())
        file_path.write_text(args["content"], encoding="utf-8")
        conversation["messages"].append(first.json()["choices"][0]["message"])
        conversation["messages"].append({"role": "tool", "tool_call_id": call1["id"],
                                         "content": json.dumps({"success": True, "path": args["path"]})})
        second = client.post("/v1/chat/completions", headers=token(), json=conversation)
        assert second.status_code == 200, second.text
        call2 = second.json()["choices"][0]["message"]["tool_calls"][0]
        assert call2["function"]["name"] == "Bash"
        args2 = json.loads(call2["function"]["arguments"])
        assert args2["command"] == "python agent_check.py"
        proc = subprocess.run([sys.executable, "-I", str(file_path)], cwd=tmp_path, capture_output=True,
                              text=True, timeout=5, check=False)
        assert proc.returncode == 0 and proc.stdout.strip() == "4"
        conversation["messages"].append(second.json()["choices"][0]["message"])
        conversation["messages"].append({"role": "tool", "tool_call_id": call2["id"],
                                         "content": json.dumps({"exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})})
        third = client.post("/v1/chat/completions", headers=token(), json=conversation)
        assert third.status_code == 200, third.text
        assert third.json()["choices"][0]["finish_reason"] == "stop"
        assert third.json()["choices"][0]["message"]["content"] == "Результат выполнения проверен."
        assert client.get("/diagnostics", headers=token()).status_code == 200


def test_streaming_tool_validation_and_done(tmp_path):
    with new_client(tmp_path) as client:
        result = client.post("/v1/chat/completions", headers=token(), json=request_body(stream=True))
        assert result.status_code == 200
        assert "finish_reason\":\"tool_calls" in result.text
        assert "data: [DONE]" in result.text
        assert '"name":"Write"' in result.text


def test_streaming_plain_text_chunks(tmp_path):
    with new_client(tmp_path) as client:
        result = client.post("/v1/chat/completions", headers=token(), json=request_body(tools=[], stream=True))
        assert result.status_code == 200
        assert "bridge-x waiting" not in result.text
        assert '"content":"Bridge X fake provider: "' in result.text
        assert "data: [DONE]" in result.text


def test_stream_terminal_error_does_not_fake_success(tmp_path):
    with new_client(tmp_path) as client:
        body = request_body(stream=True, messages=[{"role": "user", "content": "__test_sse_error__"}])
        result = client.post("/v1/chat/completions", headers=token(), json=body)
        assert result.status_code == 200
        assert "event: error" in result.text
        assert "data: [DONE]" not in result.text
        assert '"finish_reason":"stop"' not in result.text
        assert "\"tool_calls\"" not in result.text


def test_nonstream_terminal_error_is_http_error(tmp_path):
    with new_client(tmp_path) as client:
        body = request_body(messages=[{"role": "user", "content": "__test_sse_error__"}])
        result = client.post("/v1/chat/completions", headers=token(), json=body)
        assert result.status_code == 502
        assert result.json()["error"]["code"] == "UPSTREAM_SSE_ERROR"


def test_orphan_receipt_without_history_is_marked_unverified(tmp_path):
    with new_client(tmp_path) as client:
        result = client.post("/v1/chat/completions", headers=token(), json=request_body(
            messages=[{"role": "tool", "tool_call_id": "not-real", "content": "success"}]))
        assert result.status_code == 200, result.text
        assert client.app.state.journal.status("not-real") == "UNVERIFIED_CLIENT_RESULT"
        codes = [r["error_code"] for r in client.get("/diagnostics", headers=token()).json()["recent"]]
        assert "RECEIPT_UNVERIFIED" in codes


def test_invalid_json_input(tmp_path):
    with new_client(tmp_path) as client:
        result = client.post("/v1/chat/completions", headers=token(), content="{")
        assert result.status_code == 400


def test_input_limit(tmp_path):
    with new_client(tmp_path, max_request_bytes=100) as client:
        result = client.post("/v1/chat/completions", headers=token(), json=request_body())
        assert result.status_code == 413


def test_real_upstream_does_not_run_in_fake_mode(tmp_path):
    with new_client(tmp_path) as client:
        assert client.get("/health").json()["provider"] == "fake"


class LateError:
    async def generate(self, req, messages):
        yield TextDelta('{"tool_calls":[{"name":"Write","arguments":{"path":"a","content":"x"}}]}')
        yield Failed("UPSTREAM_SSE_ERROR", "late error")


class SlowProvider:
    async def generate(self, req, messages):
        await asyncio.sleep(0.04)
        yield TextDelta("Hello")
        yield Finish("stop")


class TruncatedProvider:
    async def generate(self, req, messages):
        yield TextDelta('{"tool_calls":[{"name":"Write","arguments":')
        yield Finish("length")


def test_late_sse_error_never_delivers_tool(tmp_path):
    with new_client(tmp_path, provider=LateError()) as client:
        result = client.post("/v1/chat/completions", headers=token(), json=request_body(stream=True))
        assert result.status_code == 200
        assert "event: error" in result.text
        assert '"name":"Write"' not in result.text
        assert "data: [DONE]" not in result.text


def test_heartbeat_does_not_cancel_provider(tmp_path):
    with new_client(tmp_path, provider=SlowProvider()) as client:
        result = client.post("/v1/chat/completions", headers=token(), json=request_body(stream=True, tools=[]))
        assert result.status_code == 200
        assert result.text.count(": bridge-x waiting") >= 1
        assert "Hello" in result.text
        assert "data: [DONE]" in result.text


def test_truncated_response_does_not_deliver_tool(tmp_path):
    with new_client(tmp_path, provider=TruncatedProvider()) as client:
        result = client.post("/v1/chat/completions", headers=token(), json=request_body(stream=True))
        assert "event: error" in result.text
        assert "data: [DONE]" not in result.text


def test_http_receipt_from_prior_bridge_migrates_from_chat_history(tmp_path):
    old_assistant = {"role": "assistant", "content": None, "tool_calls": [
        {"id": "call_from_12_1", "type": "function", "function": {
            "name": "Write", "arguments": json.dumps({"path": "agent_check.py", "content": "print(2 + 2)"})}}]}
    history = [{"role": "user", "content": "Create agent_check.py and execute"},
               old_assistant,
               {"role": "tool", "tool_call_id": "call_from_12_1", "content": '{"success":true}'}]
    with new_client(tmp_path) as client:
        res = client.post("/v1/chat/completions", headers=token(), json=request_body(messages=history))
        assert res.status_code == 200, res.text
        assert client.app.state.journal.status("call_from_12_1") == "RESULT_RECEIVED"
        assert res.json()["choices"][0]["message"]["tool_calls"][0]["function"]["name"] == "Bash"


def test_streaming_receipt_without_prior_local_db_continues(tmp_path):
    history = [
        {"role": "user", "content": "Create agent_check.py and execute"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "old_call", "type": "function", "function": {"name": "Write", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "old_call", "content": '{"success":true}'}
    ]
    with new_client(tmp_path) as client:
        result = client.post("/v1/chat/completions", headers=token(), json=request_body(messages=history, stream=True))
        assert result.status_code == 200
        assert '"name":"Bash"' in result.text
        assert "data: [DONE]" in result.text
        assert client.app.state.journal.status("old_call") == "RESULT_RECEIVED"
