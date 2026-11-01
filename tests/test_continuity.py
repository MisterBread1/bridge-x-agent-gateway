"""Continuity invariants; scripted wire peers do not certify live model reasoning."""
import json
import pytest
from fastapi.testclient import TestClient
from bridge_x.config import Settings
from bridge_x.gateway import create_app
from bridge_x.molab_native import native_messages
from bridge_x.providers import Finish, TextDelta
from bridge_x.schemas import ChatRequest
from .conftest import BASH
from bridge_x.context import compact
from bridge_x.journal import Journal
from bridge_x.receipts import classify_result
from bridge_x.providers import NativeToolDelta
from bridge_x.tool_models import ToolCall
from bridge_x.errors import BridgeError

AUTH = {"Authorization": "Bearer molab-local"}
ECHO = ('[Completed client tool history: Bash id=call_7d1a72c3f13c4a2c91646a471fbbcb9a; '
        'result follows, no new action.]\n"(Bash completed with no output)"')


def history(count=5):
    messages = [{"role": "user", "content": "Continue the multi-step coding task"}]
    for i in range(count):
        messages += [{"role": "assistant", "tool_calls": [{"id": f"call_{i}", "function": {
            "name": "Bash", "arguments": json.dumps({"command": f"check-{i}"})}}]},
            {"role": "tool", "tool_call_id": f"call_{i}",
             "content": json.dumps({"exit_code": 0, "stdout": ""})}]
    return messages


def test_completed_history_keeps_native_pairs_and_empty_stdout_without_assistant_claims():
    messages = history()
    req = ChatRequest(messages=messages, tools=[BASH])
    result = native_messages(req, messages, 2200)
    parts = [p for m in result for p in m["parts"] if p["type"] == "dynamic-tool"]
    assert len(parts) == 5
    assert [p["toolCallId"] for p in parts] == [f"call_{i}" for i in range(5)]
    assert all(p["state"] == "output-available" and p["output"] == {"exit_code": 0, "stdout": ""} for p in parts)
    assert all(p["input"] == {"command": f"check-{i}"} for i, p in enumerate(parts))
    assert messages == history()  # serializer cannot rewrite the client's transcript


def test_native_duplicate_receipt_and_later_confirmed_exit_stay_one_paired_result():
    messages = history(1)
    confirmed = messages[-1].copy()
    messages[-1]["content"] = "(Bash completed with no output)"
    messages.extend([confirmed, confirmed.copy()])
    req = ChatRequest(messages=messages, tools=[BASH])
    serialized = native_messages(req, messages, 2200)
    parts = [p for m in serialized for p in m["parts"] if p["type"] == "dynamic-tool"]
    assert len(parts) == 1 and parts[0]["output"] == {"exit_code": 0, "stdout": ""}
    assert not any("Unpaired" in p.get("text", "") for m in serialized for p in m["parts"])


def test_native_conflicting_confirmed_receipts_fail_closed_and_keep_original_user_goal():
    messages = history(1)
    messages[0]["content"] = ECHO  # the user may ask about this exact text
    req = ChatRequest(messages=messages, tools=[BASH])
    assert any(p.get("text") == ECHO for m in native_messages(req, messages, 2200) for p in m["parts"])
    messages.append({**messages[-1], "content": '{"exit_code":9}'})
    with pytest.raises(BridgeError) as error:
        native_messages(req, messages, 2200)
    assert error.value.code == "TOOL_RECEIPT_CONFLICT"


@pytest.mark.parametrize("streaming", [False, True])
def test_reported_bash_archive_echo_is_a_recoverable_protocol_error_not_stop(streaming):
    class EchoPeer:
        async def generate(self, req, messages):
            yield TextDelta(ECHO)
            yield Finish("stop")
    with TestClient(create_app(Settings(provider="molab", molab_tool_mode="native", journal_path=":memory:", timeout_s=1, heartbeat_s=0.05), provider=EchoPeer())) as client:
        response = client.post("/v1/chat/completions", headers=AUTH,
                               json={"messages": history(), "tools": [BASH], "stream": streaming})
        if streaming:
            assert "event: error" in response.text and "data: [DONE]" not in response.text
            assert '"finish_reason":"stop"' not in response.text
        else:
            assert response.status_code == 502
        assert "UPSTREAM_HISTORY_ECHO" in response.text
        assert client.app.state.journal.db.execute("SELECT count(*) FROM operations WHERE source='gateway'").fetchone()[0] == 0


@pytest.mark.parametrize("streaming", [False, True])
def test_eight_turn_coding_task_retains_receipts_across_every_database_reopen(streaming):
    from tools.continuity_acceptance import run_acceptance
    result = run_acceptance(streaming)
    assert result["unique_tools"] == 7 and result["turns"] == 8


@pytest.mark.parametrize("value,kind,state", [
    ({"exit_code": 0, "stdout": ""}, "exit_zero", "EXECUTED"),
    ({"exit_code": 7, "stdout": ""}, "exit_nonzero", "FAILED"),
    ("(Bash completed with no output)", "unknown", "ACKNOWLEDGED"),
    ({"cancelled": True, "exit_code": 0}, "cancelled", "CANCELLED"),
    ({"timed_out": True, "exit_code": 0}, "timed_out", "TIMED_OUT"),
    ({"stdout": ""}, "unknown", "ACKNOWLEDGED"),
    ({"success": True, "stdout": ""}, "unknown", "ACKNOWLEDGED"),
])
def test_shell_outcomes_never_infer_exit_code_from_empty_output(tmp_path, value, kind, state):
    database = str(tmp_path / "receipts.sqlite3")
    journal = Journal(database)
    journal.deliver([ToolCall("bash", "Bash", {"command": "check"}, "schema")], "task")
    message = {"role": "tool", "tool_call_id": "bash", "content": json.dumps(value)}
    assert classify_result({**message, "name": "Bash"}) == kind
    journal.reconcile_client_history([message], "task", classify_result)
    journal.close()
    journal = Journal(database)
    try:
        journal.reconcile_client_history([message], "task", classify_result)
        operation = journal.operation("bash")
        assert operation["status"] == state and operation["result_kind"] == kind
        assert operation["events"].count("ACKNOWLEDGED") == 1
    finally:
        journal.close()


def test_unknown_shell_cannot_be_repeated_after_restart_but_readback_is_allowed(tmp_path):
    path = str(tmp_path / "unknown.sqlite3")
    journal = Journal(path)
    journal.deliver([ToolCall("old", "Bash", {"command": "mutation"}, "schema")], "task")
    journal.receive("old", "task", "unknown")
    journal.close()
    journal = Journal(path)
    try:
        with pytest.raises(BridgeError, match="uncertain outcome"):
            journal.deliver([ToolCall("repeat", "Bash", {"command": "mutation"}, "schema")], "task")
        assert journal.operation("repeat") is None
        journal.deliver([ToolCall("read", "Read", {"path": "result.txt"}, "schema")], "task")
        journal.receive("read", "task", "reported_success")
        assert journal.operation("old")["status"] == "ACKNOWLEDGED"
        # Checking a file is not evidence of the original shell exit status.
        journal.receive("old", "task", "exit_zero")
        assert journal.operation("old")["status"] == "EXECUTED"
        journal.deliver([ToolCall("allowed", "Bash", {"command": "mutation"}, "schema")], "task")
    finally:
        journal.close()


def test_schema_three_migration_retains_pending_guards_and_existing_events(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.sqlite3")
    journal = Journal(path)
    journal.deliver([ToolCall("old", "Bash", {"command": "mutation"}, "schema")], "task", request_key="old-key")
    journal.close()
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE operations DROP COLUMN argument_hash")
        for column in ("tool_type", "outcome", "finish_reason", "agent_state", "pending_operations", "compacted_exchanges", "compacted_outputs"):
            db.execute("ALTER TABLE diagnostics DROP COLUMN " + column)
        db.execute("PRAGMA user_version=3")
    journal = Journal(path)
    try:
        assert journal.db.execute("PRAGMA user_version").fetchone()[0] == 5
        assert journal.operation("old")["events"] == ["PROPOSED", "VALIDATED", "DISPATCHED"]
        with pytest.raises(BridgeError):
            journal.ensure_new_turn("old-key", "task")
        journal.receive("old", "task", "unknown")
        with pytest.raises(BridgeError):
            journal.deliver([ToolCall("new", "Bash", {"command": "mutation"}, "schema")], "task")
    finally:
        journal.close()


def test_compaction_preserves_goal_latest_empty_bash_receipt_and_pending_arguments():
    messages = history(40)
    for item in messages:
        if item.get("role") == "tool" and item["tool_call_id"] != "call_39":
            item["content"] = json.dumps({"exit_code": 0, "stdout": "x" * 4000})
    pending = {"role": "assistant", "tool_calls": [{"id": "pending", "function": {
        "name": "Bash", "arguments": '{"command":"do not truncate"}'}}]}
    messages.append(pending)
    journal = Journal(":memory:")
    try:
        journal.reconcile_client_history(messages, "task", classify_result)
        bounded, stats = compact(messages, 7000)
        assert stats["archived_completed_exchanges"] > 0
        assert bounded[0] == messages[0] and bounded[-1] == pending
        assert next(m for m in bounded if m.get("tool_call_id") == "call_39") == messages[-2]
        for item in bounded:
            if item.get("role") == "tool":
                assert json.loads(item["content"])["exit_code"] == 0
        assert journal.db.execute("SELECT count(*) FROM operations WHERE state='EXECUTED'").fetchone()[0] == 40
        parts = [p for m in native_messages(ChatRequest(messages=bounded, tools=[BASH]), bounded, 2200) for p in m["parts"] if p["type"] == "dynamic-tool"]
        assert parts[-1]["state"] == "input-available" and parts[-1]["input"] == {"command": "do not truncate"}
    finally:
        journal.close()


@pytest.mark.parametrize("streaming", [False, True])
def test_valid_final_and_intermediate_prose_are_not_forced_into_tool_loops(streaming):
    class Prose:
        def __init__(self): self.requests = 0
        async def generate(self, req, messages):
            self.requests += 1
            yield TextDelta("The requested change is ready.")
            yield Finish("stop")
    provider = Prose()
    with TestClient(create_app(Settings(journal_path=":memory:"), provider=provider)) as client:
        from tools.continuity_acceptance import decode
        result = decode(client.post("/v1/chat/completions", headers=AUTH,
            json={"messages": history(), "tools": [BASH], "stream": streaming}), streaming)
        assert result["choices"][0]["finish_reason"] == "stop"
        assert result["x_bridge_x"]["agent_state"] == "model_stopped_unverified"
        assert result["x_bridge_x"]["task_completion_verified"] is False
        assert provider.requests == 1


@pytest.mark.parametrize("streaming", [False, True])
def test_unknown_receipt_is_visible_in_terminal_status(streaming):
    class Prose:
        async def generate(self, req, messages):
            yield TextDelta("Inspect the actual state before continuing.")
            yield Finish("stop")
    messages = history(1)
    messages[-1]["content"] = "(Bash completed with no output)"
    with TestClient(create_app(Settings(journal_path=":memory:"), provider=Prose())) as client:
        from tools.continuity_acceptance import decode
        result = decode(client.post("/v1/chat/completions", headers=AUTH,
            json={"messages": messages, "tools": [BASH], "stream": streaming}), streaming)
        assert result["x_bridge_x"]["agent_state"] == "execution_unknown"
        assert result["x_bridge_x"]["unknown_outcomes"] == 1


@pytest.mark.parametrize("reason", ["length", "unexpected", "error"])
@pytest.mark.parametrize("streaming", [False, True])
def test_terminal_failures_never_authorize_tools_or_success(reason, streaming):
    class Broken:
        async def generate(self, req, messages):
            yield NativeToolDelta(0, "upstream", "Bash", '{"command":"unsafe"}')
            yield Finish(reason)
    with TestClient(create_app(Settings(journal_path=":memory:"), provider=Broken())) as client:
        response = client.post("/v1/chat/completions", headers=AUTH,
            json={"messages": [{"role": "user", "content": "run"}], "tools": [BASH], "stream": streaming})
        assert "UPSTREAM_" in response.text and "data: [DONE]" not in response.text
        assert client.app.state.journal.db.execute("SELECT count(*) FROM operations").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_client_stream_cancellation_closes_provider_and_records_recovery_state():
    import asyncio
    entered, closed, disconnected = asyncio.Event(), asyncio.Event(), asyncio.Event()
    class Slow:
        async def generate(self, req, messages):
            entered.set()
            try:
                await asyncio.sleep(20)
                yield Finish("stop")
            finally:
                closed.set()
    journal = Journal(":memory:")
    app = create_app(Settings(journal_path=":memory:", heartbeat_s=0.01), provider=Slow(), journal=journal)
    sent = []
    body = json.dumps({"messages": [{"role": "user", "content": "work"}], "tools": [BASH], "stream": True}).encode()
    received_body = False
    async def receive():
        nonlocal received_body
        if not received_body:
            received_body = True
            return {"type": "http.request", "body": body, "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}
    async def send(message):
        sent.append(message)
    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.0"}, "http_version": "1.1",
             "method": "POST", "scheme": "http", "path": "/v1/chat/completions", "raw_path": b"/v1/chat/completions",
             "query_string": b"", "root_path": "", "headers": [(b"authorization", b"Bearer molab-local"), (b"content-type", b"application/json")],
             "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 2)}
    task = asyncio.create_task(app(scope, receive, send))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        disconnected.set()
        await asyncio.wait_for(task, 2)
        assert closed.is_set()
        assert not any(b"[DONE]" in m.get("body", b"") for m in sent)
        assert journal.db.execute("SELECT count(*) FROM operations").fetchone()[0] == 0
        assert any(item["event"] == "client_cancelled" for item in journal.safe_report())
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        journal.close()
