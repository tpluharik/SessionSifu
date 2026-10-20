#!/usr/bin/env python3
"""Inventory real bundle/package bytes and the exact Python build environment.

Build-environment packages are explicitly labelled: their presence in the build
environment alone is not a claim that their files were shipped in the artifact.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import subprocess
import tarfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--deb', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    packages = [{'SPDXID': 'SPDXRef-SessionSifu', 'name': 'SessionSifu', 'versionInfo': args.version,
                 'downloadLocation': 'NOASSERTION', 'filesAnalyzed': True,
                 'licenseConcluded': 'GPL-3.0-or-later', 'licenseDeclared': 'GPL-3.0-or-later'}]
    relationships = [{'spdxElementId': 'SPDXRef-DOCUMENT', 'relationshipType': 'DESCRIBES',
                      'relatedSpdxElement': 'SPDXRef-SessionSifu'}]
    for index, dist in enumerate(sorted(metadata.distributions(), key=lambda item: item.metadata.get('Name', '').lower())):
        identifier = f'SPDXRef-Environment-{index}'
        packages.append({'SPDXID': identifier, 'name': dist.metadata.get('Name', 'unknown'),
                         'versionInfo': dist.version, 'downloadLocation': 'NOASSERTION', 'filesAnalyzed': False,
                         'licenseConcluded': 'NOASSERTION', 'licenseDeclared': 'NOASSERTION',
                         'comment': 'Exact build-environment package; delivered files are enumerated separately.',
                         'externalRefs': [{'referenceCategory': 'PACKAGE-MANAGER', 'referenceType': 'purl',
                                           'referenceLocator': f"pkg:pypi/{dist.metadata.get('Name', 'unknown').lower()}@{dist.version}"}]})
        relationships.append({'spdxElementId': identifier, 'relationshipType': 'BUILD_DEPENDENCY_OF',
                              'relatedSpdxElement': 'SPDXRef-SessionSifu'})
    files = []
    def record(name, stream):
        identifier = f'SPDXRef-File-{len(files)}'
        sha256, sha1 = hashlib.sha256(), hashlib.sha1()
        while block := stream.read(1024 * 1024):
            sha256.update(block)
            sha1.update(block)
        files.append({'SPDXID': identifier, 'fileName': name,
                      'checksums': [{'algorithm': 'SHA256', 'checksumValue': sha256.hexdigest()},
                                    {'algorithm': 'SHA1', 'checksumValue': sha1.hexdigest()}],
                      'licenseInfoInFiles': ['NOASSERTION'],
                      'licenseConcluded': 'NOASSERTION', 'copyrightText': 'NOASSERTION'})
        relationships.append({'spdxElementId': 'SPDXRef-SessionSifu', 'relationshipType': 'CONTAINS',
                              'relatedSpdxElement': identifier})
    if args.deb:
        proc = subprocess.Popen(['dpkg-deb', '--fsys-tarfile', str(args.deb)], stdout=subprocess.PIPE)
        with tarfile.open(fileobj=proc.stdout, mode='r|') as archive:
            for item in archive:
                if item.isfile():
                    with archive.extractfile(item) as stream:
                        record(item.name, stream)
        proc.stdout.close()
        if proc.wait(timeout=30) != 0:
            raise SystemExit('Could not inventory Debian contents')
    elif args.root:
        for path in sorted(args.root.rglob('*')):
            if path.is_file() and not path.is_symlink():
                with path.open('rb') as stream:
                    record(path.relative_to(args.root).as_posix(), stream)
    else:
        parser.error('--root or --deb is required')
    packages[0]['packageVerificationCode'] = {'packageVerificationCodeValue': hashlib.sha1(
        ''.join(sorted(item['checksums'][1]['checksumValue'] for item in files)).encode('ascii')).hexdigest()}
    packages[0]['licenseInfoFromFiles'] = ['NOASSERTION']
    epoch = int(os.environ.get('SOURCE_DATE_EPOCH') or subprocess.check_output(
        ['git', 'show', '-s', '--format=%ct', 'HEAD'], text=True).strip())
    created = datetime.fromtimestamp(epoch, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    value = {'spdxVersion': 'SPDX-2.3', 'dataLicense': 'CC0-1.0', 'SPDXID': 'SPDXRef-DOCUMENT',
             'name': args.name, 'documentNamespace': f'https://github.com/tpluharik/SessionSifu/spdx/{args.name}',
             'creationInfo': {'created': created, 'creators': ['Tool: SessionSifu artifact inventory']},
             'packages': packages, 'files': files, 'relationships': relationships}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
