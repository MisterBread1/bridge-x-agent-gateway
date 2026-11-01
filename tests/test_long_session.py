"""Long client sessions are compacted before provider submission, not abandoned."""
import copy
import json
import httpx
import pytest
from fastapi.testclient import TestClient
from bridge_x.config import Settings
from bridge_x.context import compact
from bridge_x.gateway import create_app
from bridge_x.providers import TextDelta, Finish
from bridge_x.errors import BridgeError
from .conftest import BASH
from .test_molab_integration import save_config, mock_molab, response_stream

AUTH = {"Authorization": "Bearer molab-local"}


def long_history():
    messages = [{"role": "system", "content": "Keep changes confined to the fixture."},
                {"role": "user", "content": "Original goal: fix only the fixture CSS."}]
    for i in range(8):
        messages += [{"role": "assistant", "tool_calls": [{"id": f"old-{i}", "function": {
            "name": "Bash", "arguments": json.dumps({"command": f"fixture-check-{i}"})}}]},
            {"role": "tool", "tool_call_id": f"old-{i}",
             "content": json.dumps({"exit_code": 0, "stdout": "x" * 260_000})}]
    messages.append({"role": "user", "content": "Continue the same task; leave neighbors unchanged."})
    return messages


@pytest.mark.parametrize("stream", [False, True])
def test_two_megabyte_client_history_and_recent_read_continue_same_task(stream):
    observed = []
    class Provider:
        async def generate(self, req, messages):
            observed.append(messages)
            yield TextDelta("Current turn accepted")
            yield Finish("stop")
    history = long_history()
    original = copy.deepcopy(history)
    with TestClient(create_app(Settings(journal_path=":memory:"), Provider())) as client:
        response = client.post("/v1/chat/completions", headers=AUTH,
                               json={"messages": history, "tools": [BASH], "stream": stream})
        assert response.status_code == 200, response.text
        assert "CONTEXT_BUDGET_EXCEEDED" not in response.text
        assert len(json.dumps(observed[0])) < 220_000
        assert history[0] in observed[0] and history[1] in observed[0] and observed[0][-1] == history[-1]
        assert client.app.state.journal.db.execute("SELECT count(*) FROM operations WHERE state='EXECUTED'").fetchone()[0] == 8
        for message in observed[0]:
            if message.get("role") == "tool":
                assert json.loads(message["content"])["exit_code"] == 0
    assert history == original


def test_recent_completed_large_input_archived_as_whole_but_pending_input_preserved():
    messages = [{"role": "user", "content": "Original goal"},
                {"role": "assistant", "tool_calls": [{"id": "done", "function": {
                    "name": "Write", "arguments": json.dumps({"content": "x" * 300_000})}}]},
                {"role": "tool", "tool_call_id": "done", "content": '{"success":true}'},
                {"role": "assistant", "tool_calls": [{"id": "pending", "function": {
                    "name": "Bash", "arguments": '{"command":"must remain exact"}'}}]}]
    bounded, stats = compact(messages, 5000)
    assert bounded[0] == messages[0] and bounded[-1] == messages[-1]
    assert stats["archived_completed_exchanges"] == 1
    assert not any(m.get("tool_call_id") == "done" for m in bounded)
    with pytest.raises(BridgeError):
        compact([messages[0], messages[1]], 5000)  # Pending large Write is never truncated.


@pytest.mark.parametrize("rejection", ["http", "sse"])
def test_explicit_context_rejection_gets_one_smaller_pre_output_attempt(tmp_path, monkeypatch, rejection):
    captured = []
    def handler(request):
        captured.append(json.loads(request.content))
        if len(captured) == 1:
            if rejection == "http":
                return httpx.Response(413)
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                content=response_stream({"type": "error", "errorText": "context_length_exceeded"}))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=response_stream(
            {"type": "text-delta", "delta": "Response after compaction"}, {"type": "finish", "finishReason": "stop"}))
    mock_molab(monkeypatch, handler)
    cfg = Settings(provider="molab", molab_config_path=save_config(tmp_path), journal_path=":memory:")
    messages = [{"role": "user", "content": "Original task"},
                {"role": "assistant", "content": "old explanation " * 6000},
                {"role": "user", "content": "Continue without changing the goal"}]
    with TestClient(create_app(cfg)) as client:
        result = client.post("/v1/chat/completions", headers=AUTH, json={"messages": messages})
        assert result.status_code == 200, result.text
        assert len(captured) == 2 and len(json.dumps(captured[1])) < len(json.dumps(captured[0])) / 2
        assert "Original task" in json.dumps(captured[1]) and "Continue without changing the goal" in json.dumps(captured[1])


def test_context_recovery_never_loops_or_retries_after_partial_text(tmp_path, monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=response_stream(
            {"type": "text-delta", "delta": "Partial"},
            {"type": "error", "errorText": "context_length_exceeded"}))
    mock_molab(monkeypatch, handler)
    cfg = Settings(provider="molab", molab_config_path=save_config(tmp_path), journal_path=":memory:")
    with TestClient(create_app(cfg)) as client:
        response = client.post("/v1/chat/completions", headers=AUTH,
            json={"messages": [{"role": "user", "content": "Task"}, {"role": "assistant", "content": "x" * 90_000}], "stream": True})
        assert len(requests) == 1 and "[DONE]" not in response.text
        assert "UPSTREAM_CONTEXT_LIMIT" in response.text


def test_repeated_context_rejection_stops_after_one_recovery_attempt(tmp_path, monkeypatch):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(413)
    mock_molab(monkeypatch, handler)
    cfg = Settings(provider="molab", molab_config_path=save_config(tmp_path), journal_path=":memory:")
    with TestClient(create_app(cfg)) as client:
        result = client.post("/v1/chat/completions", headers=AUTH,
            json={"messages": [{"role": "user", "content": "Task"}, {"role": "assistant", "content": "x" * 90_000}, {"role": "user", "content": "Continue"}]})
        assert result.status_code == 413 and len(requests) == 2
