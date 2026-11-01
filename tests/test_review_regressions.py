"""The nine independent audit reproductions, now asserted as safety invariants."""
import asyncio
import json
import sqlite3
import time
from unittest.mock import patch
import httpx
import pytest
from fastapi.testclient import TestClient
from bridge_x.config import Settings
from bridge_x.errors import BridgeError
from bridge_x.gateway import create_app
from bridge_x.journal import Journal
from bridge_x.molab_provider import MolabProvider
from bridge_x.receipts import classify_result
from bridge_x.tool_models import ToolCall
from .conftest import BASH
from .test_continuity import AUTH, history
from .test_molab_integration import save_config, response_stream


def test_unpaired_generic_success_never_certifies_shell_without_exit():
    journal = Journal(":memory:")
    try:
        messages = history(1)
        messages[-1]["content"] = '{"success":true,"stdout":""}'
        journal.reconcile_client_history([messages[-1]], "task", classify_result)
        journal.reconcile_client_history(messages, "task", classify_result)
        operation = journal.operation("call_0")
        assert operation["status"] == "ACKNOWLEDGED" and operation["result_kind"] == "unknown"
    finally:
        journal.close()


def test_conflicting_confirmed_receipt_across_requests_is_rejected_atomically():
    journal = Journal(":memory:")
    try:
        messages = history(2)
        journal.reconcile_client_history(messages, "task", classify_result)
        messages[-1]["content"] = '{"exit_code":7}'
        with pytest.raises(BridgeError) as error:
            journal.reconcile_client_history(messages, "task", classify_result)
        assert error.value.code == "TOOL_RECEIPT_CONFLICT"
        assert journal.operation("call_1")["result_kind"] == "exit_zero"
    finally:
        journal.close()


def test_missing_journal_recovers_open_history_and_blocks_new_generation():
    class Unexpected:
        async def generate(self, req, messages):
            pytest.fail("pending historical mutation reached generation")
            yield
    with TestClient(create_app(Settings(journal_path=":memory:"), provider=Unexpected())) as client:
        messages = history(1)[:-1]
        response = client.post("/v1/chat/completions", headers=AUTH, json={"messages": messages, "tools": [BASH], "conversation_id": "task"})
        assert response.status_code == 409 and response.json()["error"]["code"] == "EXECUTION_UNKNOWN"
        assert client.app.state.journal.operation("call_0")["status"] == "DISPATCHED"


@pytest.mark.parametrize("kind", ["cancelled", "timed_out", "unknown"])
def test_uncertain_mutation_has_explicit_state_check_recovery_without_fake_exit(kind, tmp_path):
    path = str(tmp_path / "recovery.sqlite3")
    journal = Journal(path)
    journal.deliver([ToolCall("old", "Bash", {"command": "fixture"}, "schema")], "task")
    journal.receive("old", "task", kind)
    with pytest.raises(BridgeError):
        journal.verify("old", "task", "a" * 64, "a" * 64)
    journal.verify("old", "task", "a" * 64, "a" * 64, execution_stopped=True)
    journal.close()
    journal = Journal(path)
    try:
        op = journal.operation("old")
        assert op["status"] == "RESOLVED_BY_CHECK" and op["result_kind"] == kind
        journal.deliver([ToolCall("next", "Bash", {"command": "fixture"}, "schema")], "task")
    finally:
        journal.close()


@pytest.mark.parametrize("kind", ["cancelled", "timed_out"])
def test_real_later_exit_resolves_cancellation_and_replayed_transcript_is_idempotent(kind):
    journal = Journal(":memory:")
    try:
        messages = history(1)
        actual = messages[-1].copy()
        messages[-1]["content"] = json.dumps({"cancelled" if kind == "cancelled" else "timed_out": True})
        journal.reconcile_client_history(messages, "task", classify_result)
        messages.append(actual)
        journal.reconcile_client_history(messages, "task", classify_result)
        journal.reconcile_client_history(messages, "task", classify_result)
        assert journal.operation("call_0")["status"] == "EXECUTED"
    finally:
        journal.close()


def test_anonymous_unrelated_plain_chat_has_no_other_client_outcomes():
    journal = Journal(":memory:")
    journal.deliver([ToolCall("other", "Bash", {}, "schema")])
    journal.receive("other", result_kind="unknown")
    with TestClient(create_app(Settings(journal_path=":memory:"), journal=journal)) as client:
        response = client.post("/v1/chat/completions", headers=AUTH, json={"messages": [{"role": "user", "content": "hello"}]})
        assert response.json()["x_bridge_x"]["unknown_outcomes"] == 0


def test_runtime_gone_invalidates_current_readiness(monkeypatch, tmp_path):
    original = httpx.AsyncClient
    calls = []
    def upstream(request):
        calls.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=response_stream({"type": "finish", "finishReason": "stop"})) if len(calls) == 1 else httpx.Response(410)
    settings = Settings(provider="molab", molab_tool_mode="native", journal_path=":memory:", molab_config_path=save_config(tmp_path))
    with patch("httpx.AsyncClient", lambda **kw: original(transport=httpx.MockTransport(upstream), **kw)):
        with TestClient(create_app(settings, provider=MolabProvider(settings))) as client:
            body = {"messages": [{"role": "user", "content": "fixture"}]}
            assert client.post("/v1/chat/completions", headers=AUTH, json=body).status_code == 200
            assert client.get("/ready").json()["ready"] is True
            assert client.post("/v1/chat/completions", headers=AUTH, json=body).status_code == 410
            assert client.get("/ready").json()["ready"] is False


def test_future_schema_is_not_modified_and_operation_events_use_index(tmp_path):
    path = str(tmp_path / "future.sqlite3")
    journal = Journal(path)
    plan = journal.db.execute("EXPLAIN QUERY PLAN SELECT state FROM operation_events WHERE call_id=? ORDER BY seq", ("x",)).fetchall()
    assert any("operation_events_call" in row[3] for row in plan)
    journal.db.execute("PRAGMA user_version=99")
    journal.close()
    with pytest.raises(BridgeError) as error:
        Journal(path)
    assert error.value.code == "JOURNAL_NEWER_SCHEMA"
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 99


def test_hundred_duplicate_receipts_have_zero_updates_and_one_transaction():
    journal = Journal(":memory:")
    try:
        messages = history(100)
        journal.reconcile_client_history(messages, "task", classify_result)
        sql = []
        journal.db.set_trace_callback(sql.append)
        stats = journal.reconcile_client_history(messages, "task", classify_result)
        journal.db.set_trace_callback(None)
        assert stats["duplicates"] == 100
        assert not any(row.lstrip().upper().startswith("UPDATE ") for row in sql)
        assert sum(row == "COMMIT" for row in sql) == 1
    finally:
        journal.close()


@pytest.mark.asyncio
async def test_busy_sqlite_keeps_health_responsive_and_returns_typed_storage_error(tmp_path):
    path = str(tmp_path / "locked.sqlite3")
    journal = Journal(path)
    journal.db.execute("PRAGMA busy_timeout=250")
    blocker = sqlite3.connect(path)
    blocker.execute("BEGIN IMMEDIATE")
    app = create_app(Settings(journal_path=path), journal=journal)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fixture") as client:
            task = asyncio.create_task(client.post("/v1/chat/completions", headers=AUTH, json={"messages": [{"role": "user"}]}))
            await asyncio.sleep(0.02)
            started = time.monotonic()
            health = await client.get("/health")
            assert health.status_code == 200 and time.monotonic() - started < 0.15
            response = await task
            assert response.status_code == 503 and response.json()["error"]["code"] == "JOURNAL_BUSY"
    finally:
        blocker.rollback()
        blocker.close()
        await app.state.storage.close()
