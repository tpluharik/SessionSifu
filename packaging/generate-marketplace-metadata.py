#!/usr/bin/env python3
"""Generate store submissions from immutable SessionSifu release artifacts."""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path


REPOSITORY = "https://github.com/tpluharik/SessionSifu"
IDENTIFIER = "TomasPluharik.SessionSifu"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project_version(root: Path) -> str:
    source = (root / "app/sessionsifu").read_text(encoding="utf-8")
    match = re.search(
        r'^CURRENT_VERSION = "([0-9]+\.[0-9]+\.[0-9]+)"$', source, re.MULTILINE
    )
    if not match:
        raise SystemExit("Could not read the SessionSifu version")
    return match.group(1)


def optional_one(asset_dir: Path, pattern: str) -> Path | None:
    matches = sorted(asset_dir.rglob(pattern))
    if len(matches) > 1:
        raise SystemExit(
            f"Expected at most one {pattern!r} below {asset_dir}, found {len(matches)}"
        )
    return matches[0] if matches else None


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def generate_winget(output: Path, version: str, archive: Path) -> None:
    base = output / "winget" / "manifests" / "t" / "TomasPluharik" / "SessionSifu" / version
    url = f"{REPOSITORY}/releases/download/v{version}/{archive.name}"
    checksum = sha256(archive).upper()
    write(base / f"{IDENTIFIER}.yaml", f"""
PackageIdentifier: {IDENTIFIER}
PackageVersion: {version}
DefaultLocale: en-US
ManifestType: version
ManifestVersion: 1.10.0
""")
    write(base / f"{IDENTIFIER}.installer.yaml", f"""
PackageIdentifier: {IDENTIFIER}
PackageVersion: {version}
InstallerType: zip
NestedInstallerType: portable
NestedInstallerFiles:
  - RelativeFilePath: SessionSifu\\SessionSifu.exe
    PortableCommandAlias: sessionsifu
ArchiveBinariesDependOnPath: true
Scope: user
UpgradeBehavior: install
Commands:
  - sessionsifu
Installers:
  - Architecture: x64
    InstallerUrl: {url}
    InstallerSha256: {checksum}
ManifestType: installer
ManifestVersion: 1.10.0
""")
    write(base / f"{IDENTIFIER}.locale.en-US.yaml", f"""
PackageIdentifier: {IDENTIFIER}
PackageVersion: {version}
PackageLocale: en-US
Publisher: Tomas Pluharik
PublisherUrl: {REPOSITORY}
PublisherSupportUrl: {REPOSITORY}/issues
PrivacyUrl: {REPOSITORY}/blob/v{version}/docs/PRIVACY.md
Author: Tomas Pluharik and SessionSifu contributors
PackageName: SessionSifu
PackageUrl: {REPOSITORY}
License: GPL-3.0-or-later
LicenseUrl: {REPOSITORY}/blob/v{version}/LICENSE
Copyright: Copyright 2026 Tomas Pluharik and SessionSifu contributors
ShortDescription: Save and restore desktop applications, files and window layouts
Description: SessionSifu saves desktop sessions and restores applications, documents and window geometry. Optional Privacy Recall provides an encrypted local visual timeline with application exclusions and local OCR.
Tags:
  - desktop-session
  - privacy
  - recall
  - session-manager
  - window-manager
ReleaseNotesUrl: {REPOSITORY}/releases/tag/v{version}
ManifestType: defaultLocale
ManifestVersion: 1.10.0
""")


def generate_chocolatey(output: Path, version: str, archive: Path) -> None:
    package = output / "chocolatey" / "sessionsifu"
    url = f"{REPOSITORY}/releases/download/v{version}/{archive.name}"
    checksum = sha256(archive)
    write(package / "sessionsifu.nuspec", f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://schemas.microsoft.com/packaging/2015/06/nuspec.xsd">
  <metadata>
    <id>sessionsifu</id>
    <version>{version}</version>
    <title>SessionSifu</title>
    <authors>Tomas Pluharik and SessionSifu contributors</authors>
    <projectUrl>{REPOSITORY}</projectUrl>
    <license type="expression">GPL-3.0-or-later</license>
    <requireLicenseAcceptance>false</requireLicenseAcceptance>
    <projectSourceUrl>{REPOSITORY}</projectSourceUrl>
    <bugTrackerUrl>{REPOSITORY}/issues</bugTrackerUrl>
    <tags>sessionsifu session restore windows privacy recall</tags>
    <summary>Save and restore desktop applications, files and window layouts.</summary>
    <description>SessionSifu restores desktop sessions and offers an optional encrypted local visual timeline.</description>
    <releaseNotes>{REPOSITORY}/releases/tag/v{version}</releaseNotes>
  </metadata>
</package>
""")
    write(package / "tools" / "chocolateyinstall.ps1", f"""
$ErrorActionPreference = 'Stop'
$toolsDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Install-ChocolateyZipPackage -PackageName 'sessionsifu' `
  -Url64bit '{url}' -UnzipLocation $toolsDir `
  -Checksum64 '{checksum}' -ChecksumType64 'sha256'
$target = Join-Path $toolsDir 'SessionSifu\\SessionSifu.exe'
$shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'SessionSifu.lnk'
Install-ChocolateyShortcut -ShortcutFilePath $shortcut -TargetPath $target
""")
    write(package / "tools" / "chocolateyuninstall.ps1", """
$shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'SessionSifu.lnk'
if (Test-Path $shortcut) { Remove-Item -Force $shortcut }
""")


def generate_aur(output: Path, version: str, archive: Path) -> None:
    package = output / "aur" / "sessionsifu-bin"
    url = f"{REPOSITORY}/releases/download/v{version}/{archive.name}"
    write(package / "PKGBUILD", f"""
# Maintainer: Tomas Pluharik <tpluharik at gmail dot com>
pkgname=sessionsifu-bin
pkgver={version}
pkgrel=1
pkgdesc='Cross-desktop session restoration and private local visual timeline'
arch=('x86_64')
url='{REPOSITORY}'
license=('GPL-3.0-or-later')
optdepends=('kdotool: KDE Plasma Wayland window geometry'
            'wmctrl: X11 window geometry'
            'tesseract: local screenshot OCR')
provides=('sessionsifu')
conflicts=('sessionsifu')
source=("${{pkgname}}-${{pkgver}}.tar.gz::{url}")
sha256sums=('{sha256(archive)}')

package() {{
  install -d "${{pkgdir}}/opt" "${{pkgdir}}/usr/bin" \
    "${{pkgdir}}/usr/share/applications" "${{pkgdir}}/usr/share/icons/hicolor/512x512/apps"
  cp -a "${{srcdir}}/SessionSifu" "${{pkgdir}}/opt/SessionSifu"
  ln -s /opt/SessionSifu/SessionSifu "${{pkgdir}}/usr/bin/sessionsifu"
  install -Dm644 "${{srcdir}}/SessionSifu/org.gnome.SessionSifu.desktop" \
    "${{pkgdir}}/usr/share/applications/org.gnome.SessionSifu.desktop"
  install -Dm644 "${{srcdir}}/SessionSifu/sessionsifu-app-icon.png" \
    "${{pkgdir}}/usr/share/icons/hicolor/512x512/apps/org.gnome.SessionSifu.png"
}}
""")


def generate_homebrew(output: Path, version: str, arm: Path, intel: Path) -> None:
    arm_url = f"{REPOSITORY}/releases/download/v{version}/{arm.name}"
    intel_url = f"{REPOSITORY}/releases/download/v{version}/{intel.name}"
    write(output / "homebrew" / "Casks" / "sessionsifu.rb", f"""
cask "sessionsifu" do
  version "{version}"

  on_arm do
    sha256 "{sha256(arm)}"
    url "{arm_url}"
  end

  on_intel do
    sha256 "{sha256(intel)}"
    url "{intel_url}"
  end

  name "SessionSifu"
  desc "Desktop session restoration and private local visual timeline"
  homepage "{REPOSITORY}"

  depends_on macos: ">= :monterey"
  app "SessionSifu.app"
end
""")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--asset-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    version = project_version(args.project_root)
    windows = optional_one(args.asset_dir, f"SessionSifu-{version}-windows-x64.zip")
    linux = optional_one(args.asset_dir, f"SessionSifu-{version}-linux-x64.tar.gz")
    mac_arm = optional_one(args.asset_dir, f"SessionSifu-{version}-macos-arm64.zip")
    mac_intel = optional_one(args.asset_dir, f"SessionSifu-{version}-macos-x64.zip")
    if windows is not None:
        generate_winget(args.output, version, windows)
        generate_chocolatey(args.output, version, windows)
    if linux is not None:
        generate_aur(args.output, version, linux)
    if mac_arm is not None and mac_intel is not None:
        generate_homebrew(args.output, version, mac_arm, mac_intel)
    elif mac_arm is not None or mac_intel is not None:
        raise SystemExit("Both macOS architectures are required for Homebrew metadata")
    if not any((windows, linux, mac_arm, mac_intel)):
        raise SystemExit(f"No SessionSifu {version} release artifacts were found")
    print(args.output)


if __name__ == "__main__":
    main()
