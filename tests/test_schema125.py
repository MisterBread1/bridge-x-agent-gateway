"""Bridge X 12.5 regressions: exact declared tool schema and safe errors."""
import json
import pytest
import httpx
from fastapi.testclient import TestClient
from bridge_x.schemas import ChatRequest
from bridge_x.molab_provider import _tool_prompt, build_molab_messages
from bridge_x.errors import BridgeError
from bridge_x.tools import parse_intent
from bridge_x.gateway import create_app
from bridge_x.config import Settings
from .conftest import WRITE, BASH
from .test_molab_integration import save_config, mock_molab, response_stream


EDIT = {"type": "function", "function": {
    "name": "Edit", "description": "Replace a specific selection in a project file.",
    "parameters": {"type": "object", "additionalProperties": False,
        "properties": {
            "file_path": {"type":"string"},
            "old_string": {"type":"string"},
            "new_string": {"type":"string"},
            "replace_all": {"type":"boolean"},
        }, "required": ["file_path", "old_string", "new_string"]}}}
NESTED = {"type":"function", "function": {"name":"Task", "parameters":{
    "type":"object", "additionalProperties":False,
    "properties": {"config":{"type":"object", "required":["mode","files"],
        "additionalProperties":False,
        "properties":{"mode":{"type":"string","enum":["safe","dry-run"]},
            "files":{"type":"array","items":{"type":"string"}}}}},
    "required":["config"]}}}


def req(tool, content="Улучши дизайн и отредактируй существующий файл"):
    return ChatRequest.model_validate({"model":"molab-glm", "tools":[tool],
         "messages":[{"role":"user","content":content}]})


def test_exact_edit_schema_in_model_prompt():
    r=req(EDIT)
    prompt=_tool_prompt(r,[{"role":"user","content":"Улучши дизайн и отредактируй существующий файл"}])
    assert '"old_string"' in prompt and '"new_string"' in prompt
    assert '"file_path"' in prompt
    assert '"additionalProperties":false' in prompt
    assert '"required":["file_path","old_string","new_string"]' in prompt
    assert 'first_required_string_field' not in prompt


def test_nested_constraints_are_displayed():
    prompt=_tool_prompt(req(NESTED),[{"role":"user","content":"Configure task"}])
    assert '"enum":["safe","dry-run"]' in prompt
    assert '"required":["mode","files"]' in prompt
    assert '"items":{"type":"string"}' in prompt


def test_missing_required_argument_names_only_no_values():
    r=req(EDIT)
    frame='@@TOOL_CALL Edit\n@@ARG file_path\nprivate/project.html\n@@END_ARG\n@@ARG new_string\nMY SECRET HTML BODY\n@@END_ARG\n@@END_TOOL_CALL'
    with pytest.raises(BridgeError) as e:
        parse_intent(frame,r)
    assert e.value.code=='TOOL_SCHEMA_MISMATCH'
    assert 'old_string' in e.value.message
    assert 'MY SECRET' not in e.value.message
    assert 'private/project' not in e.value.message


def test_extra_argument_not_leaked():
    r=req(EDIT)
    frame='@@TOOL_CALL Edit\n@@ARG file_path\na.html\n@@END_ARG\n@@ARG old_string\nhi\n@@END_ARG\n@@ARG new_string\nhello\n@@END_ARG\n@@ARG leaked_secret_token\nsensitive-data\n@@END_ARG\n@@END_TOOL_CALL'
    with pytest.raises(BridgeError) as e:
        parse_intent(frame,r)
    assert 'unexpected argument' in e.value.message
    assert 'leaked_secret_token' not in e.value.message
    assert 'sensitive-data' not in e.value.message


def test_nested_type_failure_has_path_but_no_value():
    frame='@@TOOL_CALL Task\n@@VALUE config\n{"mode":"safe","files":"SECRET PATH"}\n@@END_VALUE\n@@END_TOOL_CALL'
    with pytest.raises(BridgeError) as e:
        parse_intent(frame,req(NESTED))
    assert 'config.files' in e.value.message
    assert 'expected array' in e.value.message
    assert 'SECRET PATH' not in e.value.message


def test_correct_nested_value_is_accepted():
    frame='@@TOOL_CALL Task\n@@VALUE config\n{"mode":"safe","files":["a.py"]}\n@@END_VALUE\n@@END_TOOL_CALL'
    calls=parse_intent(frame,req(NESTED))
    assert calls and calls[0].name == 'Task'
    assert calls[0].arguments['config']['files']==['a.py']


def test_extra_model_narrative_not_accepted_as_executable_tool():
    frame='I did it.\n@@TOOL_CALL Edit\n@@ARG file_path\nfile.html\n@@END_ARG\n@@END_TOOL_CALL'
    # Explanatory prose containing a command marker is NOT a tool instruction.
    # It must neither execute nor produce a false INVALID_TOOL_FRAME error.
    assert parse_intent(frame,req(EDIT)) is None


def test_live_adapter_mock_http_reports_field_without_executing(monkeypatch,tmp_path):
    frame='@@TOOL_CALL Edit\n@@ARG file_path\na.html\n@@END_ARG\n@@ARG new_string\nx\n@@END_ARG\n@@END_TOOL_CALL'
    mock_molab(monkeypatch, lambda request: httpx.Response(200, headers={'content-type':'text/event-stream'},
        content=response_stream({'type':'text-delta','delta':frame}, {'type':'finish','finishReason':'stop'})))
    cfg=save_config(tmp_path)
    settings=Settings(provider='molab',molab_config_path=cfg,journal_path=':memory:')
    with TestClient(create_app(settings)) as client:
        res=client.post('/v1/chat/completions', headers={'Authorization':'Bearer molab-local'}, json={
            'model':'molab-glm', 'messages':[{'role':'user','content':'Edit html'}], 'tools':[EDIT]})
        assert res.status_code==422
        assert res.json()['error']['code']=='TOOL_SCHEMA_MISMATCH'
        assert 'old_string' in res.json()['error']['message']
        assert 'tool_calls' not in res.text
