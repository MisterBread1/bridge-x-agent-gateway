"""Real temporary file edits, restart checkpoints and ambiguous dispatches."""
import asyncio
import hashlib
import json
import sqlite3
import os
from pathlib import Path
import subprocess
import sys
import pytest
from fastapi.testclient import TestClient
from bridge_x.config import Settings
from bridge_x.errors import BridgeError
from bridge_x.gateway import create_app
from bridge_x.journal import Journal
from bridge_x.molab_provider import build_molab_payload, read_molab_config
from bridge_x.providers import Finish, TextDelta
from bridge_x.tool_models import ToolCall
from bridge_x_test_runner.runner import Sandbox
from .conftest import WRITE, BASH
from .test_molab_integration import save_config

AUTH = {"Authorization": "Bearer molab-local"}
READ = {"function": {"name": "Read", "parameters": {"type": "object", "properties": {
    "path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}}}
EDIT = {"function": {"name": "Edit", "parameters": {"type": "object", "properties": {
    "path": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}},
    "required": ["path", "old", "new"], "additionalProperties": False}}}


class Proposals:
    def __init__(self, actions):
        self.actions = actions
        self.requests = 0

    async def generate(self, req, messages):
        self.requests += 1
        receipts = sum(m.get("role") == "tool" for m in messages)
        if receipts < len(self.actions):
            name, arguments = self.actions[receipts]
            yield TextDelta(json.dumps({"tool": name, "arguments": arguments}))
        else:
            yield TextDelta("Client receipts received")
        yield Finish("stop")


def test_dispatch_retry_after_restart_never_reissues_bash(tmp_path):
    database = str(tmp_path / "recover.sqlite3")
    settings = Settings(journal_path=database)
    provider = Proposals([("Bash", {"command": "python agent_check.py"})])
    request = {"conversation_id": "task", "tools": [BASH], "messages": [{"role": "user", "content": "run"}]}
    with TestClient(create_app(settings, provider=provider)) as client:
        first = client.post("/v1/chat/completions", headers=AUTH, json=request)
        assert first.status_code == 200
        call = first.json()["choices"][0]["message"]["tool_calls"][0]
    # Simulate response/connection loss: the executor may have run it, but
    # no receipt is available. The retry must not contact the provider again.
    with TestClient(create_app(settings, provider=provider)) as client:
        retry = client.post("/v1/chat/completions", headers=AUTH, json=request)
        assert retry.status_code == 409
        assert retry.json()["error"]["code"] == "EXECUTION_UNKNOWN"
        assert provider.requests == 1
        assert client.get("/v1/operations/" + call["id"], headers=AUTH).json()["status"] == "DISPATCHED"
        request["messages"] += [first.json()["choices"][0]["message"],
                                {"role": "tool", "tool_call_id": call["id"], "content": '{"exit_code":0}'}]
        assert client.post("/v1/chat/completions", headers=AUTH, json=request).status_code == 200
        operation = client.get("/v1/operations/" + call["id"], headers=AUTH).json()
        assert operation["status"] == "EXECUTED"
        assert operation["events"] == ["PROPOSED", "VALIDATED", "DISPATCHED", "ACKNOWLEDGED", "EXECUTED"]


def test_idempotency_header_protects_clients_without_conversation_id():
    provider = Proposals([("Write", {"path": "a", "content": "x"})])
    body = {"tools": [WRITE], "messages": [{"role": "user", "content": "create"}]}
    with TestClient(create_app(Settings(journal_path=":memory:"), provider=provider)) as client:
        auth = {**AUTH, "Idempotency-Key": "operation-1"}
        assert client.post("/v1/chat/completions", headers=auth, json=body).status_code == 200
        body["stream"] = True
        assert client.post("/v1/chat/completions", headers=auth, json=body).status_code == 409
        assert provider.requests == 1


def test_multi_file_task_edit_readback_and_restart(tmp_path):
    workspace = tmp_path / "project with spaces"
    workspace.mkdir()
    runner = Sandbox(workspace)
    html = "<html>\r\n<style>.card { color: red; }</style>\r\n<body>unchanged</body>\r\n</html>\r\n"
    runner.write("index.html", html)
    runner.write("notes.txt", "keep me\n")
    actions = [("Read", {"path": "index.html"}),
               ("Edit", {"path": "index.html", "old": "color: red", "new": "color: blue"}),
               ("Read", {"path": "index.html"})]
    provider = Proposals(actions)
    settings = Settings(journal_path=str(tmp_path / "task.sqlite3"))
    body = {"conversation_id": "css-task", "tools": [READ, EDIT], "messages": [{"role": "user", "content": "Change only card color"}]}
    edit_id = None
    for step in range(4):
        # Recreate HTTP app and reopen the database between every action.
        with TestClient(create_app(settings, provider=provider)) as client:
            response = client.post("/v1/chat/completions", headers=AUTH, json=body)
            assert response.status_code == 200, response.text
            message = response.json()["choices"][0]["message"]
            body["messages"].append(message)
            if step == 3:
                expected = hashlib.sha256(html.replace("color: red", "color: blue").encode()).hexdigest()
                actual = runner.read("index.html")["sha256"]
                verified = client.post("/v1/operations/" + edit_id + "/verification", headers=AUTH,
                                       json={"conversation_id": "css-task", "expected_sha256": expected, "observed_sha256": actual})
                assert verified.status_code == 200
                assert verified.json()["status"] == "VERIFIED"
                break
            call = message["tool_calls"][0]
            values = json.loads(call["function"]["arguments"])
            if call["function"]["name"] == "Read":
                result = runner.read(values["path"])
            else:
                result = runner.edit(values["path"], values["old"], values["new"])
                edit_id = call["id"]
            body["messages"].append({"role": "tool", "tool_call_id": call["id"], "content": json.dumps(result)})
    assert runner.read("index.html")["content"] == html.replace("color: red", "color: blue")
    assert runner.read("notes.txt")["content"] == "keep me\n"


def test_same_local_call_id_cannot_cross_two_conversations():
    journal = Journal(":memory:")
    try:
        journal.deliver([ToolCall("local-1", "Bash", {}, "schema")], "one")
        with pytest.raises(BridgeError) as exc:
            journal.receive("local-1", "two", "exit_zero")
        assert exc.value.code == "CROSS_CONVERSATION_RECEIPT"
        assert journal.operation("local-1")["status"] == "DISPATCHED"
    finally:
        journal.close()


def test_conversationless_call_is_bound_when_first_receipt_arrives():
    journal = Journal(":memory:")
    try:
        journal.deliver([ToolCall("call", "Bash", {}, "schema")])
        journal.receive("call", "one", "exit_zero")
        with pytest.raises(BridgeError):
            journal.receive("call", "two", "exit_zero")
    finally:
        journal.close()


def test_dispatch_transaction_rolls_back_all_calls_on_duplicate(tmp_path):
    journal = Journal(str(tmp_path / "atomic.sqlite3"))
    try:
        calls = [ToolCall("same", "Read", {}, "schema"), ToolCall("same", "Read", {}, "schema")]
        with pytest.raises(sqlite3.IntegrityError):
            journal.deliver(calls, "conversation", request_key="retry")
        assert journal.operation("same") is None
        journal.ensure_new_turn("retry", "conversation")
    finally:
        journal.close()


def test_structured_runtime_guidance_does_not_depend_on_markers(tmp_path):
    from bridge_x.schemas import ChatRequest
    req = ChatRequest(messages=[{"role": "user", "content": "create"}], tools=[WRITE])
    payload = build_molab_payload(req, [m.model_dump() for m in req.messages],
                                  read_molab_config(save_config(tmp_path)), protocol="structured")
    text = json.dumps(payload)
    assert "JSON" in text and "tool_calls" in text
    assert "@@CALL_V2" not in text and "@@TOOL_CALL" not in text
    assert payload["tools"] == []  # No unproven native capability is invented.


def test_molab_capability_endpoint_reports_fallback_honestly():
    with TestClient(create_app(Settings(provider="molab", journal_path=":memory:"))) as client:
        assert client.get("/v1/capabilities").status_code == 401
        result = client.get("/v1/capabilities", headers=AUTH).json()
        assert result["native_tools"] is False
        assert result["structured_intent"] is True
        assert result["live_verified"] is False


def test_absolute_deadline_cancels_provider_and_does_not_dispatch():
    closed = []
    class Slow:
        async def generate(self, req, messages):
            try:
                await asyncio.sleep(10)
                yield TextDelta("should never arrive")
            finally:
                closed.append(True)
    with TestClient(create_app(Settings(journal_path=":memory:", timeout_s=0.03, heartbeat_s=0.01), provider=Slow())) as client:
        response = client.post("/v1/chat/completions", headers=AUTH,
                               json={"tools": [WRITE], "messages": [{"role": "user"}]})
        assert response.status_code == 504
        assert response.json()["error"]["code"] == "UPSTREAM_DEADLINE"
        assert closed == [True]
        assert client.app.state.journal.db.execute("SELECT count(*) FROM operations").fetchone()[0] == 0


@pytest.mark.parametrize("attempt", [1, 2])
def test_real_http_acceptance_closes_temporary_database(tmp_path, attempt):
    report = tmp_path / "http.json"
    root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["BRIDGEX_PROVIDER"] = "fake"
    result = subprocess.run([sys.executable, str(root / "LOCAL_HTTP_ACCEPTANCE.py"), "--report", str(report)],
                            cwd=root, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["passed"] and data["real_http_server"]
