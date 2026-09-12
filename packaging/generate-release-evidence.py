#!/usr/bin/env python3
"""Generate deterministic SPDX and artifact provenance for a tagged release."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tomllib


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def timestamp() -> str:
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", "0"))
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--commit", default=os.environ.get("GITHUB_SHA", "unknown"))
    args = parser.parse_args()
    project = tomllib.loads((args.project_root / "portable/pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = str(project["version"])
    created = timestamp()
    dependencies = sorted(str(item) for item in project.get("dependencies", []))
    packages = [{
        "SPDXID": "SPDXRef-Package-SessionSifu",
        "name": "SessionSifu",
        "versionInfo": version,
        "downloadLocation": f"https://github.com/tpluharik/SessionSifu/releases/tag/v{version}",
        "filesAnalyzed": False,
        "licenseConcluded": "GPL-3.0-or-later",
        "licenseDeclared": "GPL-3.0-or-later",
    }]
    relationships = [{
        "spdxElementId": "SPDXRef-DOCUMENT",
        "relationshipType": "DESCRIBES",
        "relatedSpdxElement": "SPDXRef-Package-SessionSifu",
    }]
    for index, requirement in enumerate(dependencies, 1):
        name = requirement.split("==", 1)[0].split(">=", 1)[0].split(";", 1)[0].strip()
        spdx_id = f"SPDXRef-Package-Dependency-{index}"
        packages.append({
            "SPDXID": spdx_id,
            "name": name,
            "versionInfo": requirement.removeprefix(name).lstrip("=<>~! ") or "NOASSERTION",
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "NOASSERTION",
        })
        relationships.append({
            "spdxElementId": "SPDXRef-Package-SessionSifu",
            "relationshipType": "DEPENDS_ON",
            "relatedSpdxElement": spdx_id,
        })
    sbom = {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"SessionSifu-{version}",
        "documentNamespace": f"https://github.com/tpluharik/SessionSifu/spdx/v{version}",
        "creationInfo": {"created": created, "creators": ["Tool: SessionSifu generate-release-evidence.py"]},
        "packages": packages,
        "relationships": relationships,
    }
    artifacts = []
    for path in sorted(args.artifact_dir.iterdir()):
        if path.is_file() and path.name not in {"SHA256SUMS"}:
            artifacts.append({"name": path.name, "bytes": path.stat().st_size, "sha256": digest(path)})
    provenance = {
        "schema": 1,
        "project": "tpluharik/SessionSifu",
        "version": version,
        "source_commit": args.commit,
        "created": created,
        "builder": "github-actions/release.yml",
        "artifacts": artifacts,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / f"SessionSifu-{version}.spdx.json").write_text(
        json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output_dir / f"SessionSifu-{version}.provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
