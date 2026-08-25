#!/usr/bin/env python3
"""Validate local documentation links, current claims and generated media."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image


ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]).resolve()
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
HTML_TARGET = re.compile(r"(?:href|src)=[\"']([^\"']+)[\"']")


def local_target(source: Path, raw: str) -> Path | None:
    target = raw.strip().split()[0].strip("<>")
    if not target or target.startswith(("#", "http://", "https://", "mailto:")):
        return None
    target = target.split("#", 1)[0].split("?", 1)[0]
    if not target:
        return None
    return (source.parent / target).resolve()


markdown_files = sorted(path for path in ROOT.rglob("*.md") if ".git" not in path.parts)
assert markdown_files
for source in markdown_files:
    contents = source.read_text(encoding="utf-8")
    for raw in MARKDOWN_LINK.findall(contents) + HTML_TARGET.findall(contents):
        target = local_target(source, raw)
        if target is not None:
            assert target.exists(), f"Broken local link in {source.relative_to(ROOT)}: {raw}"

readme = (ROOT / "README.md").read_text(encoding="utf-8")
roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
extension_readme = (ROOT / "extension/sessionsifu@local/README.md").read_text(encoding="utf-8")
assert "Version 3.5.0" in readme
assert "docs/media/recall-demo.webp" in readme
assert "docs/RECALL_GUIDE.md" in readme
assert "## Shipped foundation — 3.4.0" in roadmap
assert "## Next: quality and trust" in roadmap
assert "docs/COMPETITIVE_ANALYSIS.md" in readme
assert "## Explicit non-goals" in roadmap
assert "SessionSifu 2 targets" not in contributing
assert "component of Session Keeper" not in extension_readme

media = ROOT / "docs/media"
mp4 = media / "recall-demo.mp4"
webp = media / "recall-demo.webp"
poster = media / "recall-demo-poster.png"
assert 10_000 < mp4.stat().st_size < 2_000_000
assert mp4.read_bytes()[4:8] == b"ftyp"
assert 10_000 < webp.stat().st_size < 2_000_000
with Image.open(webp) as image:
    assert image.format == "WEBP"
    assert image.size == (1200, 676)
    # Pillow coalesces identical animation frames; the remaining key frames
    # must still cover every scene and preserve animation.
    assert getattr(image, "n_frames", 1) >= 30
with Image.open(poster) as image:
    assert image.format == "PNG"
    assert image.size == (1200, 676)

renderer = (ROOT / "tools/render-recall-demo.py").read_text(encoding="utf-8")
assert "synthetic" in renderer.casefold()
assert "FRAMES = 135" in renderer

print(f"documentation checks passed ({len(markdown_files)} Markdown files)")
