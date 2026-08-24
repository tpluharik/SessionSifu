#!/usr/bin/env python3
"""Render the synthetic Privacy Recall walkthrough used by the documentation."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "docs" / "media"
WIDTH, HEIGHT = 1200, 676
FPS = 15
FRAMES = 135

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT, size)


def ease(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def rounded(draw: ImageDraw.ImageDraw, box, radius=18, fill="#ffffff", outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def label(draw: ImageDraw.ImageDraw, xy, text: str, size=22, color="#27313a", bold=False, anchor=None):
    draw.text(xy, text, font=font(size, bold), fill=color, anchor=anchor)


def app_window(draw: ImageDraw.ImageDraw, box, title: str, accent: str, lines: list[str], active=False):
    x1, y1, x2, y2 = box
    rounded(draw, box, 15, "#f9fafb", "#bcc4ca", 2 if active else 1)
    draw.rounded_rectangle((x1, y1, x2, y1 + 40), radius=15, fill="#edf0f2")
    draw.rectangle((x1, y1 + 22, x2, y1 + 40), fill="#edf0f2")
    draw.ellipse((x1 + 14, y1 + 14, x1 + 26, y1 + 26), fill=accent)
    label(draw, (x1 + 36, y1 + 20), title, 16, "#32383e", True, "lm")
    for index, line in enumerate(lines):
        yy = y1 + 62 + index * 27
        draw.rounded_rectangle((x1 + 18, yy, min(x2 - 18, x1 + 18 + len(line) * 8), yy + 9), 4, fill="#cfd5da")
    draw.rounded_rectangle((x1 + 18, y2 - 34, x1 + 104, y2 - 18), 7, fill=accent)


def shell(draw: ImageDraw.ImageDraw, recording=False):
    draw.rectangle((0, 0, WIDTH, 42), fill="#16191d")
    label(draw, (24, 21), "SessionSifu demo", 15, "#f5f7f8", True, "lm")
    label(draw, (WIDTH - 28, 21), "10:42", 15, "#f5f7f8", False, "rm")
    cx = WIDTH - 118
    draw.ellipse((cx - 12, 9, cx + 12, 33), outline="#f5f7f8", width=2)
    draw.arc((cx - 7, 14, cx + 7, 28), 35, 215, fill="#f5f7f8", width=2)
    if recording:
        draw.ellipse((cx + 7, 7, cx + 17, 17), fill="#ef4444")


def footer(draw: ImageDraw.ImageDraw, step: int, caption: str):
    rounded(draw, (165, 608, 1035, 655), 20, "#17202a")
    for index in range(4):
        x = 198 + index * 28
        draw.ellipse((x, 626, x + 10, 636), fill="#69a900" if index <= step else "#65717c")
    label(draw, (330, 631), caption, 18, "#ffffff", True, "lm")


def capture_scene(frame: int) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#17334a")
    draw = ImageDraw.Draw(image)
    for y in range(42, HEIGHT):
        shade = int(44 + (y / HEIGHT) * 38)
        draw.line((0, y, WIDTH, y), fill=(19, shade, 70 + shade // 3))
    shell(draw, recording=True)
    app_window(draw, (70, 105, 500, 355), "Roadmap — Writer", "#4f7df3", ["SessionSifu roadmap", "Release preview and journal", "Privacy-first local search"], True)
    app_window(draw, (550, 90, 1120, 310), "Research — Browser", "#e16b3d", ["Recall design notes", "Per-window screenshot capture", "Search exact visible text"])
    app_window(draw, (525, 345, 1050, 565), "Tests — Terminal", "#28a269", ["OCR corpus: Czech + English", "window gallery checks", "all tests passed"])
    pulse = 0.55 + 0.45 * math.sin(frame * 0.6) ** 2
    rounded(draw, (400, 54, 800, 92), 18, "#ffffff")
    draw.ellipse((420, 66, 434, 80), fill=(239, int(68 + 80 * pulse), int(68 + 50 * pulse)))
    label(draw, (448, 73), "Saving encrypted Recall moment locally…", 17, "#30383f", True, "lm")
    footer(draw, 0, "Capture eligible windows — local, bounded, encrypted")
    return image


def preview_canvas(draw: ImageDraw.ImageDraw, box, highlight=False, variant=0):
    x1, y1, x2, y2 = box
    rounded(draw, box, 12, "#eef3f6", "#c7d0d6")
    draw.rectangle((x1, y1, x2, y1 + 34), fill="#27313a")
    colors = ["#4f7df3", "#e16b3d", "#28a269"]
    titles = ["Roadmap — Writer", "Research — Browser", "Tests — Terminal"]
    label(draw, (x1 + 16, y1 + 17), titles[variant], 13, "#ffffff", True, "lm")
    label(draw, (x1 + 22, y1 + 65), "SessionSifu release readiness", 18, "#30383f", True)
    label(draw, (x1 + 22, y1 + 101), "Review the restore preview before release.", 15, "#5b6570")
    label(draw, (x1 + 22, y1 + 130), "The release journal stays private and local.", 15, "#5b6570")
    if highlight:
        word_x = x1 + 89
        draw.rounded_rectangle((word_x, y1 + 94, word_x + 58, y1 + 119), 4, fill="#ffe45c", outline="#e4aa00", width=2)
        label(draw, (word_x + 5, y1 + 106), "release", 15, "#222222", True, "lm")
    draw.rounded_rectangle((x1 + 22, y2 - 44, x1 + 150, y2 - 20), 10, fill=colors[variant])


def search_scene(frame: int) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#e9edef")
    draw = ImageDraw.Draw(image)
    shell(draw, recording=False)
    rounded(draw, (60, 62, 1140, 590), 24, "#fbfbfc", "#d1d6da")
    label(draw, (92, 95), "Browse Recall Snapshots", 27, "#30363b", True)
    label(draw, (92, 126), "Private local visual timeline", 16, "#7a8288")
    rounded(draw, (92, 150, 900, 202), 14, "#ffffff", "#6da431", 3)
    typed = "release"[: max(0, min(7, (frame - 28) // 3))]
    label(draw, (122, 176), typed or "Search application, title, file or screenshot text", 18, "#363d43" if typed else "#9aa1a6", False, "lm")
    rounded(draw, (918, 157, 1005, 195), 12, "#4d8d00")
    label(draw, (961, 176), "Visual", 15, "#ffffff", True, "mm")
    rounded(draw, (1012, 157, 1098, 195), 12, "#ffffff", "#aab2b8")
    label(draw, (1055, 176), "Compact", 14, "#30363b", True, "mm")
    if len(typed) == 7:
        rounded(draw, (92, 222, 406, 526), 16, "#f4f6f7")
        rounded(draw, (106, 238, 392, 372), 12, "#ffffff", "#6da431", 2)
        preview_canvas(draw, (118, 248, 260, 350), highlight=False)
        label(draw, (272, 255), "Roadmap", 16, "#30363b", True)
        label(draw, (272, 280), "Writer", 14, "#69727a")
        label(draw, (118, 393), "Found in screenshot", 14, "#4d8d00", True)
        label(draw, (118, 420), "…preview before release…", 14, "#30363b")
        label(draw, (118, 456), "10:41 · exact window", 13, "#69727a")
        preview_canvas(draw, (424, 238, 1088, 457), highlight=frame >= 58)
        label(draw, (424, 476), "1 of 3 · Roadmap — Writer · Exact application-window screenshot", 13, "#69727a")
        for index, (text, active) in enumerate((("Roadmap", True), ("Research", False), ("Tests", False))):
            x1 = 424 + index * 151
            rounded(draw, (x1, 497, x1 + 140, 526), 8, "#e9f2de" if active else "#ffffff", "#6da431" if active else "#c5ccd1")
            label(draw, (x1 + 70, 511), text, 12, "#30363b", active, "mm")
        for index, text in enumerate(("‹ Match", "Match 1 of 1", "Zoom to match")):
            x1 = 884 + index * 68 if index < 2 else 988
            if index == 0:
                rounded(draw, (735, 497, 812, 526), 8, "#ffffff", "#c5ccd1")
                label(draw, (773, 511), text, 11, "#30363b", False, "mm")
            elif index == 1:
                label(draw, (873, 511), text, 11, "#69727a", False, "mm")
            else:
                rounded(draw, (982, 497, 1088, 526), 8, "#4d8d00")
                label(draw, (1035, 511), text, 10, "#ffffff", True, "mm")
    else:
        label(draw, (600, 350), "Search encrypted moments by the window you remember", 20, "#747d84", True, "mm")
    footer(draw, 1, "Large preview, window filmstrip and OCR match navigation")
    return image


def gallery_scene(frame: int) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#1e252b")
    draw = ImageDraw.Draw(image)
    shell(draw, recording=False)
    rounded(draw, (80, 62, 1120, 588), 24, "#fbfbfc")
    label(draw, (110, 94), "Recall Window Gallery", 25, "#30363b", True)
    label(draw, (1090, 96), "1 of 3", 16, "#707980", True, "ra")
    preview_canvas(draw, (120, 135, 865, 500), highlight=True)
    rounded(draw, (895, 137, 1084, 231), 10, "#ffffff", "#6da431", 3)
    label(draw, (910, 153), "Matched window", 13, "#4d8d00", True)
    label(draw, (910, 181), "Roadmap — Writer", 14, "#30363b", True)
    label(draw, (910, 207), "OCR: release", 13, "#707980")
    rounded(draw, (895, 247, 1084, 332), 10, "#ffffff", "#c5ccd1")
    label(draw, (910, 264), "Research — Browser", 13, "#30363b", True)
    label(draw, (910, 293), "Window 2", 13, "#707980")
    rounded(draw, (895, 348, 1084, 433), 10, "#ffffff", "#c5ccd1")
    label(draw, (910, 365), "Tests — Terminal", 13, "#30363b", True)
    label(draw, (910, 394), "Window 3", 13, "#707980")
    rounded(draw, (330, 520, 450, 559), 11, "#ffffff", "#aab2b8")
    label(draw, (390, 539), "Previous", 15, "#30363b", True, "mm")
    rounded(draw, (465, 520, 585, 559), 11, "#4d8d00")
    label(draw, (525, 539), "Next", 15, "#ffffff", True, "mm")
    glow = int(100 + 80 * math.sin(frame * 0.35) ** 2)
    draw.rounded_rectangle((202, 227, 323, 275), 8, outline=(255, 190, 0, glow), width=4)
    footer(draw, 2, "Open the exact match, then browse every captured window")
    return image


def privacy_scene(frame: int) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), "#eef1f2")
    draw = ImageDraw.Draw(image)
    shell(draw, recording=False)
    rounded(draw, (140, 80, 1060, 565), 24, "#ffffff", "#d1d7db")
    label(draw, (600, 125), "Recall stays under your control", 30, "#283239", True, "ma")
    items = [
        ("Encrypted locally", "AES-256-GCM records and previews", "#4f7df3"),
        ("Separate opt-ins", "Screenshots, OCR, paths and related matches", "#28a269"),
        ("Pause or exclude", "Visible status, app/site filters and timed pause", "#e16b3d"),
        ("Delete precisely", "One moment, app, site, time range or everything", "#8f59c7"),
    ]
    for index, (title, subtitle, color) in enumerate(items):
        y = 175 + index * 82
        rounded(draw, (190, y, 1010, y + 62), 14, "#f7f9fa")
        draw.ellipse((212, y + 18, 238, y + 44), fill=color)
        label(draw, (258, y + 20), title, 18, "#30383f", True)
        label(draw, (258, y + 43), subtitle, 14, "#727b82")
        label(draw, (970, y + 31), "✓", 22, color, True, "mm")
    footer(draw, 3, "Off by default · local processing · no telemetry")
    return image


def render_frame(index: int) -> Image.Image:
    if index < 28:
        return capture_scene(index)
    if index < 75:
        return search_scene(index)
    if index < 106:
        return gallery_scene(index)
    return privacy_scene(index)


def ffmpeg_executable() -> str:
    explicit = os.environ.get("SESSIONSIFU_FFMPEG")
    if explicit and Path(explicit).is_file():
        return explicit
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as exc:
        raise SystemExit("Install ffmpeg or imageio-ffmpeg to render MP4") from exc


def main() -> int:
    MEDIA.mkdir(parents=True, exist_ok=True)
    frames = [render_frame(index) for index in range(FRAMES)]
    frames[0].save(
        MEDIA / "recall-demo.webp",
        save_all=True,
        append_images=frames[1:],
        duration=1000 // FPS,
        loop=0,
        quality=68,
        method=6,
    )
    frames[63].save(MEDIA / "recall-demo-poster.png", optimize=True)
    with tempfile.TemporaryDirectory(prefix="sessionsifu-demo-") as directory:
        frame_dir = Path(directory)
        for index, frame in enumerate(frames):
            frame.save(frame_dir / f"frame-{index:04d}.png", optimize=True)
        subprocess.run(
            [
                ffmpeg_executable(), "-y", "-loglevel", "error", "-framerate", str(FPS),
                "-i", str(frame_dir / "frame-%04d.png"), "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-crf", "25",
                str(MEDIA / "recall-demo.mp4"),
            ],
            check=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
