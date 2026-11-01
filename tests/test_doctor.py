"""Doctor/report checks are read-only and omit all operator-controlled values."""
import json
import socket
import sqlite3
import subprocess
import sys
import pytest
from fastapi.testclient import TestClient
from bridge_x.config import Settings
from bridge_x.doctor import inspect
from bridge_x.gateway import create_app
from bridge_x.journal import Journal
from .test_continuity import AUTH, history
from bridge_x.providers import TextDelta, Finish


def test_doctor_does_not_construct_provider_start_server_or_create_database(tmp_path, monkeypatch):
    import bridge_x.providers
    monkeypatch.setattr(bridge_x.providers, "make_provider", lambda *a: pytest.fail("doctor constructed provider"))
    path = tmp_path / "absent.sqlite3"
    result = inspect(Settings(journal_path=str(path)), port=0)
    assert not path.exists()
    assert not any(item["status"] == "ERROR" for item in result["checks"])
    assert "NETWORK_TARGET" not in {item["code"] for item in result["checks"]}


def test_private_invalid_configuration_is_never_printed(tmp_path, monkeypatch, capsys):
    from bridge_x.doctor import run
    path = tmp_path / "private.json"
    private = "PRIVATE_SENTINEL_DO_NOT_PUBLISH"
    path.write_text(json.dumps({"chat_url": "https://" + private + ".invalid", "marimo_session_id": private}))
    monkeypatch.setenv("BRIDGEX_MOLAB_CONFIG", str(path))
    monkeypatch.setenv("BRIDGEX_LOCAL_KEY", private)
    monkeypatch.setenv("BRIDGEX_PROVIDER", "molab")
    report = tmp_path / "report.json"
    assert run(0, report=report) == 2
    assert private not in capsys.readouterr().out + report.read_text()
    assert str(path) not in report.read_text()
    assert run(0, report=report) == 2  # never overwrite a report


def test_doctor_reports_busy_port_without_stopping_listener(tmp_path):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        result = inspect(Settings(journal_path=str(tmp_path / "state.sqlite3")), port)
        check = next(item for item in result["checks"] if item["code"] == "LOCAL_PORT")
        assert check["status"] == "WARNING"
        assert listener.getsockname()[1] == port


def test_doctor_reads_old_schema_without_running_migration(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE operations(state TEXT, result_kind TEXT); INSERT INTO operations VALUES('ACKNOWLEDGED','unknown'); PRAGMA user_version=3;")
    before = path.read_bytes()
    result = inspect(Settings(journal_path=str(path)), 0)
    assert next(item for item in result["checks"] if item["code"] == "PENDING_OPERATIONS")["status"] == "WARNING"
    assert path.read_bytes() == before


def test_sanitized_report_omits_commands_prompts_ids_and_unknown_fields(tmp_path, caplog):
    import logging
    private = "PRIVATE_SENTINEL_DO_NOT_PUBLISH"
    journal = Journal(":memory:")
    try:
        with caplog.at_level(logging.INFO, logger="bridge_x.events"):
            journal.diagnostic(private, "request_received", private, command=private, tool_type=private, outcome=private)
        report = json.dumps(journal.safe_report())
        assert private not in report + caplog.text and "req_" in report
    finally:
        journal.close()


def test_report_endpoint_is_authenticated_and_has_structured_safe_timeline():
    class Prose:
        async def generate(self, req, messages):
            yield TextDelta("PRIVATE_SENTINEL_DO_NOT_PUBLISH")
            yield Finish("stop")
    with TestClient(create_app(Settings(journal_path=":memory:"), provider=Prose())) as client:
        assert client.get("/diagnostics/report").status_code == 401
        response = client.post("/v1/chat/completions", headers=AUTH, json={"messages": history(), "tools": []})
        assert response.status_code == 200
        report = client.get("/diagnostics/report", headers=AUTH)
        assert "PRIVATE_SENTINEL_DO_NOT_PUBLISH" not in report.text
        events = {item["event"] for item in report.json()["events"]}
        assert {"request_received", "provider_generation_started", "tool_receipt_received", "tool_outcome_classified", "provider_finish_received", "completion_delivered"} <= events


@pytest.mark.parametrize("provider", ["fake", "molab"])
def test_doctor_cli_works_without_importing_optional_server_dependencies(tmp_path, provider):
    # -S hides site packages: doctor must diagnose missing dependencies instead
    # of failing while importing FastAPI/httpx/Uvicorn before its own checks.
    import os
    env = {key: value for key, value in os.environ.items() if not key.startswith("BRIDGEX_")}
    env["BRIDGEX_PROVIDER"] = provider
    result = subprocess.run([sys.executable, "-S", "-m", "bridge_x", "doctor", "--port", "0"], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == (0 if provider == "fake" else 2), result.stderr
    assert "WARNING DEPENDENCIES" in result.stdout and "PASS PYTHON" in result.stdout


def test_network_probe_is_explicit_local_only(tmp_path, monkeypatch):
    import bridge_x.doctor as doctor
    calls = []
    class Connection:
        def __init__(self, host, port, timeout): calls.append((host, port))
        def request(self, method, path): calls.append((method, path))
        def getresponse(self):
            class Response:
                status = 200
                def read(self, size):
                    from bridge_x import __version__
                    return json.dumps({"status": "ok", "version": __version__}).encode()
            return Response()
        def close(self): pass
    monkeypatch.setattr(doctor.http.client, "HTTPConnection", Connection)
    settings = Settings(journal_path=str(tmp_path / "state.sqlite3"))
    inspect(settings, 18787)
    assert calls == []
    result = inspect(settings, 18787, network=True)
    assert calls == [("127.0.0.1", 18787), ("GET", "/health")]
    assert next(c for c in result["checks"] if c["code"] == "LOCAL_HEALTH")["status"] == "PASS"
