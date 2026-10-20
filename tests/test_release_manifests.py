#!/usr/bin/python3
"""Manifest preparation/renewal tests against a real package, without a key."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

root = Path(sys.argv[1]).resolve()
source = Path(sys.argv[2]).resolve()
version = subprocess.check_output(['dpkg-deb', '-f', str(source), 'Version'], text=True).strip()
commit = '1' * 40
with tempfile.TemporaryDirectory(prefix='sessionsifu-release-metadata-') as directory:
    temporary = Path(directory)
    release, output = temporary / 'release', temporary / 'unsigned'
    release.mkdir()
    package = release / source.name
    shutil.copyfile(source, package)
    contents = package.read_bytes()
    sha = hashlib.sha256(contents).hexdigest()
    provenance = release / f'SessionSifu-{version}.provenance.json'
    provenance.write_text(json.dumps({'version': version, 'source_commit': commit,
        'artifacts': [{'name': source.name, 'bytes': len(contents), 'sha256': sha}]}))
    command = [sys.executable, str(root / 'packaging/prepare-update-manifest.py'),
               '--version', version, '--deb', str(package), '--release-dir', str(release),
               '--source-commit', commit, '--output-dir', str(output)]
    subprocess.run(command, check=True, capture_output=True)
    legacy = json.loads((output / 'latest.json').read_text())
    current = json.loads((output / 'stable-v2.json').read_text())
    portable = json.loads((output / 'portable-stable.json').read_text())
    assert legacy['sha256'] == current['sha256'] == sha
    assert legacy['minimum_version'] == '2.5.0' and current['minimum_version'] == '3.5.35'
    assert current['package_url'].startswith('https://github.com/tpluharik/SessionSifu/releases/download/')
    assert legacy['package_url'].startswith('https://raw.githubusercontent.com/tpluharik/SessionSifu/main/updates/')
    assert portable['artifacts'][source.name]['sha256'] == sha
    old = dict(current, issued_at=(datetime.now(timezone.utc) - timedelta(days=40)).isoformat(),
               expires_at=(datetime.now(timezone.utc) + timedelta(days=5)).isoformat())
    old_path = temporary / 'old.json'
    old_path.write_text(json.dumps(old))
    subprocess.run(command + ['--renew', str(old_path)], check=True, capture_output=True)
    renewed = json.loads((output / 'old.json').read_text())
    assert renewed['issued_at'] != old['issued_at']
    for key in old:
        if key not in {'issued_at', 'expires_at'}:
            assert renewed[key] == old[key], key
    assert package.read_bytes() == contents, 'Renewal changed package bytes'
    package.write_bytes(contents + b'synthetic tampering')
    rejected = subprocess.run(command, check=False, capture_output=True)
    assert rejected.returncode != 0, 'Tampered payload was accepted'
    package.write_bytes(contents)
    wrong = json.loads(provenance.read_text())
    wrong['artifacts'][0]['sha256'] = '0' * 64
    provenance.write_text(json.dumps(wrong))
    rejected = subprocess.run(command, check=False, capture_output=True)
    assert rejected.returncode != 0 and b'Provenance artifact mismatch' in rejected.stderr
    fixture = temporary / 'fixture'
    fixture.mkdir()
    (fixture / 'file.txt').write_bytes(b'actual shipped bytes')
    sbom = temporary / 'fixture.spdx.json'
    subprocess.run([sys.executable, str(root / 'packaging/create-artifact-sbom.py'),
                    '--version', version, '--name', 'synthetic-fixture', '--root', str(fixture),
                    '--output', str(sbom)], check=True, capture_output=True)
    inventory = json.loads(sbom.read_text())
    assert len(inventory['files']) == 1
    assert inventory['files'][0]['checksums'][0]['checksumValue'] == hashlib.sha256(b'actual shipped bytes').hexdigest()
    assert len(inventory['packages'][0]['packageVerificationCode']['packageVerificationCodeValue']) == 40
print('Authoritative-byte bridge, renewable timestamps, tampering rejection and real-file SBOM regressions passed')
