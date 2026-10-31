"""Release-only configuration and loopback startup checks, with no upstream."""
import os
from pathlib import Path
import socket
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args, **env_values):
    env = {k: v for k, v in os.environ.items() if not k.startswith('BRIDGEX_')}
    env.update(env_values)
    return subprocess.run([sys.executable, '-m', 'bridge_x', *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=15)


def test_missing_config_is_safe_and_does_not_create_database(tmp_path):
    database = tmp_path / 'unused.sqlite3'
    result = run_cli('--check-config', BRIDGEX_MOLAB_CONFIG=str(tmp_path / 'missing.json'), BRIDGEX_JOURNAL_PATH=str(database))
    assert result.returncode == 2 and 'MOLAB_CONFIG_MISSING' in result.stdout
    assert not database.exists()


def test_example_is_rejected_until_placeholders_are_replaced():
    result = run_cli('--check-config', BRIDGEX_MOLAB_CONFIG=str(ROOT / 'examples/.molab_local.example.json'))
    assert result.returncode == 2 and 'MOLAB_CONFIG_PLACEHOLDER' in result.stdout


def test_explicit_fake_provider_overrides_unrelated_upstream_environment():
    result = run_cli('--provider', 'fake', '--check-config', BRIDGEX_PROVIDER='invalid')
    assert result.returncode == 0 and 'provider=fake' in result.stdout


def test_empty_optional_token_is_valid_without_network(tmp_path):
    config = tmp_path / 'config.json'
    config.write_text('{"chat_url":"https://fixture.sb.molab.run/api/ai/chat","marimo_session_id":"DEMO_ONLY","marimo_server_token":""}', encoding='utf-8')
    result = run_cli('--check-config', BRIDGEX_MOLAB_CONFIG=str(config))
    assert result.returncode == 0 and 'upstream availability is not verified' in result.stdout


def test_busy_loopback_port_reports_error_without_touching_other_process():
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0))
        occupied.listen()
        result = run_cli('--provider', 'fake', '--port', str(occupied.getsockname()[1]))
        assert result.returncode == 2 and 'PORT_UNAVAILABLE' in result.stdout
        assert occupied.getsockname()[1] > 0


def test_configure_never_overwrites_existing_local_file(tmp_path, monkeypatch):
    from tools import configure
    (tmp_path / 'tools').mkdir()
    (tmp_path / 'examples').mkdir()
    template = tmp_path / 'examples/.molab_local.example.json'
    template.write_text('{"demo":true}', encoding='utf-8')
    monkeypatch.setattr(configure, '__file__', str(tmp_path / 'tools/configure.py'))
    assert configure.main() == 0
    target = tmp_path / '.molab_local.json'
    assert target.read_bytes() == template.read_bytes()
    target.write_bytes(b'LOCAL_DEMO_VALUE')
    assert configure.main() == 0 and target.read_bytes() == b'LOCAL_DEMO_VALUE'
