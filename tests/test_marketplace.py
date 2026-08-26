#!/usr/bin/env python3
"""Regression checks for package-manager metadata generation."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERSION = "3.5.2"


with tempfile.TemporaryDirectory() as temporary:
    temp = Path(temporary)
    assets = temp / "assets"
    output = temp / "output"
    assets.mkdir()
    names = [
        f"SessionSifu-{VERSION}-windows-x64.zip",
        f"SessionSifu-{VERSION}-linux-x64.tar.gz",
        f"SessionSifu-{VERSION}-macos-arm64.zip",
        f"SessionSifu-{VERSION}-macos-x64.zip",
    ]
    for index, name in enumerate(names):
        (assets / name).write_bytes(f"artifact-{index}".encode())
    subprocess.run(
        [
            "python3",
            str(ROOT / "packaging/generate-marketplace-metadata.py"),
            "--asset-dir",
            str(assets),
            "--output",
            str(output),
            "--project-root",
            str(ROOT),
        ],
        check=True,
    )
    winget = next((output / "winget").rglob("*.installer.yaml")).read_text()
    assert "NestedInstallerType: portable" in winget
    assert "SessionSifu\\SessionSifu.exe" in winget
    assert "PortableCommandAlias: sessionsifu" in winget
    aur = (output / "aur/sessionsifu-bin/PKGBUILD").read_text()
    assert "pkgver=3.5.2" in aur
    assert "sha256sums=('" in aur and "SKIP" not in aur
    chocolatey = (output / "chocolatey/sessionsifu/sessionsifu.nuspec").read_text()
    assert "GPL-3.0-or-later" in chocolatey
    cask = (output / "homebrew/Casks/sessionsifu.rb").read_text()
    assert "on_arm do" in cask and "on_intel do" in cask

    without_windows = temp / "without-windows"
    without_windows.mkdir()
    for name in names[1:]:
        (without_windows / name).write_bytes((assets / name).read_bytes())
    partial_output = temp / "partial-output"
    subprocess.run(
        [
            "python3",
            str(ROOT / "packaging/generate-marketplace-metadata.py"),
            "--asset-dir",
            str(without_windows),
            "--output",
            str(partial_output),
            "--project-root",
            str(ROOT),
        ],
        check=True,
    )
    assert (partial_output / "aur/sessionsifu-bin/PKGBUILD").is_file()
    assert (partial_output / "homebrew/Casks/sessionsifu.rb").is_file()
    assert not (partial_output / "winget").exists()
    assert not (partial_output / "chocolatey").exists()

print("marketplace metadata checks passed")
