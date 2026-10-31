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
            ['-m', 'bridge_x', '--provider', 'fake', '--check-config'],
        ]
        for command in commands:
            subprocess.run([str(python), '-B', *command], cwd=package, env=env, check=True, timeout=300)
    print(json.dumps({'version': __version__, 'members': count, 'clean_zip_environment': True,
                      'checks': len(commands), 'passed': True, 'live_provider': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
