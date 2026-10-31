import json
import pytest
from bridge_x.context import compact
from bridge_x.journal import Journal
from bridge_x.errors import BridgeError
from bridge_x.tools import ToolCall


def test_journal_deliver_receipt_duplicate(tmp_path):
    j = Journal(str(tmp_path / "state.db"))
    c = ToolCall("call_1", "Write", {"path": "f", "content": "x"}, "hash")
    j.deliver([c], "conversation_A")
    assert j.status("call_1") == "OFFERED_UNCONFIRMED"
    assert j.receive("call_1", "conversation_A", "reported_success") is True
    assert j.receive("call_1", "conversation_A") is False
    assert j.status("call_1") == "RESULT_RECEIVED"
    j.close()


def test_journal_cross_conversation(tmp_path):
    j = Journal(str(tmp_path / "state.db"))
    j.deliver([ToolCall("c1", "Write", {}, "hash")], "conversation_A")
    with pytest.raises(BridgeError) as exc:
        j.receive("c1", "conversation_B")
    assert exc.value.code == "CROSS_CONVERSATION_RECEIPT"
    j.close()


def test_journal_reopen_persistent(tmp_path):
    p = str(tmp_path / "state.db")
    j = Journal(p)
    j.deliver([ToolCall("c2", "Bash", {}, "hash")])
    j.close()
    j = Journal(p)
    assert j.status("c2") == "OFFERED_UNCONFIRMED"
    j.close()


def test_unknown_receipt_rejected():
    j = Journal(":memory:")
    with pytest.raises(BridgeError) as exc:
        j.receive("not-real")
    assert exc.value.code == "ORPHAN_TOOL_RESULT"
    j.close()


def test_context_compaction_preserves_first_task_recent_and_ids():
    huge = "T" * 60_000
    items = [{"role": "user", "content": "Make important project"},
             {"role": "assistant", "content": None, "tool_calls": [{"id": "call_abc", "function": {"arguments": '{"critical":true}'}}]},
             {"role": "tool", "tool_call_id": "call_abc", "content": huge}]
    items.extend([{"role": "assistant", "content": "ok"}] * 5)
    compacted, metrics = compact(items, max_context_chars=40_000)
    assert compacted[0] == items[0]
    assert compacted[1]["tool_calls"] == items[1]["tool_calls"]
    assert compacted[2]["tool_call_id"] == "call_abc"
    assert compacted[2]["content"].endswith("T" * 20)
    assert metrics["after_chars"] < metrics["before_chars"]
    assert items[2]["content"] == huge  # no in-place mutation


def test_recent_tool_output_not_silently_truncated():
    items = [{"role": "user", "content": "goal"}, {"role": "tool", "tool_call_id": "c", "content": "x" * 10000}]
    with pytest.raises(BridgeError) as exc:
        compact(items, max_context_chars=100)
    assert exc.value.code == "CONTEXT_BUDGET_EXCEEDED"


def test_reconcile_receipt_recovers_after_journal_replaced():
    j = Journal(":memory:")
    payload = [
        {"role": "user", "content": "Make file"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "call_old", "type": "function", "function": {"name": "Write", "arguments": '{"path":"f","content":"x"}'}}]},
        {"role": "tool", "tool_call_id": "call_old", "content": '{"success":true}'},
    ]
    stats = j.reconcile_client_history(payload, "conversation", lambda _: "reported_success")
    assert stats == {"recovered": 1, "unmatched": 0, "receipts": 1, "duplicates": 0}
    assert j.status("call_old") == "RESULT_RECEIVED"
    again = j.reconcile_client_history(payload, "conversation", lambda _: "reported_success")
    assert again["duplicates"] == 1 and again["recovered"] == 0
    j.close()


def test_reconcile_unmatched_upgrades_when_parent_arrives_later():
    j = Journal(":memory:")
    lone = [{"role": "tool", "tool_call_id": "call_late", "content": "output"}]
    assert j.reconcile_client_history(lone)["unmatched"] == 1
    assert j.status("call_late") == "UNVERIFIED_CLIENT_RESULT"
    parent = [{"role": "assistant", "tool_calls": [{"id": "call_late", "function": {"name": "Bash", "arguments": '{"command":"echo ok"}'}}]}] + lone
    j.reconcile_client_history(parent)
    assert j.status("call_late") == "RESULT_RECEIVED"
    j.close()


def test_reconcile_rejects_cross_conversation_or_renamed_call():
    j = Journal(":memory:")
    j.deliver([ToolCall("call_id", "Bash", {}, "hash")], "conversation_A")
    history = [{"role": "assistant", "tool_calls": [{"id": "call_id", "function": {"name": "Bash", "arguments": "{}"}}]},
               {"role": "tool", "tool_call_id": "call_id", "content": "ok"}]
    with pytest.raises(BridgeError) as err:
        j.reconcile_client_history(history, "conversation_B")
    assert err.value.code == "CROSS_CONVERSATION_RECEIPT"
    history[0]["tool_calls"][0]["function"]["name"] = "Write"
    with pytest.raises(BridgeError) as err:
        j.reconcile_client_history(history, "conversation_A")
    assert err.value.code == "TOOL_CALL_ID_CONFLICT"
    j.close()


def test_reconcile_respects_call_before_result_order():
    j = Journal(":memory:")
    history = [{"role": "tool", "tool_call_id": "call_bad_order", "content": "done"},
               {"role": "assistant", "tool_calls": [{"id": "call_bad_order", "function": {"name": "Write", "arguments": "{}"}}]}]
    assert j.reconcile_client_history(history)["unmatched"] == 1
    assert j.status("call_bad_order") == "UNVERIFIED_CLIENT_RESULT"
    j.close()


def test_repeated_unmatched_receipt_is_idempotent():
    j = Journal(":memory:")
    history = [{"role": "tool", "tool_call_id": "old_unpaired", "content": "stdout"}]
    first = j.reconcile_client_history(history)
    second = j.reconcile_client_history(history)
    assert first["unmatched"] == 1
    assert second == {"recovered": 0, "unmatched": 0, "receipts": 0, "duplicates": 1}
    assert j.status("old_unpaired") == "UNVERIFIED_CLIENT_RESULT"
    j.close()
