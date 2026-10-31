"""Build an allowlisted release without changing the checkout or older assets."""
import argparse
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
from bridge_x import __version__


def release_members(root):
    root = Path(root).resolve()
    names = ['README.md', 'CONTRIBUTING.md', 'CHANGELOG.md', 'RELEASE_NOTES.md',
             'SECURITY.md', '.gitignore', 'requirements.txt', 'requirements-dev.txt',
             'pytest.ini', 'LOCAL_HTTP_ACCEPTANCE.py', 'LIVE_CHECK.py', 'start.bat',
             'examples/.molab_local.example.json']
    for directory, suffixes in [('bridge_x', ('.py',)), ('bridge_x_test_runner', ('.py',)),
                                ('tests', ('.py',)), ('tools', ('.py',)),
                                ('docs', ('.md',)), ('.github', ('.md', '.yml', '.yaml'))]:
        names.extend(p.relative_to(root).as_posix() for p in (root / directory).rglob('*')
                     if p.suffix in suffixes and '__pycache__' not in p.parts)
    members = {}
    for name in sorted(set(names)):
        path = root / name
        if (not path.resolve().is_relative_to(root)
                or any(part.is_symlink() for part in (path, *path.parents) if part != root)):
            raise ValueError('Release input must not be a symlink or escape the project')
        members[name] = path.read_bytes()
    members['FILE_SHA256SUMS.txt'] = ''.join(hashlib.sha256(data).hexdigest() + '  ' + name + '\n'
                                           for name, data in sorted(members.items())).encode()
    return members


def _write_immutable(path, data):
    try:
        with path.open('xb') as stream:
            stream.write(data)
    except FileExistsError:
        if path.read_bytes() != data:
            raise FileExistsError('Output exists with different bytes; choose a new output directory') from None


def build_release(root, output_dir):
    members = release_members(root)
    buffer = io.BytesIO()
    prefix = f'bridge-x-{__version__}/'
    with ZipFile(buffer, 'w', ZIP_DEFLATED) as archive:
        for name, data in sorted(members.items()):
            info = ZipInfo(prefix + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compress_type=ZIP_DEFLATED)
    data = buffer.getvalue()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f'bridge-x-{__version__}-complete.zip'
    digest = hashlib.sha256(data).hexdigest()
    _write_immutable(target, data)
    _write_immutable(output_dir / 'SHA256SUMS.txt', (digest + '  ' + target.name + '\n').encode('ascii'))
    return {'archive': target.name, 'members': len(members), 'sha256': digest}


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=root / 'artifacts')
    args = parser.parse_args()
    print(json.dumps(build_release(root, args.output_dir)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
