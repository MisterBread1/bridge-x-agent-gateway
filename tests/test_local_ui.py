"""Actual operator routes use isolated state and never run client tools."""
import json
import sqlite3
import pytest
from fastapi.testclient import TestClient
from bridge_x.config import Settings
from bridge_x.gateway import create_app
from bridge_x.errors import BridgeError
from bridge_x.journal import Journal
from bridge_x.tool_models import ToolCall
from bridge_x.user_state import personal_key, backup_journal
from bridge_x.paths import InstanceLock

AUTH = {"Authorization": "Bearer fixture-local-key"}


def settings(tmp_path):
    return Settings(journal_path=str(tmp_path / "state.sqlite3"), local_api_key="fixture-local-key",
                    molab_config_path=str(tmp_path / "private.json"))


def test_real_state_auth_origin_and_safe_config(tmp_path):
    app = create_app(settings(tmp_path))
    app.state.journal.deliver([ToolCall("call-real", "Read", {}, "schema")], "PRIVATE_SESSION")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/ui/api/snapshot").status_code == 401
        assert client.get("/ui/api/snapshot", headers={**AUTH, "Origin": "https://foreign.invalid"}).status_code == 403
        assert client.get("/ui/api/snapshot", headers={**AUTH, "Host": "foreign.invalid"}).status_code == 403
        page = client.get("/ui/")
        assert page.status_code == 200 and "frame-ancestors 'none'" in page.headers["Content-Security-Policy"]
        assert client.get("/ui/assets/app.js").status_code == 200
        result = client.get("/ui/api/snapshot", headers=AUTH)
        assert result.json()["operations"][0]["id"] == "call-real"
        assert "PRIVATE_SESSION" not in result.text
        value = {"chat_url": "https://fixture.sb.molab.run/api/ai/chat",
                 "marimo_session_id": "private-session-fixture", "marimo_server_token": "private-token-fixture"}
        saved = client.post("/ui/api/config", headers=AUTH, json=value)
        assert saved.status_code == 200
        assert json.loads((tmp_path / "private.json").read_text()) == value
        public = client.get("/ui/api/config", headers=AUTH).text + saved.text
        assert "private-token-fixture" not in public and "private-session-fixture" not in public
        assert client.get("/ui/api/snapshot?before=-1", headers=AUTH).status_code == 400


def test_runtime_check_is_explicit_readonly_by_default(tmp_path, monkeypatch):
    from bridge_x import molab_runtime
    (tmp_path / "private.json").write_text(json.dumps({"chat_url": "https://fixture.sb.molab.run/api/ai/chat", "marimo_session_id": "fixture"}))
    called = []
    def check(config, *, configure):
        called.append(configure)
        return {"mode": "code_mode", "changed": False}
    monkeypatch.setattr(molab_runtime, "ensure_native_mode", check)
    with TestClient(create_app(settings(tmp_path)), base_url="http://127.0.0.1") as client:
        client.get("/ui/api/snapshot", headers=AUTH)
        assert not called
        result = client.post("/ui/api/check-runtime", headers=AUTH, json={})
        assert result.json()["model_generation_checked"] is False and called == [False]
        client.post("/ui/api/check-runtime", headers=AUTH, json={"configure": True})
        assert called == [False, True]


def test_demo_key_cannot_save_config_and_invalid_body_does_not_reflect_input(tmp_path):
    cfg = settings(tmp_path)
    from dataclasses import replace
    with TestClient(create_app(replace(cfg, local_api_key="molab-local")), base_url="http://127.0.0.1") as client:
        result = client.post("/ui/api/config", headers={"Authorization": "Bearer molab-local"}, json={})
        assert result.status_code == 403 and not (tmp_path / "private.json").exists()
    with TestClient(create_app(cfg), base_url="http://127.0.0.1") as client:
        result = client.post("/ui/api/config", headers=AUTH, json={"chat_url": "PRIVATE_INVALID_VALUE"})
        assert result.status_code >= 400 and "PRIVATE_INVALID_VALUE" not in result.text


def test_personal_key_is_stable_and_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIDGEX_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("BRIDGEX_LOCAL_KEY", raising=False)
    first = personal_key()
    assert len(first) >= 32 and personal_key() == first
    (tmp_path / "local.key").write_text("invalid")
    with pytest.raises(BridgeError):
        personal_key()
    assert (tmp_path / "local.key").read_text() == "invalid"


def test_backup_preserves_committed_wal_state_and_rejects_existing_output(tmp_path):
    source, target = tmp_path / "live.sqlite3", tmp_path / "backup.sqlite3"
    db = sqlite3.connect(source)
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("CREATE TABLE fixture(value); INSERT INTO fixture VALUES(42);")
        backup_journal(source, target)
        with sqlite3.connect(target) as backup:
            assert backup.execute("SELECT value FROM fixture").fetchone() == (42,)
        before = target.read_bytes()
        with pytest.raises(BridgeError):
            backup_journal(source, target)
        assert target.read_bytes() == before
    finally:
        db.close()


def test_same_journal_instance_lock_blocks_second_process_owner(tmp_path):
    path = str(tmp_path / "state.sqlite3")
    with InstanceLock(path):
        with pytest.raises(BridgeError) as error:
            with InstanceLock(path):
                pass
        assert error.value.code == "JOURNAL_IN_USE"
    with InstanceLock(path):
        pass
