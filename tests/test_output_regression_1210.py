"""V12.10: real provider-level regression tests with a mocked Molab transport.

Never contacts a live runtime or uses customer credentials.
"""
import json
import httpx
from fastapi.testclient import TestClient
from bridge_x.config import Settings
from bridge_x.gateway import create_app
from bridge_x.molab_provider import _tool_prompt, MolabProvider, decode_molab_event
from bridge_x.schemas import ChatRequest
from .conftest import WRITE, BASH
from .test_molab_integration import save_config, mock_molab, response_stream
from .test_output_budget126 import READ, EDIT

AUTH = {"Authorization": "Bearer molab-local"}


def _chat(messages=None, tools=None, stream=False):
    return {"model": "molab-glm", "messages": messages or [{"role": "user", "content": "Улучши существующий HTML файл"}],
            "tools": tools if tools is not None else [WRITE, READ, EDIT, BASH], "stream": stream}


def _guide(payload):
    return payload["messages"][0]["parts"][0]["text"]


def test_stage_aware_edit_does_not_list_every_tool_or_force_massive_html():
    extra = [{"type": "function", "function": {
        "name": "ExtraTool" + str(i), "parameters": {"type": "object", "properties": {"a": {"type": "string"}}}
    }} for i in range(51)]
    req = ChatRequest.model_validate(_chat(tools=[WRITE, READ, EDIT, BASH] + extra))
    h = _tool_prompt(req, [m.model_dump(exclude_none=True) for m in req.messages], 2200)
    assert h.index("Read: ") < h.index("Edit: ")
    assert "Do not paste whole existing files" in h
    assert "2200 characters" in h
    assert "(+52 other declared tools, deferred)" in h
    assert "ExtraTool50" not in h
    assert len(h.encode("utf-8")) < 3500


def test_forced_tool_is_in_focused_subset_even_if_not_a_standard_tool():
    tools = [WRITE, READ, EDIT, BASH] + [{"type": "function", "function": {
        "name": "SpecialTool", "parameters": {"type": "object", "properties": {"flag": {"type": "boolean"}}}
    }}]
    payload = _chat(tools=tools)
    payload["tool_choice"] = {"type": "function", "function": {"name": "SpecialTool"}}
    req = ChatRequest.model_validate(payload)
    h = _tool_prompt(req, [m.model_dump(exclude_none=True) for m in req.messages], 2200)
    assert "SpecialTool: " in h
    assert '"flag"' in h


def test_output_limit_adapts_only_when_client_retries_same_request(monkeypatch, tmp_path):
    calls = []
    text = '@@CALL_V2 Write\n@@FIELD path\nagent_check.py\n@@FIELD content\nprint(2 + 2)\n@@END_CALL'
    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        if len(calls) <= 2:
            # A generation that was aborted by the server after partial text.
            body = response_stream({"type": "text-delta", "delta": "@@CALL_V2 Write\n@@FIELD content\n" + "A" * 250},
                                   {"type": "finish", "finishReason": "length"})
        else:
            body = response_stream({"type": "text-delta", "delta": text},
                                   {"type": "finish", "finishReason": "stop"})
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)
    mock_molab(monkeypatch, handler)
    settings = Settings(provider="molab", molab_config_path=save_config(tmp_path),
                        journal_path=":memory:", max_action_chars=2200)
    request = _chat(messages=[{"role": "user", "content": "Create agent_check.py"}], tools=[WRITE])
    with TestClient(create_app(settings)) as client:
        response1 = client.post('/v1/chat/completions', headers=AUTH, json=request)
        assert response1.status_code == 502
        assert response1.json()["error"]["code"] == "UPSTREAM_OUTPUT_LIMIT"
        assert 'tool_calls' not in response1.text
        assert len(calls) == 1  # No silent retry.
        response2 = client.post('/v1/chat/completions', headers=AUTH, json=request)
        assert response2.status_code == 502
        assert len(calls) == 2
        response3 = client.post('/v1/chat/completions', headers=AUTH, json=request)
        assert response3.status_code == 200
        tool = response3.json()["choices"][0]["message"]["tool_calls"][0]
        assert json.loads(tool["function"]["arguments"])["content"] == 'print(2 + 2)'
        response4 = client.post('/v1/chat/completions', headers=AUTH, json=request)
        assert response4.status_code == 200
    assert [int(_guide(v).split('target at most ')[1].split(' characters')[0]) for v in calls] == [2200, 1300, 1000, 2200]


def test_rate_limit_does_not_trigger_output_budget_adaptation(monkeypatch, tmp_path):
    payloads = []
    def handler(request):
        payloads.append(json.loads(request.content))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=response_stream(
            {"type": "error", "error": {"statusCode": 429, "message": "quota"}}))
    mock_molab(monkeypatch, handler)
    settings = Settings(provider="molab", molab_config_path=save_config(tmp_path), journal_path=":memory:")
    with TestClient(create_app(settings)) as client:
        for _ in range(2):
            res = client.post('/v1/chat/completions', headers=AUTH, json=_chat(tools=[WRITE]))
            assert res.status_code == 429
            assert res.json()['error']['code'] == 'UPSTREAM_RATE_LIMIT'
    assert len(payloads) == 2
    assert _guide(payloads[0]) == _guide(payloads[1])


def test_streaming_output_limit_never_claims_done_or_tool_execution(monkeypatch, tmp_path):
    partial = '@@CALL_V2 Write\n@@FIELD path\nindex.html\n@@FIELD content\n<div>huge'
    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=response_stream(
            {"type": "text-delta", "delta": partial}, {"type": "finish", "finishReason": "length"}))
    mock_molab(monkeypatch, handler)
    settings = Settings(provider="molab", molab_config_path=save_config(tmp_path), journal_path=":memory:")
    with TestClient(create_app(settings)) as client:
        res = client.post('/v1/chat/completions', headers=AUTH, json=_chat(stream=True))
    assert res.status_code == 200  # SSE HTTP status; the event signals failure.
    assert "UPSTREAM_OUTPUT_LIMIT" in res.text
    assert '"tool_calls"' not in res.text
    assert 'data: [DONE]' not in res.text


def test_fingerprint_has_no_persistent_raw_prompt_and_cache_expires(monkeypatch):
    provider = MolabProvider(Settings(provider="fake"))
    req = ChatRequest.model_validate(_chat(tools=[WRITE]))
    messages = [m.model_dump(exclude_none=True) for m in req.messages]
    fingerprint = provider._request_fingerprint(req, messages)
    assert len(fingerprint) == 64
    assert "HTML" not in fingerprint
    provider._observe_outcome(fingerprint, "UPSTREAM_OUTPUT_LIMIT")
    assert provider._budget_for(fingerprint) == 1300
    old_count, _ = provider._output_limit_history[fingerprint]
    provider._output_limit_history[fingerprint] = (old_count, -1000.0)
    assert provider._budget_for(fingerprint) == 2200
    assert not provider._output_limit_history


def test_sqlite_upgrade_keeps_old_journal_and_adds_budget_metadata(tmp_path):
    import sqlite3
    from bridge_x.journal import Journal
    file = tmp_path / 'old_journal.sqlite3'
    with sqlite3.connect(file) as db:
        db.execute('''CREATE TABLE upstream_failures(
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id TEXT NOT NULL,error_code TEXT NOT NULL,upstream_event TEXT NOT NULL,
            upstream_status INTEGER,sse_event_count INTEGER,sse_partial_text_chars INTEGER,
            sse_body_bytes INTEGER,elapsed_ms INTEGER,input_message_count INTEGER,
            input_tool_count INTEGER,upstream_request_bytes INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')
        db.execute('''INSERT INTO upstream_failures(request_id,error_code,upstream_event)
                      VALUES('old_id','UPSTREAM_OUTPUT_LIMIT','finish')''')
    journal = Journal(str(file))
    assert len(journal.latest_upstream_failures()) == 1
    assert journal.latest_upstream_failures()[0]['request_id'] == 'old_id'
    journal.upstream_failure('new_id','UPSTREAM_OUTPUT_LIMIT', {
        'upstream_event': 'finish', 'upstream_status': 200, 'advisory_action_chars': 1300})
    row = journal.latest_upstream_failures()[0]
    assert row['advisory_action_chars'] == 1300
    assert row['request_id'] == 'new_id'
    journal.close()
