"""Eight-turn native wire fixture with real temporary files and empty-output Python.

This is an offline protocol test, not a live ZCode or model reasoning test.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from bridge_x.config import Settings
from bridge_x.gateway import create_app
from bridge_x.sse import SSEParser
from .native_css_acceptance import tool


def decode(response, streaming):
    response.raise_for_status()
    if not streaming:
        return response.json()
    calls, content, reason, status = {}, "", None, None
    assert "event: error" not in response.text and "data: [DONE]" in response.text
    for event in SSEParser().feed(response.content):
        if event.data == "[DONE]":
            continue
        chunk = json.loads(event.data)
        status = chunk.get("x_bridge_x", status)
        choice = chunk["choices"][0]
        reason = choice["finish_reason"] or reason
        delta = choice["delta"]
        content += delta.get("content") or ""
        for call in delta.get("tool_calls", []):
            item = calls.setdefault(call["index"], {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
            item["id"] += call.get("id", "")
            for key in ("name", "arguments"):
                item["function"][key] += call.get("function", {}).get(key, "")
    message = {"role": "assistant", "content": content or None}
    if calls:
        message["tool_calls"] = [calls[i] for i in sorted(calls)]
    return {"choices": [{"message": message, "finish_reason": reason}], "x_bridge_x": status}


def run_acceptance(streaming=False):
    actions = [("Read", {"path": "app.css"}), ("Edit", {"path": "app.css", "old": "red", "new": "blue"}),
               ("Read", {"path": "app.css"}), ("Bash", {"command": "python verify.py blue"}),
               ("Read", {"path": "app.css"}), ("Edit", {"path": "app.css", "old": "blue", "new": "green"}),
               ("Bash", {"command": "python verify.py green"})]
    tools = [tool("Read", {"path": {"type": "string"}}, ["path"]),
             tool("Edit", {key: {"type": "string"} for key in ("path", "old", "new")}, ["path", "old", "new"]),
             tool("Bash", {"command": {"type": "string"}}, ["command"])]
    original_client = httpx.AsyncClient
    requests, executed, ids = [], [], set()
    with tempfile.TemporaryDirectory(prefix="bridge-continuity-") as temp:
        folder = Path(temp)
        initial = b".panel { color: red; padding: 24px; }\r\n"
        (folder / "app.css").write_bytes(initial)
        (folder / "neighbor.txt").write_bytes(b"UNCHANGED\r\n")
        (folder / "verify.py").write_text("from pathlib import Path\nimport sys\nassert Path('app.css').read_bytes() == ('.panel { color: '+sys.argv[1]+'; padding: 24px; }\\r\\n').encode()\np=Path('runs.txt')\np.write_text((p.read_text() if p.exists() else '')+sys.argv[1]+'\\n')\n", encoding="utf-8")
        config = folder / "config.json"
        config.write_text(json.dumps({"chat_url": "https://fixture.sb.molab.run/api/ai/chat", "marimo_session_id": "FIXTURE_ONLY"}), encoding="utf-8")
        settings = Settings(provider="molab", molab_tool_mode="native", journal_path=str(folder / "state.sqlite3"), molab_config_path=str(config))

        def upstream(request):
            posted = json.loads(request.content)
            completed = [p for m in posted["messages"] for p in m["parts"] if p.get("type") == "dynamic-tool"]
            index = len(requests)
            requests.append(posted)
            # The peer refuses to advance unless ALL actual receipts and their
            # paired call inputs survived serialization, including old Bash.
            assert len(completed) == index
            assert len({p["toolCallId"] for p in completed}) == index
            for i, part in enumerate(completed):
                assert part["state"] == "output-available"
                assert (part["toolName"], part["input"]) == actions[i]
                if part["toolName"] == "Bash":
                    assert part["output"] == {"exit_code": 0, "stdout": "", "stderr": ""}
                else:
                    assert part["output"]["success"] is True
            if index == len(actions):
                assert (folder / "app.css").read_bytes() == initial.replace(b"red", b"green")
                events = [{"type": "text-delta", "delta": "Fixture goal verified"}, {"type": "finish", "finishReason": "stop"}]
            else:
                name, values = actions[index]
                cid = f"fixture-{index}"
                events = [{"type": "tool-input-start", "toolCallId": cid, "toolName": name},
                          {"type": "tool-input-available", "toolCallId": cid, "toolName": name, "input": values},
                          {"type": "finish", "finishReason": "tool-calls"}]
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content="".join("data: " + json.dumps(e) + "\n\n" for e in events).encode())

        messages = [{"role": "user", "content": "Change only panel color from red to blue, verify, then green and verify again."}]
        with patch("httpx.AsyncClient", lambda **kw: original_client(transport=httpx.MockTransport(upstream), **kw)):
            for index in range(len(actions) + 1):
                # Every turn reopens the same database, including the empty Bash receipts.
                with TestClient(create_app(settings)) as client:
                    response = client.post("/v1/chat/completions", headers={"Authorization": "Bearer molab-local"},
                                           json={"messages": messages, "tools": tools, "conversation_id": "fixture-task", "stream": streaming})
                    result = decode(response, streaming)
                    message = result["choices"][0]["message"]
                    messages.append(message)
                    if index == len(actions):
                        assert result["choices"][0]["finish_reason"] == "stop" and not message.get("tool_calls")
                        assert result["x_bridge_x"]["task_completion_verified"] is False
                        assert client.app.state.journal.db.execute("SELECT count(*) FROM operations WHERE state!='EXECUTED'").fetchone()[0] == 0
                        break
                    calls = message["tool_calls"]
                    assert len(calls) == 1
                    call = calls[0]
                    assert call["id"] not in ids
                    ids.add(call["id"])
                    name, values = call["function"]["name"], json.loads(call["function"]["arguments"])
                    assert (name, values) == actions[index]
                    if name == "Read":
                        receipt = {"success": True, "content": (folder / values["path"]).read_text()}
                    elif name == "Edit":
                        path = folder / values["path"]
                        data = path.read_bytes()
                        assert data.count(values["old"].encode()) == 1
                        path.write_bytes(data.replace(values["old"].encode(), values["new"].encode(), 1))
                        receipt = {"success": True}
                    else:
                        color = "blue" if index == 3 else "green"
                        assert values["command"] == f"python verify.py {color}"
                        run = subprocess.run([sys.executable, "verify.py", color], cwd=folder, capture_output=True, timeout=10)
                        assert run.returncode == 0 and run.stdout == run.stderr == b""
                        receipt = {"exit_code": run.returncode, "stdout": "", "stderr": ""}
                    executed.append(name)
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(receipt)})
        assert executed == [name for name, _ in actions]
        assert (folder / "neighbor.txt").read_bytes() == b"UNCHANGED\r\n"
        assert (folder / "app.css").read_bytes() == initial.replace(b"red", b"green")
        assert (folder / "runs.txt").read_text().splitlines() == ["blue", "green"]
    return {"passed": True, "live_provider": False, "streaming": streaming, "turns": len(requests),
            "unique_tools": len(ids), "empty_stdout_checks": 2, "sqlite_reopens": len(requests)}


def main():
    print(json.dumps([run_acceptance(False), run_acceptance(True)]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
