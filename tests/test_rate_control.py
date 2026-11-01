"""Scheduling and actual HTTP/SSE failure boundaries; no live quota consumed."""
import asyncio
from dataclasses import replace
from email.utils import formatdate
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from bridge_x.config import Settings
from bridge_x.errors import BridgeError
from bridge_x.gateway import create_app
from bridge_x.journal import Journal
from bridge_x.molab_provider import MolabProvider, decode_molab_event
from bridge_x.rate_control import RateController, event_retry_after, retry_after_seconds, is_background
from .test_molab_integration import mock_molab, save_config, response_stream
from .test_native_molab import events
from .conftest import WRITE

AUTH = {"Authorization": "Bearer molab-local"}


def settings(**overrides):
    return replace(Settings(molab_rate_control=True, molab_request_interval_s=0.03,
                            molab_background_interval_s=0.03, molab_background_idle_s=0.03,
                            molab_max_queue_wait_s=3, journal_path=":memory:"), **overrides)


@pytest.mark.parametrize("value,expected", [("60", 60), ("2.5", 2.5), (0, 0),
    ("bad", None), (True, None), ("NaN", None), ("inf", None), (-1, None), (None, None)])
def test_retry_after_input(value, expected):
    assert retry_after_seconds(value) == expected


def test_retry_after_http_date_and_nested_event():
    assert retry_after_seconds(formatdate(1700000123, usegmt=True), now=1700000000) == 123
    assert retry_after_seconds(formatdate(1700000000, usegmt=True), now=1700000123) == 0
    assert event_retry_after({"error": {"cause": {"retryAfterMs": 12500}}}) == 12.5
    assert event_retry_after({"message": "retry after 999999 seconds private"}) is None


def test_real_cli_configuration_enables_pacing(monkeypatch):
    for key in ("BRIDGEX_MOLAB_REQUEST_INTERVAL", "BRIDGEX_MOLAB_BACKGROUND_INTERVAL",
                "BRIDGEX_MOLAB_BACKGROUND_IDLE", "BRIDGEX_MOLAB_COOLDOWN", "BRIDGEX_MOLAB_MAX_QUEUE_WAIT"):
        monkeypatch.delenv(key, raising=False)
    cfg = Settings.from_env()
    assert cfg.molab_rate_control and cfg.molab_request_interval_s == 1
    assert cfg.molab_cooldown_s == 60


def test_only_known_background_tasks_are_deprioritized():
    assert is_background("project_memory_extract:abcdef")
    assert is_background("session_title:123")
    assert not is_background("project_memory_recall:123")
    assert not is_background("main_turn")
    assert not is_background("subagent:123")


@pytest.mark.asyncio
async def test_concurrent_generation_is_serialized_and_spaced():
    controller = RateController(settings())
    starts, active = [], 0

    async def run():
        nonlocal active
        async with controller.slot("main_turn"):
            assert active == 0
            active += 1
            starts.append(time.monotonic())
            await asyncio.sleep(0.005)
            active -= 1

    await asyncio.wait_for(asyncio.gather(*(run() for _ in range(4))), 3)
    assert all(b - a >= 0.025 for a, b in zip(starts, starts[1:]))
    assert not controller.busy and controller.foreground_waiters == 0


@pytest.mark.asyncio
async def test_waiting_memory_does_not_hold_foreground_lock():
    controller = RateController(settings(molab_background_idle_s=0.08))
    controller.last_foreground_activity = time.time()
    order = []

    async def run(scope):
        async with controller.slot(scope):
            order.append(scope)

    background = asyncio.create_task(run("project_memory_extract:abc"))
    await asyncio.sleep(0)
    await run("main_turn")
    assert order == ["main_turn"]
    await asyncio.wait_for(background, 3)
    assert order == ["main_turn", "project_memory_extract:abc"]


@pytest.mark.asyncio
async def test_cancellation_releases_waiter_and_active_slot():
    controller = RateController(settings())
    entered = asyncio.Event()

    async def hold():
        async with controller.slot("main_turn"):
            entered.set()
            await asyncio.Event().wait()

    holder = asyncio.create_task(hold())
    await entered.wait()
    waiter = asyncio.create_task(hold())
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert controller.foreground_waiters == 0
    holder.cancel()
    with pytest.raises(asyncio.CancelledError):
        await holder
    assert not controller.busy
    async with controller.slot("main_turn"):
        pass


@pytest.mark.asyncio
async def test_cooldown_applies_to_other_branches_without_replay():
    controller = RateController(settings(molab_cooldown_s=0.08))
    admitted = []
    async with controller.slot("main_turn"):
        controller.note_limit()
    limited_at = time.monotonic()
    async with controller.slot("project_memory_extract:other"):
        admitted.append(time.monotonic())
    assert admitted[0] - limited_at >= 0.07
    assert len(admitted) == 1


def test_cooldown_survives_restart_and_keeps_longer_server_delay(tmp_path):
    cfg = settings(molab_max_queue_wait_s=0.05)
    with_journal = Journal(str(tmp_path / "state.sqlite3"))
    first = RateController(cfg)
    first.bind("molab", with_journal)
    assert first.note_limit(3600) == 3600
    with_journal.close()
    reopened = Journal(str(tmp_path / "state.sqlite3"))
    second = RateController(cfg)
    second.bind("molab", reopened)
    with pytest.raises(BridgeError) as ex:
        second.preflight()
    assert ex.value.status == 429 and ex.value.retryable
    assert 3595 < ex.value.retry_after_s <= 3600
    assert second.status()["automatic_upstream_retry"] is False
    assert second.note_limit() == 120
    assert second.blocked_until - time.time() > 3595  # never shorten a server deadline
    reopened.close()


@pytest.mark.asyncio
async def test_queue_deadline_returns_retry_without_entering_upstream():
    controller = RateController(settings(molab_max_queue_wait_s=0.03))
    controller.note_limit(300)
    with pytest.raises(BridgeError) as ex:
        async with controller.slot("main_turn"):
            pytest.fail("Must not enter upstream during cooldown")
    assert ex.value.code == "MOLAB_QUEUE_TIMEOUT" and ex.value.retry_after_s > 290
    assert controller.foreground_waiters == 0 and not controller.busy


@pytest.mark.parametrize("event_name,payload", [
    ("error", {"error": {"statusCode": 429, "retry_after": 321}}),
    ("message", {"type": "error", "error": {"code": "rate_limit", "retry_after": 321}}),
    ("message", {"type": "finish", "finishReason": "error", "error": {"code": "rate_limit", "retry_after": 321}}),
    ("legacy-error", {"code": "rate_limit", "retry_after": 321})])
def test_every_error_terminal_preserves_retry_hint(event_name, payload):
    out = decode_molab_event(json.dumps(payload), event_name)
    assert out[0].code == "UPSTREAM_RATE_LIMIT" and out[0].retry_after_s == 321


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("http_error", [False, True])
def test_gateway_rate_error_is_retryable_and_repeated_request_never_hits_molab(monkeypatch, tmp_path, stream, http_error):
    posts = []

    def upstream(request):
        posts.append(request)
        if http_error:
            return httpx.Response(429, headers={"Retry-After": "321"}, content=b"private body")
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=response_stream(
            *events(), {"type": "finish", "finishReason": "tool-calls"},
            {"type": "error", "error": {"code": "rate_limit", "retry_after": 321, "message": "private body"}}))

    mock_molab(monkeypatch, upstream)
    cfg = settings(provider="molab", molab_tool_mode="native", molab_config_path=save_config(tmp_path), molab_max_queue_wait_s=0.05)
    provider = MolabProvider(cfg)
    with TestClient(create_app(cfg, provider=provider)) as client:
        body = {"messages": [{"role": "user", "content": "edit"}], "tools": [WRITE], "stream": stream}
        first = client.post("/v1/chat/completions", headers=AUTH, json=body)
        if stream:
            assert "event: error" in first.text and "[DONE]" not in first.text
            assert '"tool_calls"' not in first.text
            assert '"type":"rate_limit_error"' in first.text and '"retryable":true' in first.text
        else:
            assert first.status_code == 429 and first.headers["retry-after"] == "321"
            assert first.json()["error"]["type"] == "rate_limit_error"
            assert first.json()["error"]["retryable"] is True
        second = client.post("/v1/chat/completions", headers=AUTH, json=body)
        assert second.status_code == 429 and int(second.headers["retry-after"]) >= 320
        assert len(posts) == 1
        assert client.app.state.journal.db.execute("SELECT count(*) FROM operations").fetchone()[0] == 0
        assert "private body" not in first.text + second.text
        assert client.get("/diagnostics", headers=AUTH).json()["rate_control"]["cooldown_remaining_seconds"] >= 320


@pytest.mark.parametrize("http_error", [False, True])
def test_explicit_exhausted_quota_is_not_misrepresented_as_temporary_rate(monkeypatch, tmp_path, http_error):
    posts = []

    def upstream(request):
        posts.append(request)
        if http_error:
            return httpx.Response(429, json={"error": {"code": "insufficient_quota", "status": 429}})
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=response_stream(
            {"type": "error", "error": {"code": "insufficient_quota", "status": 429, "retry_after": 1}}))

    mock_molab(monkeypatch, upstream)
    cfg = settings(provider="molab", molab_config_path=save_config(tmp_path))
    provider = MolabProvider(cfg)
    with TestClient(create_app(cfg, provider=provider)) as client:
        response = client.post("/v1/chat/completions", headers=AUTH, json={"messages": [{"role": "user", "content": "hi"}]})
        error = response.json()["error"]
        assert error["code"] == "UPSTREAM_QUOTA_EXHAUSTED"
        assert error["type"] == "insufficient_quota" and error["retryable"] is False
        assert "retry-after" not in response.headers
        assert provider.rate_status()["cooldown_remaining_seconds"] == 0
        assert len(posts) == 1


def test_longer_header_hint_wins_over_shorter_sse_hint(monkeypatch, tmp_path):
    mock_molab(monkeypatch, lambda request: httpx.Response(200,
        headers={"content-type": "text/event-stream", "Retry-After": "7200"},
        content=response_stream({"type": "error", "error": {"code": "rate_limit", "retry_after": 1}})))
    cfg = settings(provider="molab", molab_config_path=save_config(tmp_path))
    with TestClient(create_app(cfg)) as client:
        response = client.post("/v1/chat/completions", headers=AUTH, json={"messages": [{"role": "user", "content": "hi"}]})
        assert response.headers["retry-after"] == "7200"
        assert response.json()["error"]["retry_after_seconds"] == 7200
