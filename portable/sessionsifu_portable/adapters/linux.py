"""Portable Linux adapters for KDE Plasma, GNOME and other desktops."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

from .base import AdapterCapabilities, PlatformAdapter, process_details, process_files
from ..model import SessionSnapshot, WindowSnapshot


def _run(command: list[str], timeout: int = 8) -> str:
    completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    return completed.stdout.strip() if completed.returncode == 0 else ""


class LinuxAdapter(PlatformAdapter):
    key = "linux"
    desktop = "Linux Desktop"
    capabilities = AdapterCapabilities(
        applications=True,
        documents=True,
        geometry=bool(shutil.which("wmctrl")),
        workspaces=bool(shutil.which("wmctrl")),
        monitors=False,
        native_wayland=False,
    )

    def capture_windows(self, include_files: bool = True) -> list[WindowSnapshot]:
        if not shutil.which("wmctrl"):
            return []
        windows: list[WindowSnapshot] = []
        for line in _run(["wmctrl", "-lpGx"]).splitlines():
            parts = line.split(None, 9)
            if len(parts) < 10:
                continue
            window_id, workspace, pid_raw, x, y, width, height, _host, app_id, title = parts
            try:
                pid = int(pid_raw)
                geometry = [int(x), int(y), int(width), int(height)]
            except ValueError:
                continue
            executable, command = process_details(pid, include_command=include_files)
            if Path(executable).stem.casefold() in {"sessionsifu", "plasmashell", "gnome-shell"}:
                continue
            windows.append(
                WindowSnapshot(
                    window_id=window_id,
                    app_id=app_id,
                    app_name=app_id.split(".")[-1],
                    title=title,
                    executable=executable,
                    command=command,
                    pid=pid,
                    geometry=geometry,
                    workspace=workspace,
                    open_files=process_files(pid) if include_files else [],
                )
            )
        return windows

    def apply_layout(self, session: SessionSnapshot) -> None:
        if not shutil.which("wmctrl"):
            return
        available: dict[str, list[WindowSnapshot]] = defaultdict(list)
        for current in self.capture_windows():
            available[current.app_id].append(current)
        used: set[str] = set()
        for saved in session.windows:
            choices = [item for item in available.get(saved.app_id, []) if item.window_id not in used]
            if not choices:
                continue
            current = next((item for item in choices if item.title == saved.title), choices[0])
            used.add(current.window_id)
            x, y, width, height = saved.geometry
            _run(["wmctrl", "-ir", current.window_id, "-e", f"0,{x},{y},{width},{height}"])
            if saved.workspace.lstrip("-").isdigit() and int(saved.workspace) >= 0:
                _run(["wmctrl", "-ir", current.window_id, "-t", saved.workspace])


class GnomeAdapter(LinuxAdapter):
    key = "gnome-portable"
    desktop = "GNOME (portable fallback)"

    def diagnostics(self) -> dict[str, object]:
        details = super().diagnostics()
        details["full_extension_detected"] = bool(
            shutil.which("gnome-extensions")
            and "sessionsifu@local" in _run(["gnome-extensions", "list"])
        )
        details["note"] = (
            "Use the bundled GNOME Shell extension for full Wayland geometry; "
            "the portable fallback can only inspect windows exposed by wmctrl."
        )
        return details


class KDEAdapter(LinuxAdapter):
    key = "kde-plasma"
    desktop = "KDE Plasma"

    def __init__(self) -> None:
        self.kdotool = shutil.which("kdotool")
        self.capabilities = AdapterCapabilities(
            applications=True,
            documents=True,
            geometry=bool(self.kdotool or shutil.which("wmctrl")),
            workspaces=bool(self.kdotool or shutil.which("wmctrl")),
            monitors=False,
            native_wayland=bool(self.kdotool),
        )

    def _kdo(self, *arguments: str) -> str:
        if not self.kdotool:
            return ""
        return _run([self.kdotool, *arguments])

    def capture_windows(self, include_files: bool = True) -> list[WindowSnapshot]:
        if not self.kdotool:
            return super().capture_windows(include_files=include_files)
        windows: list[WindowSnapshot] = []
        for window_id in self._kdo("search").splitlines():
            window_id = window_id.strip()
            if not window_id:
                continue
            pid_raw = self._kdo("getwindowpid", window_id).splitlines()[:1]
            if not pid_raw or not pid_raw[0].strip().isdigit():
                continue
            pid = int(pid_raw[0].strip())
            title = self._kdo("getwindowname", window_id).splitlines()[:1]
            app_id = self._kdo("getwindowclassname", window_id).splitlines()[:1]
            geometry_text = self._kdo("getwindowgeometry", window_id)
            position = re.search(r"Position:\s*(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)", geometry_text)
            size = re.search(r"Geometry:\s*(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)", geometry_text)
            if not position or not size:
                continue
            geometry = [
                round(float(position.group(1))),
                round(float(position.group(2))),
                round(float(size.group(1))),
                round(float(size.group(2))),
            ]
            executable, command = process_details(pid, include_command=include_files)
            if Path(executable).stem.casefold() in {"sessionsifu", "plasmashell", "gnome-shell"}:
                continue
            identity = app_id[0].strip() if app_id else Path(executable).stem
            windows.append(
                WindowSnapshot(
                    window_id=window_id,
                    app_id=identity,
                    app_name=identity,
                    title=title[0].strip() if title else "",
                    executable=executable,
                    command=command,
                    pid=pid,
                    geometry=geometry,
                    workspace=self._kdo("get_desktop_for_window", window_id).strip(),
                    open_files=process_files(pid) if include_files else [],
                )
            )
        return windows

    def apply_layout(self, session: SessionSnapshot) -> None:
        if not self.kdotool:
            super().apply_layout(session)
            return
        available: dict[str, list[WindowSnapshot]] = defaultdict(list)
        for current in self.capture_windows():
            available[current.app_id].append(current)
        used: set[str] = set()
        for saved in session.windows:
            choices = [item for item in available.get(saved.app_id, []) if item.window_id not in used]
            if not choices:
                continue
            current = next((item for item in choices if item.title == saved.title), choices[0])
            used.add(current.window_id)
            x, y, width, height = saved.geometry
            self._kdo("windowmove", current.window_id, str(x), str(y))
            self._kdo("windowsize", current.window_id, str(width), str(height))
            if saved.workspace:
                self._kdo("set_desktop_for_window", current.window_id, saved.workspace)

    def diagnostics(self) -> dict[str, object]:
        details = super().diagnostics()
        details["kdotool"] = self.kdotool or "not installed"
        return details
