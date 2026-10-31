"""Root-cause regression: protocol markers inside prose/data are NOT commands.

Previously parse_intent used substring searches and routed an ordinary reply,
including tool payloads containing a literal @@CALL_V2, into parse_frame_v2.
That produced the exact user-facing error 'Tool frame must begin with a command'.
"""
import json
import pytest
from fastapi.testclient import TestClient
from bridge_x.config import Settings
from bridge_x.gateway import create_app
from bridge_x.providers import TextDelta, Finish
from bridge_x.schemas import ChatRequest
from bridge_x.tools import parse_intent
from bridge_x.errors import BridgeError
from .conftest import WRITE, BASH


def req(**kw):
    return ChatRequest.model_validate({
        'model': 'molab-glm',
        'messages': [{'role': 'user', 'content': 'help'}],
        'tools': [WRITE, BASH],
        **kw,
    })


def tool_text():
    return '@@CALL_V2 Write\n@@FIELD path\nagent_check.py\n@@FIELD content\nprint(2 + 2)\n@@END_CALL'


@pytest.mark.parametrize('body', [
    'I will use @@CALL_V2 for tool calls, not for prose.',
    'The syntax is @@TOOL_CALL <name>, then parameters.',
    'Например, @@CALL_V2 Read — это начало фрейма.',
    'An ordinary response.\n' + tool_text(),
    '```text\n' + tool_text() + '\n```',
    'I have done it.\n@@TOOL_CALL Write\n@@ARG path\na.py\n@@END_ARG\n@@END_TOOL_CALL',
    'CSS content { --example: "@@CALL_V2 Write"; }',
])
def test_marker_in_plain_response_is_never_parsed_as_tool(body):
    assert parse_intent(body, req()) is None


def test_top_level_v2_frame_still_creates_validated_write():
    result = parse_intent(' \n' + tool_text() + '\n', req())
    assert len(result) == 1
    assert result[0].name == 'Write'
    assert result[0].arguments['content'] == 'print(2 + 2)'


def test_top_level_v2_frame_with_bom():
    result = parse_intent('\ufeff' + tool_text(), req())
    assert result[0].arguments['path'] == 'agent_check.py'


def test_legacy_frame_containing_v2_marker_stays_legacy():
    body = '@@TOOL_CALL Write\n@@ARG path\nx.txt\n@@END_ARG\n@@ARG content\nMention @@CALL_V2 inside source code\n@@END_ARG\n@@END_TOOL_CALL'
    result = parse_intent(body, req())
    assert result[0].arguments['content'] == 'Mention @@CALL_V2 inside source code'


def test_json_tool_envelope_containing_v2_marker_stays_json():
    body = json.dumps({'tool_calls': [{'name': 'Write', 'arguments': {
        'path': 'x.txt', 'content': 'start\n@@CALL_V2 Write\nend',
    }}]})
    result = parse_intent(body, req())
    assert result[0].arguments['content'] == 'start\n@@CALL_V2 Write\nend'


def test_json_tool_envelope_containing_legacy_marker_stays_json():
    body = json.dumps({'tool_calls': [{'name': 'Write', 'arguments': {
        'path': 'x.txt', 'content': '@@TOOL_CALL is quoted in documentation',
    }}]})
    result = parse_intent(body, req())
    assert result[0].arguments['content'] == '@@TOOL_CALL is quoted in documentation'


def test_malformed_true_v2_frame_still_rejected():
    with pytest.raises(BridgeError) as err:
        parse_intent('@@CALL_V2 Write\n@@FIELD path\nindex.html', req())
    assert err.value.code == 'INVALID_TOOL_FRAME'


def test_malformed_true_legacy_frame_still_rejected():
    with pytest.raises(BridgeError) as err:
        parse_intent('@@TOOL_CALL Write\n@@ARG path\nx', req())
    assert err.value.code == 'INVALID_TOOL_FRAME'


def test_historical_echo_still_rejected_without_execution():
    with pytest.raises(BridgeError) as err:
        parse_intent('<previous_tool_calls>@@CALL_V2 Write</previous_tool_calls>', req())
    assert err.value.code == 'UPSTREAM_HISTORY_ECHO'


class IncrementalProvider:
    def __init__(self, text):
        self.text = text

    async def generate(self, request, messages):
        for n in range(0, len(self.text), 11):
            yield TextDelta(self.text[n:n+11])
        yield Finish('stop')


@pytest.mark.parametrize('stream',[False, True])
def test_http_prose_with_marker_is_safe_normal_reply(tmp_path,stream):
    text = 'Here is a code sample (do not run it):\n' + tool_text()
    with TestClient(create_app(Settings(journal_path=str(tmp_path/'state.sqlite')),provider=IncrementalProvider(text))) as client:
        response = client.post('/v1/chat/completions', headers={'Authorization':'Bearer molab-local'}, json={
            'model':'molab-glm','stream':stream,
            'messages':[{'role':'user','content':'explain syntax'}],
            'tools':[WRITE,BASH]})
        assert response.status_code == 200
        assert 'tool_calls' not in response.text
        assert 'INVALID_TOOL_FRAME' not in response.text
        assert not client.app.state.journal.db.execute('SELECT call_id FROM intents').fetchall()


def test_prompt_does_not_embed_executable_example():
    from bridge_x.molab_provider import _tool_prompt
    data = [m.model_dump(exclude_none=True) for m in req().messages]
    guide = _tool_prompt(req(),data)
    assert '@@CALL_V2' in guide and '@@END_CALL' in guide
    assert '@@CALL_V2 Write\n@@FIELD' not in guide
    assert 'example.py' not in guide
