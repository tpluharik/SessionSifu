#!/usr/bin/env python3
"""Prepare unsigned metadata from already-built bytes. Never reads a private key.

Review the output, then sign it with OpenSSL in a separate trusted session.
Renewal verifies the old package and changes timestamps only, without a build.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--deb', type=Path, required=True)
    parser.add_argument('--release-dir', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--renew', type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r'\d+\.\d+\.\d+', args.version) or not re.fullmatch(r'[0-9a-f]{40}', args.source_commit):
        parser.error('A release version and exact source commit are required')
    if args.deb.is_symlink() or not args.deb.is_file():
        parser.error('The Debian artifact must be a regular file')
    actual = subprocess.check_output(['dpkg-deb', '-f', str(args.deb), 'Version'], text=True, timeout=10).strip()
    if actual != args.version:
        parser.error('Debian version does not match the requested release')
    provenance_path = args.release_dir / f'SessionSifu-{args.version}.provenance.json'
    provenance = json.loads(provenance_path.read_text())
    if provenance['version'] != args.version or provenance['source_commit'] != args.source_commit:
        parser.error('Provenance does not match the release commit')
    for entry in provenance['artifacts']:
        name = entry['name']
        if Path(name).name != name:
            parser.error('Invalid provenance artifact path')
        path = args.release_dir / name
        if path.is_symlink() or path.stat().st_size != entry['bytes'] or digest(path) != entry['sha256']:
            parser.error('Provenance artifact mismatch')
    size, sha = args.deb.stat().st_size, digest(args.deb)
    if not any(entry['name'] == args.deb.name and entry['sha256'] == sha for entry in provenance['artifacts']):
        parser.error('The Debian payload is not covered by release provenance')
    now = datetime.now(timezone.utc)
    issued = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    expires = (now + timedelta(days=45)).strftime('%Y-%m-%dT%H:%M:%SZ')
    base = f'https://github.com/tpluharik/SessionSifu/releases/download/v{args.version}/'
    common = dict(version=args.version, channel='stable', issued_at=issued,
                  expires_at=expires, minimum_version='3.5.35', size=size, sha256=sha,
                  notes='Distribution hardening. All channels use the same CI-built Debian bytes. Recovery data is preserved; log in afresh to activate extension changes.')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.renew:
        old = json.loads(args.renew.read_text())
        if old['version'] != args.version or old['sha256'] != sha or old['size'] != size:
            parser.error('Renewal may not change the existing package')
        old.update(issued_at=issued, expires_at=expires)
        (args.output_dir / args.renew.name).write_text(json.dumps(old, indent=2) + '\n')
        return
    v2 = {**common, 'package_url': base + args.deb.name}
    legacy = {**common, 'minimum_version': '2.5.0',
              'package_url': f'https://raw.githubusercontent.com/tpluharik/SessionSifu/main/updates/{args.deb.name}'}
    artifacts = {}
    for path in sorted(args.release_dir.iterdir()):
        if path.is_file() and not path.is_symlink() and (args.version in path.name or path.name == 'SHA256SUMS'):
            artifacts[path.name] = {'size': path.stat().st_size, 'sha256': digest(path), 'url': base + path.name}
    portable = dict(schema=1, channel='stable', version=args.version, issued_at=issued,
                    expires_at=expires, source_commit=args.source_commit, artifacts=artifacts)
    for name, value in [('stable-v2.json', v2), ('latest.json', legacy), ('portable-stable.json', portable)]:
        (args.output_dir / name).write_text(json.dumps(value, indent=2) + '\n')


if __name__ == '__main__':
    main()
