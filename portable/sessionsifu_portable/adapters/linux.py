"""Portable Linux adapters for KDE Plasma, GNOME and other desktops."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

from .base import AdapterCapabilities, PlatformAdapter, cached_process_snapshot
from ..model import MonitorSnapshot, SessionSnapshot, WindowSnapshot
from ..content import enrich_linux_session
from ..experimental_wayland import (
    PROTOCOL_NAME,
    PROTOCOL_VERSION,
    detect_wayland_session_management,
    managed_window_ids,
)


KWIN_CAPTURE_SCRIPT = r"""
const rows = workspace.windowList().slice(0, 512).map(function (window) {
    const geometry = window.frameGeometry;
    let desktop = '';
    try {
        if (window.desktops && window.desktops.length)
            desktop = String(window.desktops[0].x11DesktopNumber);
    } catch (_) {}
    return {
        window_id: String(window.internalId || ''),
        app_id: String(window.desktopFileName || window.resourceClass || ''),
        app_name: String(window.resourceClass || window.desktopFileName || ''),
        title: String(window.caption || ''),
        pid: Number(window.pid || 0),
        geometry: [Math.round(geometry.x), Math.round(geometry.y),
                   Math.round(geometry.width), Math.round(geometry.height)],
        workspace: desktop,
        minimized: Boolean(window.minimized)
    };
});
output_result(JSON.stringify(rows));
"""


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
        monitors=bool(shutil.which("xrandr") or shutil.which("kscreen-doctor")),
        native_wayland=False,
    )

    def __init__(self) -> None:
        self.wayland_session = detect_wayland_session_management()
        self.capabilities = replace(
            type(self).capabilities,
            experimental_wayland_session_management=self.wayland_session.usable,
        )

    def capture(self, include_files: bool = True) -> SessionSnapshot:
        session = super().capture(include_files=include_files)
        session.session_protocol = {
            "protocol": PROTOCOL_NAME,
            "version": PROTOCOL_VERSION,
            "feature_enabled": self.wayland_session.feature_enabled,
            "compositor_advertises": self.wayland_session.compositor_advertises,
            # Only a cooperating application may set this true and provide IDs.
            "client_claimed": False,
            "managed_window_ids": [],
        }
        return session

    def capture_windows(self, include_files: bool = True) -> list[WindowSnapshot]:
        if not shutil.which("wmctrl"):
            return []
        windows: list[WindowSnapshot] = []
        process_cache: dict[int, tuple[str, list[str], list[str]]] = {}
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
            executable, command, open_files = cached_process_snapshot(
                process_cache, pid, include_files=include_files
            )
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
                    open_files=open_files,
                )
            )
        return windows

    def enrich_content(self, session: SessionSnapshot) -> None:
        enrich_linux_session(session)

    def capture_monitors(self, windows=None) -> list[MonitorSnapshot]:
        monitors: list[MonitorSnapshot] = []
        if shutil.which("xrandr"):
            for line in _run(["xrandr", "--query"]).splitlines():
                match = re.match(
                    r"^(\S+) connected(?: primary)?\s+(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", line
                )
                if not match:
                    continue
                name, width, height, x, y = match.groups()
                monitors.append(MonitorSnapshot(
                    monitor_id=name, name=name,
                    geometry=[int(x), int(y), int(width), int(height)],
                    primary=" connected primary " in f" {line} ",
                ))
        return monitors or super().capture_monitors(windows)

    def apply_layout(self, session: SessionSnapshot) -> list[dict]:
        session = self.reconciled_session(session)
        delegated = managed_window_ids(session.session_protocol, self.wayland_session)
        outcomes = [
            {
                "window_id": saved.window_id,
                "state": "delegated",
                "reason": "Layout is owned by the cooperating Wayland session client",
            }
            for saved in session.windows
            if saved.window_id in delegated
        ]
        if not shutil.which("wmctrl"):
            return outcomes
        available: dict[str, list[WindowSnapshot]] = defaultdict(list)
        for current in self.capture_windows(include_files=False):
            available[current.app_id].append(current)
        used: set[str] = set()
        for saved in session.windows:
            if saved.window_id in delegated:
                continue
            choices = [item for item in available.get(saved.app_id, []) if item.window_id not in used]
            if not choices:
                continue
            current = next((item for item in choices if item.title == saved.title), choices[0])
            used.add(current.window_id)
            x, y, width, height = saved.geometry
            subprocess.run(["wmctrl", "-ir", current.window_id, "-e", f"0,{x},{y},{width},{height}"], check=True, timeout=8, capture_output=True)
            if saved.workspace.lstrip("-").isdigit() and int(saved.workspace) >= 0:
                subprocess.run(["wmctrl", "-ir", current.window_id, "-t", saved.workspace], check=True, timeout=8, capture_output=True)
            outcomes.append({"window_id": saved.window_id, "state": "completed"})
        return outcomes

    def diagnostics(self) -> dict[str, object]:
        details = super().diagnostics()
        details["experimental_wayland_session_management"] = self.wayland_session.to_dict()
        return details


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
        self.wayland_session = detect_wayland_session_management()
        self.kdotool = shutil.which("kdotool")
        self.capabilities = AdapterCapabilities(
            applications=True,
            documents=True,
            geometry=bool(self.kdotool or shutil.which("wmctrl")),
            workspaces=bool(self.kdotool or shutil.which("wmctrl")),
            monitors=bool(shutil.which("kscreen-doctor") or shutil.which("xrandr")),
            native_wayland=bool(self.kdotool),
            experimental_wayland_session_management=self.wayland_session.usable,
        )

    def _kdo(self, *arguments: str) -> str:
        if not self.kdotool:
            return ""
        return _run([self.kdotool, *arguments])

    def _kwin_json(self, script: str):
        """Run one bounded KWin script and parse its structured result."""
        output = self._kdo("kwinscript", "--inline", script)
        for line in reversed(output.splitlines()):
            candidate = line.strip()
            if not candidate or candidate[0] not in "[{":
                continue
            try:
                return json.loads(candidate)
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    def _batched_kde_windows(
        self, include_files: bool
    ) -> list[WindowSnapshot] | None:
        raw = self._kwin_json(KWIN_CAPTURE_SCRIPT)
        if not isinstance(raw, list):
            return None
        windows: list[WindowSnapshot] = []
        process_cache: dict[int, tuple[str, list[str], list[str]]] = {}
        for item in raw[:512]:
            if not isinstance(item, dict):
                continue
            try:
                pid = int(item.get("pid") or 0)
                geometry = [int(value) for value in list(item.get("geometry") or [])]
            except (TypeError, ValueError):
                continue
            if pid <= 0 or len(geometry) != 4 or geometry[2] < 32 or geometry[3] < 32:
                continue
            executable, command, open_files = cached_process_snapshot(
                process_cache, pid, include_files=include_files
            )
            if Path(executable).stem.casefold() in {
                "sessionsifu", "plasmashell", "gnome-shell"
            }:
                continue
            identity = str(item.get("app_id") or Path(executable).stem)[:512]
            windows.append(WindowSnapshot.from_dict({
                **item,
                "app_id": identity,
                "app_name": str(item.get("app_name") or identity)[:512],
                "executable": executable,
                "command": command,
                "open_files": open_files,
            }))
        return windows

    def capture_windows(self, include_files: bool = True) -> list[WindowSnapshot]:
        if not self.kdotool:
            return super().capture_windows(include_files=include_files)
        batched = self._batched_kde_windows(include_files)
        if batched is not None:
            return batched
        windows: list[WindowSnapshot] = []
        process_cache: dict[int, tuple[str, list[str], list[str]]] = {}
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
            executable, command, open_files = cached_process_snapshot(
                process_cache, pid, include_files=include_files
            )
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
                    open_files=open_files,
                )
            )
        return windows

    def apply_layout(self, session: SessionSnapshot) -> None:
        session = self.reconciled_session(session)
        if not self.kdotool:
            return super().apply_layout(session)
        payload = [
            {
                "window_id": str(window.window_id)[:128],
                "geometry": [int(value) for value in window.geometry],
                "workspace": str(window.workspace)[:16],
            }
            for window in session.windows[:512]
            if window.window_id and len(window.geometry) == 4
        ]
        encoded = json.dumps(payload, separators=(",", ":"))
        script = (
            "const saved=JSON.parse(" + json.dumps(encoded) + ");"
            "const byId={};workspace.windowList().forEach(function(w){"
            "byId[String(w.internalId||'')]=w;});let updated=0;const ids=[];"
            "saved.forEach(function(s){const w=byId[s.window_id];if(!w)return;"
            "const g=w.frameGeometry;g.x=s.geometry[0];g.y=s.geometry[1];"
            "g.width=s.geometry[2];g.height=s.geometry[3];w.frameGeometry=g;"
            "if(s.workspace){const d=workspace.desktops.find(function(item){"
            "return String(item.x11DesktopNumber)===String(s.workspace);});"
            "if(d)w.desktops=[d];}updated++;ids.push(s.window_id);});"
            "output_result(JSON.stringify({updated:updated,ids:ids}));"
        )
        result = self._kwin_json(script)
        applied = set(result.get("ids", [])) if isinstance(result, dict) else set()
        outcomes = [{"window_id": wid, "state": "completed"} for wid in applied]
        if len(applied) == len(session.windows):
            return outcomes
        available: dict[str, list[WindowSnapshot]] = defaultdict(list)
        for current in self.capture_windows(include_files=False):
            available[current.app_id].append(current)
        used: set[str] = set(applied)
        for saved in session.windows:
            if saved.window_id in applied:
                continue
            choices = [item for item in available.get(saved.app_id, []) if item.window_id not in used]
            if not choices:
                continue
            current = next((item for item in choices if item.title == saved.title), choices[0])
            used.add(current.window_id)
            x, y, width, height = saved.geometry
            subprocess.run([self.kdotool, "windowmove", current.window_id, str(x), str(y)], check=True, timeout=8, capture_output=True)
            subprocess.run([self.kdotool, "windowsize", current.window_id, str(width), str(height)], check=True, timeout=8, capture_output=True)
            if saved.workspace:
                subprocess.run([self.kdotool, "set_desktop_for_window", current.window_id, saved.workspace], check=True, timeout=8, capture_output=True)
            outcomes.append({"window_id": saved.window_id, "state": "completed"})
        return outcomes

    def diagnostics(self) -> dict[str, object]:
        details = super().diagnostics()
        details["kdotool"] = self.kdotool or "not installed"
        return details
