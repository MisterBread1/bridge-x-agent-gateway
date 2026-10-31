"""The release gate rejects incomplete manifests and unsafe ZIP structures."""
import hashlib
import io
from pathlib import Path
from zipfile import ZipFile
import pytest
from bridge_x import __version__
from tools.verify_release import verify_members
from tools.audit_release import scan

PREFIX = f'bridge-x-{__version__}/'


def archive(files):
    buffer = io.BytesIO()
    with ZipFile(buffer, 'w') as z:
        for name, data in files:
            z.writestr(name, data)
    buffer.seek(0)
    return ZipFile(buffer)


def test_manifest_gate_accepts_exact_checksum_coverage():
    data = b'public fixture'
    manifest = (hashlib.sha256(data).hexdigest() + '  README.md\n').encode()
    with archive([(PREFIX+'README.md', data), (PREFIX+'FILE_SHA256SUMS.txt', manifest)]) as z:
        assert verify_members(z) == (PREFIX, 2)


@pytest.mark.parametrize('extra', ['../escape.py', 'other-root/file.py', 'folder\\file.py'])
def test_manifest_gate_rejects_unsafe_or_wrong_root(extra):
    with archive([(extra, b'fixture')]) as z, pytest.raises(ValueError):
        verify_members(z)


def test_manifest_gate_rejects_unlisted_file():
    with archive([(PREFIX+'README.md', b'fixture'), (PREFIX+'FILE_SHA256SUMS.txt', b'')]) as z, pytest.raises(ValueError):
        verify_members(z)


def test_media_audit_only_accepts_named_gif_assets():
    valid = (Path(__file__).resolve().parents[1] / 'docs/assets/bridge-x-demo.gif').read_bytes()
    assert scan([('docs/assets/bridge-x-demo.gif', valid)]) == []
    assert scan([('docs/assets/bridge-x-demo.gif', b'not a GIF')])
    assert scan([('unapproved.bin', b'\xff')])
