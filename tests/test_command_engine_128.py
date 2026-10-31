"""Command Engine 3.0 regression and adversarial tests.

Exercise real schemas, multi-line source content, malformed frames and the
HTTP integration. No live network endpoints or operator credentials required.
"""
import json
import random
import string

import pytest
from fastapi.testclient import TestClient

from bridge_x.config import Settings
from bridge_x.errors import BridgeError
from bridge_x.gateway import create_app
from bridge_x.molab_provider import _tool_prompt
from bridge_x.providers import TextDelta, Finish, Failed
from bridge_x.schemas import ChatRequest
from bridge_x.tools import parse_intent
from .conftest import WRITE, BASH


def req(tools=None, **extra):
    return ChatRequest.model_validate({
        "messages": [{"role":"user", "content":"create a small file"}],
        "tools": [WRITE, BASH] if tools is None else tools,
        **extra,
    })


def v2(name, fields):
    lines = ["@@CALL_V2 " + name]
    for kind, key, value in fields:
        lines += [f"@@{kind} {key}", value]
    lines.append("@@END_CALL")
    return "\n".join(lines)


def error_code(raw, tools=None, **kwargs):
    with pytest.raises(BridgeError) as exc:
        parse_intent(raw, req(tools, **kwargs))
    return exc.value.code


def test_v2_full_write_single_final_marker():
    result = parse_intent(v2("Write", [("FIELD", "path", "a.py"), ("FIELD", "content", "print(2+2)")]), req())
    assert result[0].arguments == {"path":"a.py", "content":"print(2+2)"}


def test_v2_full_bash_single_final_marker():
    call = parse_intent(v2("Bash", [("FIELD", "command", "python agent_check.py")]), req())[0]
    assert call.name == "Bash" and call.arguments["command"] == "python agent_check.py"


@pytest.mark.parametrize("name", ["Read", "Ping", "CheckStatus"])
def test_v2_zero_field_tool(name):
    declaration = {"type":"function", "function":{"name":name, "parameters":{"type":"object", "properties":{},"additionalProperties":False}}}
    assert parse_intent(v2(name, []), req([declaration]))[0].arguments == {}


@pytest.mark.parametrize("value", ["", " ", "  hello  ", "cmd /c echo yes", r"C:\Work\app\main.py", "Привет 🧪", "'\"\\n--", "a\nb\nc"])
def test_v2_preserves_literal_field_values(value):
    result = parse_intent(v2("Write", [("FIELD", "path", "a.py"), ("FIELD", "content", value)]), req())[0]
    assert result.arguments["content"] == value


def test_v2_windows_crlf_source_file():
    raw = "@@CALL_V2 Write\r\n@@FIELD path\r\na.py\r\n@@FIELD content\r\nprint(1)\r\nprint(2)\r\n@@END_CALL"
    call = parse_intent(raw, req())[0]
    assert call.arguments["content"] == "print(1)\r\nprint(2)"


def test_v2_typed_nested_complex_schema():
    special = {"type":"function", "function":{"name":"Config", "parameters":{
        "type":"object", "properties":{"path":{"type":"string"},"settings":{"type":"object", "properties":{
            "files":{"type":"array","items":{"type":"string"}},
            "enabled":{"type":"boolean"}}, "required":["files","enabled"], "additionalProperties":False}},
        "required":["path","settings"], "additionalProperties":False}}}
    content = json.dumps({"files": ["one.py", "two.py"], "enabled": True})
    c = parse_intent(v2("Config", [("FIELD", "path", "a.json"), ("JSON", "settings", content)]), req([special]))[0]
    assert c.arguments["settings"]["enabled"] is True


@pytest.mark.parametrize("typed", ["NaN", "Infinity", "{bad}", "[1,}", "1e9999"])
def test_v2_rejects_malformed_typed_json(typed):
    typ = {"type":"function", "function":{"name":"Count", "parameters":{
        "type":"object", "properties":{"n":{"type":"number"}},"required":["n"]}}}
    raw = v2("Count", [("JSON", "n", typed)])
    assert error_code(raw, [typ]) in ("INVALID_TOOL_VALUE", "INVALID_TOOL_ARGUMENTS", "INVALID_TOOL_JSON")


@pytest.mark.parametrize("raw", [
    "@@CALL_V2 Write\n@@FIELD path\na.py\n@@FIELD content\nprint(4)",
    "@@CALL_V2 Write\n@@FIELD path\na.py\n@@FIELD content\nprint(4)\n@@END_CAL",
    "@@CALL_V2 Write\n@@FIELD path\na.py\n@@END_CALL\nprint('injected')",
    "@@CALL_V2 Write\n@@FIELD path\na.py\n@@END_CALL\n@@CALL_V2 Bash\n@@END_CALL",
    "@@CALL_V2 Write\n@@FIELD path\na.py\n@@FIELD path\nb.py\n@@END_CALL",
    "@@CALL_V2 Write\ntext outside field\n@@END_CALL",
    "@@CALL_V2 Write\n@@END_CALL\n@@END_CALL",
])
def test_v2_rejects_broken_frame(raw):
    assert error_code(raw) == "INVALID_TOOL_FRAME"


def test_v2_narrative_preamble_is_not_executed():
    # A prefaced example is not a standalone executable call, even if complete.
    narrative = "I have done it\n@@CALL_V2 Write\n@@FIELD path\na.py\n@@FIELD content\nhi\n@@END_CALL"
    assert parse_intent(narrative, req()) is None


def test_v2_escaped_delimiters_in_source_are_literal():
    content = "first\n\\@@FIELD path\na-bad-path\n\\@@JSON nope\n\\@@END_CALL\nlast"
    call = parse_intent(v2("Write", [("FIELD", "path", "a.py"), ("FIELD", "content", content)]), req())[0]
    assert call.arguments["path"] == "a.py"
    assert call.arguments["content"] == "first\n@@FIELD path\na-bad-path\n@@JSON nope\n@@END_CALL\nlast"


def test_v2_missing_required_rejected_by_real_schema():
    assert error_code(v2("Write", [("FIELD", "path", "a.py")])) == "TOOL_SCHEMA_MISMATCH"


def test_v2_extra_field_rejected_by_real_schema():
    assert error_code(v2("Write", [("FIELD", "path", "a.py"), ("FIELD", "content", "okay"),
                                   ("FIELD", "overwrite_everything", "yes")])) == "TOOL_SCHEMA_MISMATCH"


def test_v2_wrong_declared_tool_rejected():
    assert error_code(v2("WriteOther", [("FIELD", "path", "a.py")])) == "TOOL_NOT_AVAILABLE"


def test_v2_forced_choice_enforced():
    choice = {"type":"function", "function":{"name":"Bash"}}
    assert error_code(v2("Write", [("FIELD", "path", "a.py"), ("FIELD", "content", "ok")]), tool_choice=choice) == "WRONG_FORCED_TOOL"


def test_v2_tool_choice_none_enforced():
    assert error_code(v2("Bash", [("FIELD", "command", "echo done")]), tool_choice="none") == "TOOL_CHOICE_NONE"


def test_v2_size_limit_checked_before_schema():
    with pytest.raises(BridgeError) as exc:
        parse_intent(v2("Write", [("FIELD", "path", "a.py"), ("FIELD", "content", "x"*500)]), req(), max_args_bytes=128)
    assert exc.value.code == "TOOL_FRAME_TOO_LARGE"


def test_v2_multiple_random_unicode_source_blobs():
    rng = random.Random(1337)
    alphabet = string.ascii_letters + string.digits + " 🇰🇿🧪\\\"'<> {}"
    for _ in range(150):
        body = "\n".join("".join(rng.choice(alphabet) for _ in range(rng.randint(0,80))) for _ in range(rng.randint(1,12)))
        call = parse_intent(v2("Write", [("FIELD", "path", "a.txt"), ("FIELD", "content", body)]), req())[0]
        assert call.arguments["content"] == body


def test_prompt_v2_without_old_per_arg_terminator():
    data = [m.model_dump(exclude_none=True) for m in req().messages]
    prompt = _tool_prompt(req(), data)
    assert "@@CALL_V2" in prompt
    assert "NO @@END_ARG markers are needed" in prompt
    assert "Never claim that a command succeeded" in prompt
    assert "@@END_CALL" in prompt


def test_prompt_compact_with_55_tools():
    huge = [WRITE,BASH]+[{'type':'function','function':{'name':f'ExtraTool{i}','description':'A'*100,
            'parameters':{'type':'object','properties':{'q':{'type':'string'}},'required':['q']}}} for i in range(53)]
    request = req(huge)
    prompt = _tool_prompt(request, [m.model_dump(exclude_none=True) for m in request.messages])
    assert len(prompt.encode('utf-8')) < 5000


class V2Provider:
    def __init__(self, text, error=None):
        self.text = text
        self.error = error

    async def generate(self, request, messages):
        for x in range(0, len(self.text), 17):
            yield TextDelta(self.text[x:x+17])
        if self.error:
            yield Failed(self.error, "synthetic interruption")
        else:
            yield Finish("stop")


def test_http_v2_write_is_openai_tool_call(tmp_path):
    output = v2("Write", [("FIELD", "path", "agent_check.py"), ("FIELD", "content", "print(2 + 2)")])
    with TestClient(create_app(Settings(journal_path=str(tmp_path/'state.db')), provider=V2Provider(output))) as client:
        res = client.post('/v1/chat/completions', headers={'Authorization':'Bearer molab-local'}, json={
            'model':'molab-glm','messages':[{'role':'user','content':'create agent_check.py'}],
            'tools':[WRITE,BASH]})
        assert res.status_code == 200
        calls = res.json()['choices'][0]['message']['tool_calls']
        assert len(calls) == 1 and calls[0]['function']['name'] == 'Write'
        assert json.loads(calls[0]['function']['arguments'])['content'] == 'print(2 + 2)'


@pytest.mark.parametrize('streaming',[False, True])
def test_http_v2_interrupted_never_executes_tool(tmp_path, streaming):
    output = v2('Bash', [('FIELD','command','python agent_check.py')])
    with TestClient(create_app(Settings(journal_path=str(tmp_path/'state.db')), provider=V2Provider(output, 'UPSTREAM_RATE_LIMIT'))) as client:
        res = client.post('/v1/chat/completions', headers={'Authorization':'Bearer molab-local'}, json={
            'model':'molab-glm','messages':[{'role':'user','content':'run script'}],
            'stream':streaming,'tools':[WRITE,BASH]})
        if streaming:
            assert '"tool_calls"' not in res.text
            assert 'UPSTREAM_RATE_LIMIT' in res.text
        else:
            assert res.status_code == 429
        assert not client.app.state.journal.db.execute('SELECT call_id FROM intents').fetchall()


def test_http_v2_streaming_tool_call(tmp_path):
    output = v2('Bash', [('FIELD','command','python agent_check.py')])
    with TestClient(create_app(Settings(journal_path=str(tmp_path/'state.db')), provider=V2Provider(output))) as client:
        res = client.post('/v1/chat/completions', headers={'Authorization':'Bearer molab-local'}, json={
            'model':'molab-glm','messages':[{'role':'user','content':'run script'}],
            'stream':True,'tools':[WRITE,BASH]})
        assert res.status_code == 200
        assert '"tool_calls"' in res.text
        assert 'data: [DONE]' in res.text
        assert 'python agent_check.py' in res.text


def test_v2_old_frame_compatibility():
    old = '@@TOOL_CALL Bash\n@@ARG command\npython agent_check.py\n@@END_ARG\n@@END_TOOL_CALL'
    assert parse_intent(old, req())[0].arguments['command'] == 'python agent_check.py'
