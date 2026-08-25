#!/usr/bin/env python3
"""Build a self-contained SessionSifu desktop bundle on the current OS."""

from __future__ import annotations

import argparse
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTABLE = ROOT / "portable"
VERSION = "3.5.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["windows", "macos", "linux"])
    parser.add_argument("--arch", default=platform.machine().lower())
    return parser.parse_args()


def zip_tree(source: Path, target: Path, prefix: str = "") -> None:
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        if source.is_file():
            archive.write(source, f"{prefix}{source.name}")
            return
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, f"{prefix}{path.relative_to(source)}")


def main() -> int:
    args = parse_args()
    target = args.target or {"Windows": "windows", "Darwin": "macos"}.get(platform.system(), "linux")
    if importlib.util.find_spec("PyInstaller") is None:
        raise SystemExit("Install portable[gui,build] before building a desktop bundle")

    output = ROOT / "dist" / "portable"
    work = ROOT / "build" / f"pyinstaller-{target}-{args.arch}"
    spec = ROOT / "build" / "pyinstaller-spec"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    spec.mkdir(parents=True, exist_ok=True)

    separator = ";" if os.name == "nt" else ":"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        "SessionSifu",
        "--icon",
        str(ROOT / "branding" / "sessionsifu-app-icon.png"),
        "--paths",
        str(PORTABLE),
        "--add-data",
        f"{ROOT / 'app' / 'org.gnome.SessionSifu.svg'}{separator}app",
        "--add-data",
        f"{ROOT / 'ocr' / 'tessdata'}{separator}tessdata",
        "--distpath",
        str(work / "dist"),
        "--workpath",
        str(work / "work"),
        "--specpath",
        str(spec),
        str(PORTABLE / "launcher.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)

    built = work / "dist" / ("SessionSifu.app" if target == "macos" else "SessionSifu")
    if not built.exists():
        raise SystemExit(f"PyInstaller did not create {built}")
    if target == "linux":
        shutil.copy2(
            ROOT / "branding" / "sessionsifu-app-icon.png",
            built / "sessionsifu-app-icon.png",
        )
        (built / "org.gnome.SessionSifu.desktop").write_text(
            "[Desktop Entry]\n"
            "Name=SessionSifu\n"
            "Comment=Save and restore applications, files and window layouts\n"
            "Exec=sessionsifu\n"
            "Icon=org.gnome.SessionSifu\n"
            "Terminal=false\n"
            "Type=Application\n"
            "Categories=Utility;\n",
            encoding="utf-8",
        )
    suffix = "zip" if target in {"windows", "macos"} else "tar.gz"
    artifact = output / f"SessionSifu-{VERSION}-{target}-{args.arch}.{suffix}"
    artifact.unlink(missing_ok=True)
    if suffix == "zip":
        zip_tree(built, artifact, "SessionSifu.app/" if built.suffix == ".app" else "SessionSifu/")
    else:
        base = str(artifact).removesuffix(".tar.gz")
        archive = Path(shutil.make_archive(base, "gztar", root_dir=built.parent, base_dir=built.name))
        if archive != artifact:
            archive.replace(artifact)
    print(artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
