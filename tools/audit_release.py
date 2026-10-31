"""Offline publication checks. Reports locations and categories, never values."""
import argparse
import json
from pathlib import Path
import re
from zipfile import ZipFile

APPROVED_MEDIA = {'docs/assets/bridge-x-demo.gif', 'docs/assets/bridge-x-demo-ledger.gif'}


def scan(members):
    findings = []
    for name, data in members:
        parts = Path(name).parts
        forbidden = {'.git', '.venv', 'venv', '__pycache__', '.pytest_cache', '.hypothesis', '.audit-tmp'}
        if forbidden.intersection(parts) or Path(name).name in {'.molab_local.json', '.env'} or name.endswith(('.sqlite3', '.sqlite3-wal', '.sqlite3-shm', '.pyc', '.log', '.dmp')):
            findings.append({'file': name, 'kind': 'private_or_generated_file'})
        relative = name.replace('\\', '/')
        if relative.startswith('bridge-x-') and '/' in relative:
            relative = relative.split('/', 1)[1]
        if relative in APPROVED_MEDIA:
            if not data.startswith((b'GIF87a', b'GIF89a')) or len(data) > 10_000_000:
                findings.append({'file': name, 'kind': 'invalid_demo_gif'})
            continue
        try:
            text = data.decode('utf-8-sig')
        except UnicodeError:
            findings.append({'file': name, 'kind': 'unexpected_binary'})
            continue
        patterns = {'developer_home_path': r'[A-Za-z]:\\+(?:Users|Documents and Settings)\\+[^\\\s"\']+',
                    'private_infrastructure_ip': r'\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3})\b',
                    'credential_prefix': r'\b(?:ghp_|github_pat_|glpat-|sk-)[A-Za-z0-9_-]{20,}',
                    'private_key': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'}
        for kind, pattern in patterns.items():
            for match in re.finditer(pattern, text):
                findings.append({'file': name, 'line': text.count('\n', 0, match.start()) + 1, 'kind': kind})
    return findings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('target', type=Path)
    args = parser.parse_args()
    if args.target.is_file():
        with ZipFile(args.target) as archive:
            members = [(n, archive.read(n)) for n in archive.namelist() if not n.endswith('/')]
    else:
        members = [(p.relative_to(args.target).as_posix(), p.read_bytes()) for p in args.target.rglob('*') if p.is_file()]
    findings = scan(members)
    print(json.dumps({'files_scanned': len(members), 'findings': findings, 'passed': not findings}))
    return 0 if not findings else 1


if __name__ == '__main__':
    raise SystemExit(main())
