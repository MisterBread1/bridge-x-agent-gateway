"""Publication regressions: complete docs, immutable outputs, no private state."""
import hashlib
from pathlib import Path
import shutil
from zipfile import ZipFile
import pytest
from bridge_x import __version__
from tools.build_release import build_release

ROOT = Path(__file__).resolve().parents[1]
PREFIX = f'bridge-x-{__version__}/'


def test_complete_archive_has_stable_prefix_docs_and_valid_checksums(tmp_path):
    result = build_release(ROOT, tmp_path)
    with ZipFile(tmp_path / result['archive']) as archive:
        for name in ['CONTRIBUTING.md', '.github/PULL_REQUEST_TEMPLATE.md',
                     '.github/workflows/ci.yml', '.github/workflows/release.yml',
                     'docs/FILE_GUIDE.md', 'docs/ARCHITECTURE.md', 'start.bat',
                     'docs/assets/bridge-x-demo.gif', 'docs/assets/bridge-x-demo-ledger.gif',
                     '.github/ISSUE_TEMPLATE/bug_report.yml', 'tools/requirements-media.txt']:
            assert archive.read(PREFIX + name) == (ROOT / name).read_bytes()
        for line in archive.read(PREFIX + 'FILE_SHA256SUMS.txt').decode().splitlines():
            digest, name = line.split('  ', 1)
            assert hashlib.sha256(archive.read(PREFIX + name)).hexdigest() == digest
        assert not any(name.endswith(('.zip', '.sqlite3', '.pyc', '.log')) for name in archive.namelist())
        assert PREFIX + '.molab_local.json' not in archive.namelist()
        assert all(name.startswith(PREFIX) for name in archive.namelist())


def test_build_is_repeatable_and_never_changes_checkout_manifest(tmp_path):
    before = (ROOT / 'FILE_SHA256SUMS.txt').read_bytes()
    first = build_release(ROOT, tmp_path / 'one')
    second = build_release(ROOT, tmp_path / 'two')
    assert first == second
    assert (tmp_path / 'one' / first['archive']).read_bytes() == (tmp_path / 'two' / second['archive']).read_bytes()
    assert build_release(ROOT, tmp_path / 'one') == first
    assert (ROOT / 'FILE_SHA256SUMS.txt').read_bytes() == before


def test_existing_different_asset_is_never_overwritten(tmp_path):
    target = tmp_path / f'bridge-x-{__version__}-complete.zip'
    target.write_bytes(b'previous-publication')
    with pytest.raises(FileExistsError):
        build_release(ROOT, tmp_path)
    assert target.read_bytes() == b'previous-publication'


def test_private_files_and_unlisted_root_files_are_excluded(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    for directory in ['bridge_x', 'bridge_x_test_runner', 'tests', 'tools', 'docs', '.github', 'examples']:
        shutil.copytree(ROOT / directory, source / directory, ignore=shutil.ignore_patterns('__pycache__'))
    for path in ROOT.iterdir():
        if path.is_file() and path.suffix != '.zip':
            shutil.copyfile(path, source / path.name)
    private = ('LOCAL_' + 'UNLISTED_') * 3
    (source / '.molab_local.json').write_text(private)
    (source / 'private-note.txt').write_text(private)
    (source / 'state.sqlite3').write_bytes(private.encode())
    result = build_release(source, tmp_path / 'output')
    with ZipFile(tmp_path / 'output' / result['archive']) as archive:
        assert not any(private.encode() in archive.read(name) for name in archive.namelist())
