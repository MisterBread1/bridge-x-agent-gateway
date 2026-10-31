"""Synthetic reproductions of long ZCode requests without contacting Molab."""
import json
from fastapi.testclient import TestClient
from bridge_x.config import Settings
from bridge_x.gateway import create_app
from bridge_x.sse import SSEParser


def test_55_tools_and_260kb_payload(tmp_path):
    tools = []
    for i in range(55):
        tools.append({"type": "function", "function": {"name": f"Tool_{i}", "description": "T"*500,
                     "parameters": {"type": "object", "properties": {"param": {"type": "string", "description": "S"*2500}},
                                    "additionalProperties": False}}})
    messages = [{"role": "user", "content": "This is synthetic test data." + "X" * 9_000}]
    messages += [{"role": "assistant", "content": "reasoning-placeholder " + "y" * 4_000} for _ in range(18)]
    body = {"model": "bridge-x-fake", "messages": messages, "tools": tools, "stream": False}
    payload_size = len(json.dumps(body).encode())
    assert payload_size > 200_000, payload_size
    settings = Settings(journal_path=str(tmp_path / "stress.db"), max_context_chars=220_000)
    with TestClient(create_app(settings)) as client:
        result = client.post("/v1/chat/completions", headers={"Authorization": "Bearer molab-local"}, json=body)
        assert result.status_code == 200, result.text
        assert result.json()["choices"][0]["finish_reason"] == "stop"


def test_100mb_sse_stream_in_small_frames():
    # No accumulation in parser; 100MB processed incrementally.
    parser = SSEParser(max_event_chars=4096)
    one = b'data: ' + b'x' * 1024 + b'\n\n'
    count = 0
    for i in range(100_000):
        count += len(parser.feed(one))
    assert count == 100_000
    assert parser.finish() == []


def test_500_turns_of_bounded_context():
    from bridge_x.context import compact
    msgs = [{"role": "user", "content": "Build the project"}]
    for i in range(250):
        msgs.append({"role": "assistant", "tool_calls": [{"id": f"call_{i}", "function": {"name": "Bash", "arguments": '{"command":"python test.py"}'}}]})
        msgs.append({"role": "tool", "tool_call_id": f"call_{i}", "content": "stdout:" + "x" * 2500})
    compacted, _ = compact(msgs, max_context_chars=220_000)
    assert compacted[0]["content"] == "Build the project"
    assert compacted[-1]["tool_call_id"] == "call_249"
    tool_ids = [m["tool_call_id"] for m in compacted if m.get("role") == "tool"]
    assert tool_ids[-1] == "call_249"
    assert all(not m.get("tool_calls") or all(
        c["id"] in tool_ids for c in m["tool_calls"])
        for m in compacted if m.get("role") == "assistant")
    assert any("context archival" in m.get("content", "") for m in compacted if isinstance(m.get("content"), str))
