"""Explicit rejection can recover; ambiguous or partially delivered work cannot."""
import asyncio
from dataclasses import replace
import json
import sqlite3
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from bridge_x.gateway import create_app
from bridge_x.journal import Journal
from bridge_x.molab_provider import MolabProvider
from bridge_x.rate_control import RateController
from .conftest import WRITE
from .test_rate_control import settings, AUTH
from .test_molab_integration import mock_molab, save_config, response_stream
from .test_native_molab import events


def retry_settings(tmp_path, **kwargs):
    return replace(settings(provider="molab", molab_tool_mode="native", verify_molab_native_mode=True,
                            molab_config_path=save_config(tmp_path), molab_rate_retries=2,
                            molab_cooldown_s=0.025, molab_request_interval_s=0.01, heartbeat_s=0.005), **kwargs)


def upstream_sequence(monkeypatch, responses):
    posts = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, text='<div data-config=\'{"ai":{"mode":"manual"}}\'></div>')
        posts.append(request.content)
        response = responses[min(len(posts) - 1, len(responses) - 1)]
        if isinstance(response, Exception):
            raise response
        return response

    mock_molab(monkeypatch, handler)
    return posts


def stream_response(*items):
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=response_stream(*items))


def rate_event(**kwargs):
    return {"type": "error", "error": {"code": "rate_limit", **kwargs}}


BODY = {"messages": [{"role": "user", "content": "edit"}], "tools": [WRITE]}


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("http_error", [False, True])
def test_rate_then_success_returns_one_native_tool_without_client_failure(monkeypatch, tmp_path, stream, http_error):
    first = httpx.Response(429, json={"error": {"code": "rate_limit"}}) if http_error else stream_response(rate_event())
    posts = upstream_sequence(monkeypatch, [first, stream_response(*events(), {"type": "finish", "finishReason": "tool-calls"})])
    cfg = retry_settings(tmp_path)
    with TestClient(create_app(cfg)) as client:
        response = client.post('/v1/chat/completions', headers=AUTH, json={**BODY, "stream": stream})
        assert response.status_code == 200
        if stream:
            assert 'event: error' not in response.text and 'data: [DONE]' in response.text
            assert response.text.count('"name":"Write"') == 1
            assert ': bridge-x waiting' in response.text
        else:
            assert len(response.json()['choices'][0]['message']['tool_calls']) == 1
        db = client.app.state.journal.db
        assert db.execute('SELECT count(*) FROM operations').fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM diagnostics WHERE phase='rate_limit_retry_wait'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM diagnostics WHERE phase='failed'").fetchone()[0] == 0
        assert len(posts) == 2
        # Same semantic request: no injected receipt, fabricated result or edit.
        a, b = map(json.loads, posts)
        semantic = lambda data: [{k: v for k, v in m.items() if k != 'id'} for m in data['messages']]
        assert semantic(a) == semantic(b) and a['tools'] == b['tools']


@pytest.mark.parametrize("http_error", [False, True])
def test_retries_are_bounded_when_every_attempt_is_rate_limited(monkeypatch, tmp_path, http_error):
    error = httpx.Response(429, json={"error": {"code": "rate_limit"}}) if http_error else stream_response(rate_event())
    posts = upstream_sequence(monkeypatch, [error])
    with TestClient(create_app(retry_settings(tmp_path))) as client:
        response = client.post('/v1/chat/completions', headers=AUTH, json=BODY)
        assert response.status_code == 429
        assert response.json()['error']['type'] == 'rate_limit_error'
        assert len(posts) == 3
        assert client.app.state.journal.db.execute('SELECT count(*) FROM operations').fetchone()[0] == 0


@pytest.mark.parametrize("prior", [
    [{"type": "text-delta", "delta": "partial"}],
    [{"type": "text", "text": "fallback"}],
    [{"type": "tool-input-start", "toolCallId": "x", "toolName": "Write"}],
    events(),
    [{"type": "finish", "finishReason": "stop"}],
])
def test_no_retry_after_any_text_tool_input_or_terminal(monkeypatch, tmp_path, prior):
    posts = upstream_sequence(monkeypatch, [stream_response(*prior, rate_event())])
    with TestClient(create_app(retry_settings(tmp_path))) as client:
        response = client.post('/v1/chat/completions', headers=AUTH, json=BODY)
        assert response.status_code == 429 and len(posts) == 1
        assert client.app.state.journal.db.execute('SELECT count(*) FROM operations').fetchone()[0] == 0


@pytest.mark.parametrize("failure", [
    httpx.ReadTimeout('private network error'),
    stream_response({"type": "error", "error": {"code": "insufficient_quota"}}),
    httpx.Response(429, json={"error": {"code": "insufficient_quota"}}),
    stream_response({"type": "text-delta", "delta": "incomplete"}),
    stream_response({"type": "error", "errorText": "unknown failure"}),
])
def test_no_retry_on_unknown_outcome_permanent_quota_or_incomplete_stream(monkeypatch, tmp_path, failure):
    posts = upstream_sequence(monkeypatch, [failure])
    with TestClient(create_app(retry_settings(tmp_path))) as client:
        response = client.post('/v1/chat/completions', headers=AUTH, json=BODY)
        assert response.status_code >= 400 and len(posts) == 1
        assert 'private network error' not in response.text


def test_server_delay_exceeding_total_deadline_is_not_retried(monkeypatch, tmp_path):
    posts = upstream_sequence(monkeypatch, [stream_response(rate_event(retry_after=3600))])
    with TestClient(create_app(retry_settings(tmp_path, timeout_s=1))) as client:
        response = client.post('/v1/chat/completions', headers=AUTH, json=BODY)
        assert response.status_code == 429 and len(posts) == 1
        assert response.headers['retry-after'] == '3600'


def test_success_does_not_erase_recent_rate_pressure_after_restart(tmp_path):
    cfg = retry_settings(tmp_path, molab_request_interval_s=15, molab_cooldown_s=60)
    path = str(tmp_path / 'state.sqlite3')
    journal = Journal(path)
    controller = RateController(cfg)
    controller.bind('molab', journal)
    assert controller.note_limit() == 60
    controller.note_success()
    controller.note_success()
    assert controller.interval == 30 and controller.failures == 1
    journal.close()
    journal = Journal(path)
    restarted = RateController(cfg)
    restarted.bind('molab', journal)
    assert restarted.last_limit == controller.last_limit
    assert restarted.note_limit() == 120 and restarted.interval == 60
    restarted.last_limit = time.time() - cfg.molab_rate_recovery_s - 1
    restarted.note_success()
    assert restarted.failures == 0 and restarted.interval < 60
    journal.close()


def test_upgrade_old_provider_cache_preserves_existing_data(tmp_path):
    path = str(tmp_path / 'old.sqlite3')
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE provider_control(provider_key TEXT PRIMARY KEY,blocked_until REAL NOT NULL,last_start REAL NOT NULL,failures INTEGER NOT NULL,interval_s REAL NOT NULL)')
        db.execute('INSERT INTO provider_control VALUES(?,?,?,?,?)', ('molab', time.time()+60, 123, 1, 30))
    journal = Journal(path)
    controller = RateController(retry_settings(tmp_path, molab_request_interval_s=15))
    controller.bind('molab', journal)
    assert controller.blocked_until > time.time() and controller.interval == 30
    assert controller.failures == 1 and controller.last_start == 123 and controller.last_limit > 0
    journal.close()


@pytest.mark.asyncio
async def test_cancelling_rate_wait_releases_slot_and_never_sends_second_post(monkeypatch, tmp_path):
    from .test_molab_integration import request_factory
    posts = upstream_sequence(monkeypatch, [stream_response(rate_event())])
    provider = MolabProvider(retry_settings(tmp_path, molab_cooldown_s=2))
    req = request_factory([WRITE])
    notices = asyncio.Event()

    async def run():
        async for event in provider.generate(req, [m.model_dump(exclude_none=True) for m in req.messages]):
            notices.set()

    task = asyncio.create_task(run())
    await asyncio.wait_for(notices.wait(), 2)
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(posts) == 1
    assert not provider.rate_controller.busy and provider.rate_controller.foreground_waiters == 0


@pytest.mark.asyncio
async def test_background_waits_past_short_queue_limit_without_false_upstream_error(monkeypatch, tmp_path):
    from .test_molab_integration import request_factory
    posts = upstream_sequence(monkeypatch, [stream_response({"type": "finish", "finishReason": "stop"})])
    cfg = retry_settings(tmp_path, molab_max_queue_wait_s=0.01, timeout_s=2)
    provider = MolabProvider(cfg)
    req = request_factory([WRITE])
    req._execution_scope = 'project_memory_extract:task'

    async def run():
        return [e async for e in provider.generate(req, [m.model_dump(exclude_none=True) for m in req.messages])]

    async with provider.rate_controller.slot('main_turn'):
        task = asyncio.create_task(run())
        await asyncio.sleep(0.04)
        assert not task.done()
    result = await asyncio.wait_for(task, 2)
    assert result[-1].reason == 'stop' and len(posts) == 1


def test_unverified_notebook_mode_has_no_automatic_replay(tmp_path):
    cfg = retry_settings(tmp_path, verify_molab_native_mode=False)
    assert RateController(cfg).status()['automatic_upstream_retry'] is False


def test_local_cooldown_is_distinguished_from_new_upstream_rejection(tmp_path):
    from bridge_x.errors import BridgeError
    controller = RateController(retry_settings(tmp_path, molab_max_queue_wait_s=0.01, timeout_s=1))
    controller.note_limit(300)
    with pytest.raises(BridgeError) as ex:
        controller.preflight()
    assert ex.value.code == 'MOLAB_COOLDOWN_ACTIVE'
    assert ex.value.public()['error']['type'] == 'rate_limit_error'


def test_known_cooldown_within_turn_budget_waits_instead_of_failing_short_queue(monkeypatch, tmp_path):
    posts = upstream_sequence(monkeypatch, [stream_response(*events(), {"type": "finish", "finishReason": "tool-calls"})])
    cfg = retry_settings(tmp_path, molab_max_queue_wait_s=0.01, timeout_s=2)
    provider = MolabProvider(cfg)
    provider.rate_controller.note_limit(0.08)
    with TestClient(create_app(cfg, provider=provider)) as client:
        response = client.post('/v1/chat/completions', headers=AUTH, json={**BODY, 'stream': True})
        assert 'event: error' not in response.text and 'data: [DONE]' in response.text
        assert ': bridge-x waiting' in response.text and len(posts) == 1


def test_thinking_then_explicit_rate_limit_keeps_heartbeat_and_recovers(monkeypatch, tmp_path):
    attempts = []

    async def handler(request):
        if request.method == 'GET':
            return httpx.Response(200, text='<div data-config=\'{"ai":{"mode":"manual"}}\'></div>')
        attempts.append(request)
        await asyncio.sleep(0.08)
        if len(attempts) == 1:
            return stream_response(rate_event())
        return stream_response(*events(), {"type": "finish", "finishReason": "tool-calls"})

    mock_molab(monkeypatch, handler)
    with TestClient(create_app(retry_settings(tmp_path, timeout_s=2))) as client:
        response = client.post('/v1/chat/completions', headers=AUTH, json={**BODY, 'stream': True})
        assert len(attempts) == 2
        assert response.text.count(': bridge-x waiting') >= 5
        assert 'event: error' not in response.text and 'data: [DONE]' in response.text
        assert response.text.count('"name":"Write"') == 1


def test_thinking_uses_one_total_deadline_not_a_new_deadline_per_attempt(monkeypatch, tmp_path):
    attempts = []

    async def handler(request):
        if request.method == 'GET':
            return httpx.Response(200, text='<div data-config=\'{"ai":{"mode":"manual"}}\'></div>')
        attempts.append(request)
        await asyncio.sleep(0.08)
        return stream_response(rate_event())

    mock_molab(monkeypatch, handler)
    cfg = retry_settings(tmp_path, timeout_s=0.15, molab_cooldown_s=0.1)
    with TestClient(create_app(cfg)) as client:
        response = client.post('/v1/chat/completions', headers=AUTH, json=BODY)
        assert response.status_code == 429 and len(attempts) == 1


def test_thinking_deadline_cancels_upstream_and_releases_slot(monkeypatch, tmp_path):
    attempts = []

    async def handler(request):
        if request.method == 'GET':
            return httpx.Response(200, text='<div data-config=\'{"ai":{"mode":"manual"}}\'></div>')
        attempts.append(request)
        await asyncio.sleep(5)
        return stream_response({"type": "finish", "finishReason": "stop"})

    mock_molab(monkeypatch, handler)
    cfg = retry_settings(tmp_path, timeout_s=0.05)
    provider = MolabProvider(cfg)
    with TestClient(create_app(cfg, provider=provider)) as client:
        response = client.post('/v1/chat/completions', headers=AUTH, json={**BODY, 'stream': True})
        assert 'UPSTREAM_DEADLINE' in response.text and 'data: [DONE]' not in response.text
        assert len(attempts) == 1 and not provider.rate_controller.busy
