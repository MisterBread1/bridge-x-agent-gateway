"""Verify and test a complete ZIP in a fresh isolated Python environment."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
import venv
from zipfile import ZipFile
from bridge_x import __version__


def verify_members(archive):
    prefix = f'bridge-x-{__version__}/'
    names = archive.namelist()
    if len(names) != len(set(names)) or sum(i.file_size for i in archive.infolist()) > 50_000_000:
        raise ValueError('Duplicate members or oversized release')
    for name in names:
        path = PurePosixPath(name)
        if (not name.startswith(prefix) or path.is_absolute() or '..' in path.parts
                or '\\' in name or name.endswith('/')):
            raise ValueError('Invalid release member path')
    manifest = archive.read(prefix + 'FILE_SHA256SUMS.txt').decode('ascii')
    checked = set()
    for line in manifest.splitlines():
        digest, rel = line.split('  ', 1)
        full = prefix + rel
        if full in checked or hashlib.sha256(archive.read(full)).hexdigest() != digest:
            raise ValueError('Release file checksum mismatch')
        checked.add(full)
    if checked != set(names) - {prefix + 'FILE_SHA256SUMS.txt'}:
        raise ValueError('Release manifest does not exactly cover archive files')
    return prefix, len(names)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--work-dir', type=Path, required=True)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    work_root = args.work_dir.resolve()
    with tempfile.TemporaryDirectory(prefix='bridge-x-verify-', dir=work_root) as temp:
        workspace = Path(temp).resolve()
        assert workspace.is_relative_to(work_root)
        with ZipFile(args.archive) as archive:
            prefix, count = verify_members(archive)
            for name in archive.namelist():
                target = workspace / name
                assert target.resolve().is_relative_to(workspace)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
        package = workspace / prefix.rstrip('/')
        environment = workspace / 'clean-python'
        venv.create(environment, with_pip=True)
        python = environment / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        env = {k: v for k, v in os.environ.items() if not k.startswith('BRIDGEX_') and k != 'PYTHONPATH'}
        env.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
        commands = [
            ['-m', 'pip', 'install', '-r', 'requirements-dev.txt'],
            ['-m', 'pip', 'check'],
            ['-m', 'compileall', '-q', 'bridge_x', 'bridge_x_test_runner', 'tests', 'tools'],
            ['-m', 'pytest', '-q', '-ra'],
            ['LOCAL_HTTP_ACCEPTANCE.py', '--report', str(workspace / 'http-acceptance.json')],
            ['-m', 'tools.native_css_acceptance'],
            ['-m', 'tools.continuity_acceptance'],
            ['-m', 'bridge_x', 'doctor', '--provider', 'fake', '--port', '0'],
            ['-m', 'bridge_x', '--provider', 'fake', '--check-config'],
        ]
        for command in commands:
            subprocess.run([str(python), '-B', *command], cwd=package, env=env, check=True, timeout=300)
        # Install the actual package, then probe it outside the extracted
        # source directory so imports cannot accidentally use the checkout.
        subprocess.run([str(python), '-m', 'pip', 'install', '--no-deps', str(package)],
                       cwd=workspace, env=env, check=True, timeout=300)
        probe = """from importlib.resources import files
from bridge_x.config import Settings
from bridge_x.gateway import create_app
from fastapi.testclient import TestClient
from bridge_x.desktop_host import GatewayHost
from bridge_x.desktop_i18n import text
from bridge_x.monitoring import RequestMonitor
from bridge_x.request_log import RequestLog
assert files('bridge_x').joinpath('ui/index.html').is_file()
assert text('requests', 'ru') == 'Запросы'
with TestClient(create_app(Settings(journal_path=':memory:'), monitor=RequestMonitor())) as client:
    assert client.get('/health').status_code == 200
    assert client.get('/ui/').status_code == 404
with TestClient(create_app(Settings(journal_path=':memory:')), base_url='http://127.0.0.1') as client:
    assert client.get('/ui/').status_code == 200
    assert client.get('/ui/assets/app.js').status_code == 200
    assert client.get('/ui/assets/locales.js').status_code == 200
    assert client.get('/ui/api/snapshot').status_code == 401
"""
        subprocess.run([str(python), '-I', '-c', probe], cwd=workspace, env=env, check=True, timeout=30)
        entry = environment / ('Scripts/bridge-x.exe' if os.name == 'nt' else 'bin/bridge-x')
        subprocess.run([str(entry), 'doctor', '--provider', 'fake', '--port', '0'], cwd=workspace, env=env, check=True, timeout=30)
    print(json.dumps({'version': __version__, 'members': count, 'clean_zip_environment': True,
                      'checks': len(commands) + 3, 'installed_package_ui': True, 'installed_native_console': True,
                      'passed': True, 'live_provider': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
