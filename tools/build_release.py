"""Allowlisted publication archive. Does not read any local credentials."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from bridge_x import __version__


def main():
    root = Path(__file__).resolve().parents[1]
    names = ['README.md', 'CHANGELOG.md', 'RELEASE_NOTES.md', 'SECURITY.md', '.gitignore',
             'requirements.txt', 'requirements-dev.txt', 'pytest.ini', 'LOCAL_HTTP_ACCEPTANCE.py', 'LIVE_CHECK.py', 'start.bat']
    for directory, suffix in [('bridge_x', '.py'), ('bridge_x_test_runner', '.py'), ('tests', '.py'), ('tools', '.py'), ('docs', '.md')]:
        names.extend(p.relative_to(root).as_posix() for p in (root / directory).rglob('*' + suffix)
                     if '__pycache__' not in p.parts)
    names.append('examples/.molab_local.example.json')
    members = {name: (root / name).read_bytes() for name in sorted(set(names))}
    members['FILE_SHA256SUMS.txt'] = ''.join(hashlib.sha256(data).hexdigest() + '  ' + name + '\n'
                                           for name, data in sorted(members.items())).encode()
    (root / 'FILE_SHA256SUMS.txt').write_bytes(members['FILE_SHA256SUMS.txt'])
    target = root.parent / f'bridge-x-{__version__}.zip'
    with ZipFile(target, 'w', ZIP_DEFLATED) as archive:
        for name, data in sorted(members.items()):
            info_name = root.name + '/' + name
            archive.writestr(info_name, data)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (root.parent / 'SHA256SUMS.txt').write_text(digest + '  ' + target.name + '\n', encoding='ascii')
    print(json.dumps({'archive': target.name, 'members': len(members), 'sha256': digest}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
