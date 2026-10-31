"""Regression tests for output-limit mitigations; never contact Molab."""
import json
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from bridge_x.config import Settings
from bridge_x.errors import BridgeError
from bridge_x.gateway import create_app
from bridge_x.schemas import ChatRequest
from bridge_x.molab_provider import (
    _safe_error_category, _tool_prompt, build_molab_payload, decode_molab_event,
)
from bridge_x.providers import Failed
from .conftest import WRITE, BASH
from .test_molab_integration import mock_molab, save_config, response_stream

READ = {"type": "function", "function": {"name": "Read", "parameters": {
    "type": "object", "properties": {"file_path": {"type": "string"}},
    "required": ["file_path"], "additionalProperties": False}}}
EDIT = {"type": "function", "function": {"name": "Edit", "parameters": {
    "type": "object", "properties": {"file_path": {"type": "string"},
    "old_string": {"type": "string"}, "new_string": {"type": "string"}},
    "required": ["file_path", "old_string", "new_string"],
    "additionalProperties": False}}}


def request(messages=None):
    return ChatRequest.model_validate({"model": "molab-glm", "tools": [WRITE, READ, EDIT, BASH],
        "messages": messages or [{"role": "user", "content": "Улучши существующий файл, премиальный дизайн"}]})


def test_edit_task_starts_with_read_and_honors_soft_budget():
    r = request()
    guidance = _tool_prompt(r, [m.model_dump(exclude_none=True) for m in r.messages], 2500)
    assert '2500 characters' in guidance
    assert 'For THIS turn, inspect' in guidance
    assert guidance.index('Read: ') < guidance.index('Edit: ')
    assert 'ONE small verified action' in guidance
    assert 'Do NOT silently truncate' in guidance


def test_after_tool_result_does_not_require_read_again():
    messages = [{"role": "user", "content": "Улучши существующий файл"},
                {"role": "tool", "tool_call_id": "old_read", "content": "file exists"}]
    req = request(messages)
    guidance = _tool_prompt(req, messages)
    assert 'For THIS turn, inspect' not in guidance
    assert 'do not re-read unnecessarily' in guidance


def test_payload_contains_guidance_but_no_undocumented_max_tokens(tmp_path):
    from bridge_x.molab_provider import read_molab_config
    cfg = read_molab_config(save_config(tmp_path))
    req = request()
    payload = build_molab_payload(req, [m.model_dump(exclude_none=True) for m in req.messages], cfg, 3100)
    assert '3100 characters' in json.dumps(payload['messages'])
    assert 'max_tokens' not in payload['body']
    assert payload['options'] == {'webSearch': False}
    assert payload['messages'] == payload['uiMessages']


def test_length_is_output_limit_and_filter_not_mislabeled():
    assert decode_molab_event(json.dumps({"type":"finish", "finishReason":"length"}))[0].code == 'UPSTREAM_OUTPUT_LIMIT'
    assert decode_molab_event(json.dumps({"type":"finish", "finishReason":"content-filter"}))[0].code == 'UPSTREAM_CONTENT_FILTER'
    assert _safe_error_category({"error": {"message": "Output token limit exceeded", "code": "max_output_tokens"}}) == 'UPSTREAM_OUTPUT_LIMIT'
    assert _safe_error_category({"error": {"message": "Context window exceeded"}}) == 'UPSTREAM_CONTEXT_LIMIT'


def test_invalid_soft_budget_environment(monkeypatch):
    monkeypatch.setenv('BRIDGEX_PROVIDER','molab')
    monkeypatch.setenv('BRIDGEX_ACTION_CHARS','500')
    with pytest.raises(ValueError,match='BRIDGEX_ACTION_CHARS'):
        Settings.from_env()
    monkeypatch.setenv('BRIDGEX_ACTION_CHARS','3700')
    assert Settings.from_env().max_action_chars == 3700


def test_length_after_partial_tool_response_never_delivers_command(monkeypatch, tmp_path):
    seen=[]
    def handler(request):
        seen.append(json.loads(request.content))
        text='@@TOOL_CALL Write\n@@ARG path\nweb.html\n@@END_ARG\n@@ARG content\n<h1>Incomplete'
        return httpx.Response(200, headers={'content-type':'text/event-stream'},
          content=response_stream({'type':'text-delta','delta':text},
                                   {'type':'finish','finishReason':'length'}))
    mock_molab(monkeypatch, handler)
    cfg=save_config(tmp_path)
    settings=Settings(provider='molab',molab_config_path=cfg,journal_path=':memory:',max_action_chars=3000)
    with TestClient(create_app(settings)) as client:
        res=client.post('/v1/chat/completions',headers={'Authorization':'Bearer molab-local'},json={
            'model':'molab-glm','messages':[{'role':'user','content':'Create html'}],
            'tools':[WRITE,READ,EDIT],'stream':True})
        assert res.status_code==200
        assert 'UPSTREAM_OUTPUT_LIMIT' in res.text
        assert '"tool_calls"' not in res.text
        assert 'data: [DONE]' not in res.text
    assert seen
    assert '3000 characters' in json.dumps(seen[0]['messages'])
