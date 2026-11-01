"""Native proxy ownership, actual HTTP telemetry and timing/privacy contracts."""
import asyncio
from contextlib import closing
from http.client import HTTPConnection
import json
import os
import socket
import sqlite3
import time
import pytest
from fastapi.testclient import TestClient
from bridge_x.config import Settings
from bridge_x.desktop_host import GatewayHost
from bridge_x.gateway import create_app
from bridge_x.monitoring import RequestMonitor
from bridge_x.providers import TextDelta, Finish, Failed


def test_request_timings_separate_queue_provider_and_first_output():
    monitor = RequestMonitor(); now = [0.0]; monitor.clock = lambda: now[0]
    token = monitor.begin("POST", "/v1/chat/completions")
    now[0] = 1; monitor.stage("queue")
    now[0] = 3; monitor.stage("upstream")
    now[0] = 4; assert monitor.first_output(); monitor.stage("receiving")
    now[0] = 5; monitor.status(200); monitor.finish(token)
    row = monitor.snapshot()["requests"][0]
    assert (row["queue_ms"], row["upstream_ms"], row["first_output_ms"], row["total_ms"]) == (2000, 2000, 4000, 5000)
    assert row["phase"] == "done" and not row["active"]


def test_monitor_is_bounded_and_does_not_record_arbitrary_paths():
    monitor = RequestMonitor(capacity=2)
    for _ in range(5):
        token = monitor.begin("POST", "/PRIVATE_RUNTIME_SESSION_AND_TOKEN")
        monitor.status(401); monitor.finish(token)
    result = monitor.snapshot()
    assert len(result["requests"]) == 2
    assert "PRIVATE_RUNTIME" not in json.dumps(result)
    assert result["requests"][0]["error_code"] == "HTTP_401"


def test_desktop_reuses_legacy_api_auth_without_key_creation_or_prompt(tmp_path, monkeypatch):
    from bridge_x.desktop_host import desktop_settings
    monkeypatch.setenv("BRIDGEX_DATA_DIR", str(tmp_path)); monkeypatch.delenv("BRIDGEX_LOCAL_KEY", raising=False)
    settings = Settings(provider="molab")
    assert desktop_settings(settings).local_api_key == "molab-local" and not (tmp_path / "local.key").exists()
    (tmp_path / "local.key").write_text("LEGACY_FIXTURE_" + "x" * 32)
    assert desktop_settings(settings).local_api_key == (tmp_path / "local.key").read_text()
    monkeypatch.setenv("BRIDGEX_LOCAL_KEY", "explicit-fixture")
    assert desktop_settings(settings).local_api_key == "molab-local"  # from_env supplies the explicit value.


@pytest.mark.parametrize("streaming", [False, True])
def test_actual_http_and_sse_record_codes_without_bodies_keys_or_file_contents(streaming):
    private = "PRIVATE_FIXTURE_DO_NOT_LOG"
    monitor = RequestMonitor()
    class Provider:
        async def generate(self, req, messages):
            monitor.stage("queue"); await asyncio.sleep(.025)
            monitor.stage("upstream"); await asyncio.sleep(.025)
            yield TextDelta(private); yield Finish("stop")
    settings = Settings(journal_path=":memory:", local_api_key=private)
    with TestClient(create_app(settings, Provider(), monitor=monitor)) as client:
        response = client.post("/v1/chat/completions", headers={"Authorization": "Bearer " + private},
                               json={"messages": [{"role": "user", "content": private}], "stream": streaming})
        assert response.status_code == 200
        client.post("/v1/chat/completions", json={})
    result = monitor.snapshot()
    assert private not in json.dumps(result)
    assert {row["http"] for row in result["requests"]} == {200, 401}
    successful = next(row for row in result["requests"] if row["http"] == 200)
    assert successful["request_bytes"] > len(private) and successful["response_bytes"] > len(private)
    assert successful["queue_ms"] >= 20 and successful["upstream_ms"] >= 20
    assert successful["first_output_ms"] >= 40 and successful["phase"] == "done"


def test_sse_error_with_http_200_is_visible_as_failure():
    monitor = RequestMonitor()
    class Provider:
        async def generate(self, req, messages):
            yield Failed("UPSTREAM_CONTEXT_LIMIT", "PRIVATE_ERROR_TEXT")
    with TestClient(create_app(Settings(journal_path=":memory:"), Provider(), monitor=monitor)) as client:
        response = client.post("/v1/chat/completions", headers={"Authorization": "Bearer molab-local"},
                               json={"messages": [{"role": "user", "content": "fixture"}], "stream": True})
        assert response.status_code == 200 and "[DONE]" not in response.text
    row = monitor.snapshot()["requests"][0]
    assert row["http"] == 200 and row["phase"] == "failed" and row["error_code"] == "UPSTREAM_CONTEXT_LIMIT"


def wait_for(host, predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = host.snapshot()
        if predicate(result): return result
        time.sleep(.02)
    pytest.fail("Desktop host did not reach expected state: " + str(host.snapshot()))


def test_owned_proxy_starts_without_key_files_and_stops_cleanly(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIDGEX_DATA_DIR", str(tmp_path))
    journal = tmp_path / "state.sqlite3"
    host = GatewayHost(Settings(provider="fake", journal_path=str(journal)), port=0)
    assert host.start()
    try:
        ready = wait_for(host, lambda state: state["state"] == "running")
        connection = HTTPConnection("127.0.0.1", ready["port"], timeout=3)
        connection.request("GET", "/health"); response = connection.getresponse()
        assert response.status == 200 and json.loads(response.read())["provider"] == "fake"
        connection.close()
        assert not (tmp_path / "local.key").exists()
        assert not host.start()  # One owner, no duplicate process.
    finally:
        host.stop(); assert host.wait()
    assert host.snapshot()["state"] == "stopped"
    with closing(sqlite3.connect(journal)) as database:
        assert database.execute("PRAGMA quick_check").fetchone() == ("ok",)
    records = [json.loads(line) for line in journal.with_suffix(".requests.jsonl").read_text().splitlines()]
    assert records[-1]["http"] == 200 and records[-1]["phase"] == "done"
    assert records[-1]["schema"] == 1 and records[-1]["path"] == "/health"
    # Reuse the same owner after a graceful stop, retaining its existing SQLite state.
    assert host.start()
    try: wait_for(host, lambda state: state["state"] == "running")
    finally: host.stop(); assert host.wait()


def test_busy_port_leaves_existing_listener_and_unused_journal_untouched(tmp_path):
    with socket.socket() as existing:
        existing.bind(("127.0.0.1", 0)); existing.listen()
        path = tmp_path / "unused.sqlite3"
        host = GatewayHost(Settings(journal_path=str(path)), existing.getsockname()[1])
        host.start(); result = wait_for(host, lambda state: state["state"] == "error")
        assert result["error"] == "PORT_UNAVAILABLE" and not path.exists()
        assert host.wait() and existing.getsockname()[1] > 0


@pytest.mark.skipif(os.name != "nt", reason="Native Windows Tk acceptance")
def test_native_language_change_preserves_fields_and_requires_no_login(tmp_path, monkeypatch):
    import tkinter as tk
    from bridge_x.desktop import Desktop
    monkeypatch.setenv("BRIDGEX_DATA_DIR", str(tmp_path))
    class Host:
        port = 8787; thread = None; app = None
        def snapshot(self):
            return {"state": "stopped", "error": None, "port": 8787, "provider": "fake", "model": "bridge-x-fake", "rate": {}, "requests": [], "events": []}
        def start(self): pass
        def stop(self): pass
    root = tk.Tk(); root.withdraw()
    try:
        window = Desktop(root, Settings(provider="fake", molab_config_path=str(tmp_path / "none.json")), host=Host())
        window.fields["chat_url"].set("https://fixture.sb.molab.run/api/ai/chat")
        window.lang.set("RUS"); window.change_language()
        assert "Монитор прокси" in root.title()
        window.lang.set("ENG"); window.change_language()
        assert "Proxy Monitor" in root.title()
        assert window.fields["chat_url"].get().endswith("/api/ai/chat")
        window.filter.current(1); window.lang.set("RUS"); window.change_language()
        assert window.filter.current() == 1 and window.filter.get() == "Ошибки / отмены"
        assert not (tmp_path / "local.key").exists()
    finally: root.destroy()


def test_request_log_is_rotated_private_and_flushes_on_close(tmp_path):
    from bridge_x.request_log import RequestLog
    path = tmp_path / "requests.jsonl"
    log = RequestLog(path, max_bytes=1500, capacity=100)
    monitor = RequestMonitor(); monitor.writer = log
    for _ in range(24):
        token = monitor.begin("POST", "/PRIVATE_SESSION_AND_TOKEN")
        monitor.stage("failed", "PRIVATE_ERROR_DETAIL"); monitor.status(413); monitor.finish(token)
    log.close()
    assert not log.thread.is_alive() and log.status() == {"failed": False, "dropped": 0}
    files = list(tmp_path.glob("requests.jsonl*"))
    assert len(files) == 4 and all(file.stat().st_size <= 1500 for file in files)
    records = [json.loads(line) for file in files for line in file.read_text().splitlines()]
    assert all(row["error_code"] == "OTHER_ERROR" and row["phase"] == "failed" for row in records)
    assert "PRIVATE_" not in json.dumps(records) and all(row["at"].endswith("+00:00") for row in records)


def test_failed_request_log_surfaces_status_without_stopping_requests(tmp_path):
    from bridge_x.request_log import RequestLog
    # Directory in place of the log; no raw OS error or private path is exposed.
    log = RequestLog(tmp_path)
    log.close()
    monitor = RequestMonitor(); monitor.writer = log
    token = monitor.begin("POST", "/v1/chat/completions"); monitor.status(200); monitor.finish(token)
    assert log.status() == {"failed": True, "dropped": 1}
    assert monitor.snapshot()["requests"][0]["phase"] == "done"


def test_connection_save_validates_before_atomic_replacement(tmp_path):
    from bridge_x.desktop_host import save_connection
    from bridge_x.errors import BridgeError
    target = tmp_path / "connection.json"
    target.write_text('{"old":"private fixture"}')
    settings = Settings(molab_config_path=str(target))
    invalid = {"chat_url": "https://fixture.sb.molab.run/api/ai/chat", "marimo_session_id": "YOUR_SESSION_ID", "marimo_server_token": ""}
    with pytest.raises(BridgeError): save_connection(settings, invalid)
    assert json.loads(target.read_text()) == {"old": "private fixture"}
    valid = {**invalid, "marimo_session_id": "fixture-session", "http_headers": {"X-Fixture": "test"}}
    save_connection(settings, valid)
    assert json.loads(target.read_text()) == valid and len(list(tmp_path.iterdir())) == 1


@pytest.mark.asyncio
async def test_cancelled_http_request_is_not_recorded_as_success():
    from bridge_x.monitoring import MonitorMiddleware
    monitor = RequestMonitor(); started = asyncio.Event()
    async def app(scope, receive, send):
        monitor.stage("queue"); started.set(); await asyncio.Future()
    async def receive(): return {"type": "http.disconnect"}
    async def send(message): pass
    task = asyncio.create_task(MonitorMiddleware(app, monitor)({"type": "http", "method": "POST", "path": "/v1/chat/completions"}, receive, send))
    await started.wait(); task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    row = monitor.snapshot()["requests"][0]
    assert row["phase"] == "cancelled" and row["http"] is None and not row["active"]
    assert monitor.current.get() is None
