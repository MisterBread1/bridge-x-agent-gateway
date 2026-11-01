"""Regressions for ZCode memory/foreground overlap and serial native batches."""
import asyncio
import json
import sqlite3
import hashlib
import pytest
from fastapi.testclient import TestClient
from bridge_x.config import Settings
from bridge_x.coordinator import ToolCoordinator
from bridge_x.errors import BridgeError
from bridge_x.execution_scope import resolve_execution_scope
from bridge_x.gateway import create_app
from bridge_x.journal import Journal
from bridge_x.providers import NativeToolDelta, Finish
from bridge_x.schemas import ChatRequest
from bridge_x.tool_models import ToolCall
from .conftest import WRITE, BASH

AUTH = {"Authorization": "Bearer molab-local", "x-session-id": "same-zcode-session"}


class NativeBatch:
    def __init__(self):
        self.count = 0

    async def generate(self, req, messages):
        self.count += 1
        if not any(m.get("role") == "tool" for m in messages):
            yield NativeToolDelta(0, "upstream-1", "Write", '{"path":"a","content":"first"}')
            yield NativeToolDelta(1, "upstream-2", "Bash", '{"command":"stale proposal must not be queued"}')
        else:
            yield NativeToolDelta(0, "upstream-next", "Bash", '{"command":"replanned after receipt"}')
        yield Finish("tool_calls")


@pytest.mark.parametrize("stream", [False, True])
def test_native_batch_is_delivered_as_one_action_when_parallel_is_false(stream):
    settings = Settings(provider="molab", molab_tool_mode="native", journal_path=":memory:")
    with TestClient(create_app(settings, provider=NativeBatch())) as client:
        response = client.post("/v1/chat/completions", headers=AUTH, json={
            "messages": [{"role": "user", "content": "do it"}], "tools": [WRITE, BASH], "stream": stream})
        assert response.status_code == 200
        if stream:
            assert '"name":"Write"' in response.text
            assert '"name":"Bash"' not in response.text
            assert "data: [DONE]" in response.text and "event: error" not in response.text
        else:
            calls = response.json()["choices"][0]["message"]["tool_calls"]
            assert len(calls) == 1 and calls[0]["function"]["name"] == "Write"
        rows = client.app.state.journal.db.execute("SELECT name FROM operations").fetchall()
        assert rows == [("Write",)]


def test_unissued_later_native_proposal_is_replanned_after_real_receipt():
    provider = NativeBatch()
    with TestClient(create_app(Settings(provider="molab", molab_tool_mode="native", journal_path=":memory:"), provider=provider)) as client:
        body = {"messages": [{"role": "user", "content": "task"}], "tools": [WRITE, BASH]}
        first = client.post("/v1/chat/completions", headers=AUTH, json=body)
        message = first.json()["choices"][0]["message"]
        call = message["tool_calls"][0]
        body["messages"] += [message, {"role": "tool", "tool_call_id": call["id"], "content": '{"success":true}'}]
        second = client.post("/v1/chat/completions", headers=AUTH, json=body)
        assert second.status_code == 200
        next_call = second.json()["choices"][0]["message"]["tool_calls"][0]
        assert json.loads(next_call["function"]["arguments"])["command"] == "replanned after receipt"
        assert provider.count == 2


def test_explicit_parallel_permission_preserves_all_native_calls():
    with TestClient(create_app(Settings(provider="molab", molab_tool_mode="native", journal_path=":memory:"), provider=NativeBatch())) as client:
        response = client.post("/v1/chat/completions", headers=AUTH, json={
            "messages": [{"role": "user", "content": "task"}], "tools": [WRITE, BASH], "parallel_tool_calls": True})
        assert len(response.json()["choices"][0]["message"]["tool_calls"]) == 2


def test_background_scope_is_stable_through_its_tool_loop_and_changes_for_new_job():
    initial = [{"role": "user", "content": "foreground goal"}, {"role": "user", "content": "memory job one"}]
    scope = resolve_execution_scope(initial, "project_memory_extract")
    continued = initial + [{"role": "assistant", "tool_calls": [{"id": "x"}]}, {"role": "tool", "content": "result"}]
    assert resolve_execution_scope(continued, "project_memory_extract") == scope
    assert resolve_execution_scope(initial + [{"role": "user", "content": "memory job two"}], "project_memory_extract") != scope
    assert resolve_execution_scope(initial) == "main_turn"


def test_background_pending_bash_does_not_block_foreground_but_still_blocks_its_own_branch():
    journal = Journal(":memory:")
    try:
        scope = "project_memory_extract:one"
        journal.deliver([ToolCall("pending-memory-bash", "Bash", {}, "schema")], "session", request_key="background-request", execution_scope=scope)
        journal.ensure_new_turn("foreground-request", "session", execution_scope="main_turn")
        with pytest.raises(BridgeError) as exc:
            journal.ensure_new_turn("background-continuation", "session", execution_scope=scope)
        assert exc.value.code == "EXECUTION_UNKNOWN"
        assert journal.operation("pending-memory-bash")["status"] == "DISPATCHED"
    finally:
        journal.close()


def test_foreground_pending_bash_is_not_misclassified_as_background():
    journal = Journal(":memory:")
    try:
        journal.deliver([ToolCall("pending-main-bash", "Bash", {}, "schema")], "session", request_key="original")
        with pytest.raises(BridgeError):
            journal.ensure_new_turn("new-main", "session")
        journal.ensure_new_turn("memory-job", "session", execution_scope="project_memory_extract:two")
    finally:
        journal.close()


def test_shared_foreground_history_is_accepted_in_background_without_cross_conversation_error():
    journal = Journal(":memory:")
    try:
        journal.deliver([ToolCall("shared", "Write", {}, "schema")], "session")
        journal.receive("shared", "session", "reported_success")
        history = [{"role": "assistant", "tool_calls": [{"id": "shared", "function": {"name": "Write", "arguments": "{}"}}]},
                   {"role": "tool", "tool_call_id": "shared", "content": '{"success":true}'},
                   {"role": "user", "content": "memory task"}]
        request = ChatRequest(messages=history, tools=[WRITE], conversation_id="session")
        turn = ToolCoordinator(journal, 220000).prepare(request, history, "project_memory_extract:new")
        assert turn.receipts["duplicates"] == 1
        assert turn.conversation_id == "session"
    finally:
        journal.close()


def test_completed_background_receipt_does_not_release_unrelated_foreground_pending_call():
    journal = Journal(":memory:")
    try:
        journal.deliver([ToolCall("main", "Bash", {}, "schema")], "session")
        journal.deliver([ToolCall("memory", "Read", {}, "schema")], "session", execution_scope="project_memory_extract:one")
        journal.receive("memory", "session", "unknown")
        with pytest.raises(BridgeError):
            journal.ensure_new_turn("next", "session")
    finally:
        journal.close()


def test_sdk_transport_option_changes_do_not_bypass_exact_request_guard():
    journal = Journal(":memory:")
    try:
        coordinator = ToolCoordinator(journal, 220000)
        first = ChatRequest(messages=[{"role": "user", "content": "task"}], tools=[WRITE], conversation_id="session", thinking={"type": "enabled"})
        messages = [m.model_dump() for m in first.messages]
        turn = coordinator.prepare(first, messages)
        coordinator.dispatch(turn, [ToolCall("operation", "Write", {}, "schema")])
        second = first.model_copy(update={"thinking": {"type": "disabled"}, "stream_options": {"include_usage": True}})
        with pytest.raises(BridgeError):
            coordinator.prepare(second, messages)
    finally:
        journal.close()


def test_real_zcode_headers_separate_background_from_foreground_pending_operations():
    class Single:
        async def generate(self, req, messages):
            yield NativeToolDelta(0, "native", "Bash", '{"command":"read-only background check"}')
            yield Finish("tool_calls")
    with TestClient(create_app(Settings(provider="molab", molab_tool_mode="native", journal_path=":memory:"), provider=Single())) as client:
        memory_body = {"messages": [{"role": "user", "content": "extract memory"}], "tools": [BASH]}
        memory = client.post("/v1/chat/completions", headers={**AUTH, "x-zcode-query-source": "project_memory_extract"}, json=memory_body)
        assert memory.status_code == 200
        main_body = {"messages": [{"role": "user", "content": "edit project"}], "tools": [BASH]}
        main = client.post("/v1/chat/completions", headers={**AUTH, "x-zcode-query-source": "main_turn"}, json=main_body)
        assert main.status_code == 200
        rows = client.app.state.journal.db.execute("SELECT execution_scope FROM operations").fetchall()
        assert len(rows) == 2 and "main_turn" in {r[0] for r in rows}
        assert any(r[0].startswith("project_memory_extract:") for r in rows)


def test_scope_survives_restart_and_original_pending_operations_remain_protected(tmp_path):
    database = str(tmp_path / "state.sqlite3")
    journal = Journal(database)
    journal.deliver([ToolCall("memory", "Read", {}, "schema")], "session", execution_scope="project_memory_extract:one")
    journal.close()
    journal = Journal(database)
    try:
        journal.ensure_new_turn("main", "session")
        assert journal.operation("memory")["execution_scope"] == "project_memory_extract:one"
        assert journal.db.execute("PRAGMA user_version").fetchone()[0] == 5
        with pytest.raises(BridgeError):
            journal.ensure_new_turn("same-branch", "session", execution_scope="project_memory_extract:one")
    finally:
        journal.close()


def test_old_fingerprint_still_prevents_replay_of_a_completed_side_effect():
    journal = Journal(":memory:")
    try:
        req = ChatRequest(messages=[{"role": "user", "content": "run once"}], tools=[BASH], conversation_id="session")
        old_basis = req.model_dump(exclude={"stream"}, exclude_none=True)
        old_key = hashlib.sha256(json.dumps(old_basis, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        journal.deliver([ToolCall("old-operation", "Bash", {}, "schema")], "session", request_key=old_key)
        journal.receive("old-operation", "session", "exit_zero")
        with pytest.raises(BridgeError) as exc:
            ToolCoordinator(journal, 220000).prepare(req, [m.model_dump() for m in req.messages])
        assert exc.value.code == "EXECUTION_UNKNOWN"
    finally:
        journal.close()
