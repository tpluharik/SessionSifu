#!/usr/bin/env python3
"""Recover retired, expired raw-channel packages from Git into a release archive."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=Path('packaging/retired-updates.json'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    value = json.loads(args.manifest.read_text())
    commit = value['source_commit']
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise SystemExit('Invalid source commit')
    total = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(args.output, 'w:gz') as archive:
        for item in value['artifacts']:
            name = item['path']
            if not re.fullmatch(r'updates/sessionsifu_\d+\.\d+\.\d+_all.deb', name):
                raise SystemExit('Invalid retired artifact path')
            contents = subprocess.check_output(['git', 'show', f'{commit}:{name}'], timeout=30)
            total += len(contents)
            if (len(contents) != item['size'] or len(contents) > 50 * 1024 * 1024 or
                    total > 512 * 1024 * 1024 or hashlib.sha256(contents).hexdigest() != item['sha256']):
                raise SystemExit('Retired package does not match reviewed bytes')
            info = tarfile.TarInfo(name)
            info.size = len(contents)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(contents))
        contents = args.manifest.read_bytes()
        info = tarfile.TarInfo('retired-updates.json')
        info.size = len(contents)
        info.mode = 0o644
        archive.addfile(info, io.BytesIO(contents))
    print(f'Archived {len(value["artifacts"])} expired payloads; Git history and current channel files preserved')


if __name__ == '__main__':
    main()
