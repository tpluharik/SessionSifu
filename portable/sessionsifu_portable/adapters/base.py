"""Common adapter contracts and safe process/file helpers."""

from __future__ import annotations

import os
import subprocess
import time
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from ..model import MonitorSnapshot, SessionSnapshot, WindowSnapshot
from ..content import enrich_generic_session

try:
    import psutil
except ImportError:  # pragma: no cover - the frozen release always includes psutil
    psutil = None


@dataclass(frozen=True, slots=True)
class AdapterCapabilities:
    applications: bool = True
    documents: bool = True
    geometry: bool = False
    workspaces: bool = False
    monitors: bool = False
    native_wayland: bool = False


def process_details(pid: int, include_command: bool = True) -> tuple[str, list[str]]:
    if pid <= 0 or psutil is None:
        return "", []
    try:
        process = psutil.Process(pid)
        return process.exe(), process.cmdline()[:64] if include_command else []
    except (psutil.Error, OSError):
        return "", []


def process_files(pid: int, limit: int = 32) -> list[str]:
    if pid <= 0 or psutil is None:
        return []
    home = Path.home().resolve()
    found: list[str] = []
    try:
        candidates = [entry.path for entry in psutil.Process(pid).open_files()]
    except (psutil.Error, OSError):
        return []
    for raw in candidates[:512]:
        try:
            path = Path(raw).resolve()
            relative = path.relative_to(home)
            if any(part.startswith(".") for part in relative.parts):
                continue
            if not path.is_file() or path.is_symlink():
                continue
            value = str(path)
            if value not in found:
                found.append(value)
            if len(found) >= limit:
                break
        except (OSError, ValueError):
            continue
    return found


def cached_process_snapshot(
    cache: dict[int, tuple[str, list[str], list[str]]],
    pid: int,
    *,
    include_files: bool = True,
) -> tuple[str, list[str], list[str]]:
    """Resolve process metadata once per PID during a capture operation.

    Desktop APIs commonly return several windows for one application process.
    Repeating executable, command-line and open-file discovery for each window
    is expensive on every supported OS and can race a process that is exiting.
    The cache is deliberately capture-scoped so no process information survives
    longer than the snapshot operation.
    """
    cached = cache.get(pid)
    if cached is not None:
        executable, command, files = cached
        return executable, list(command), list(files) if include_files else []
    executable, command = process_details(pid, include_command=include_files)
    files = process_files(pid) if include_files else []
    cache[pid] = (executable, list(command), list(files))
    return executable, list(command), list(files)


class PlatformAdapter(ABC):
    key = "unknown"
    desktop = "Unknown"
    capabilities = AdapterCapabilities()

    @abstractmethod
    def capture_windows(self, include_files: bool = True) -> list[WindowSnapshot]:
        raise NotImplementedError

    def capture(self, include_files: bool = True) -> SessionSnapshot:
        windows = self.capture_windows(include_files=include_files)
        monitors = self.capture_monitors(windows)
        for window in windows:
            if not window.monitor:
                window.monitor = self.monitor_for_geometry(window.geometry, monitors)
        return SessionSnapshot(
            platform=self.key,
            desktop=self.desktop,
            windows=windows,
            monitors=monitors,
            capabilities=asdict(self.capabilities),
        )

    def capture_monitors(self, windows: list[WindowSnapshot] | None = None) -> list[MonitorSnapshot]:
        windows = windows or []
        if windows:
            left = min(window.geometry[0] for window in windows)
            top = min(window.geometry[1] for window in windows)
            right = max(window.geometry[0] + window.geometry[2] for window in windows)
            bottom = max(window.geometry[1] + window.geometry[3] for window in windows)
            return [MonitorSnapshot(
                monitor_id="virtual-desktop", name="Virtual desktop",
                geometry=[left, top, max(64, right - left), max(64, bottom - top)],
                primary=True,
            )]
        return [MonitorSnapshot(monitor_id="primary", name="Primary", primary=True)]

    @staticmethod
    def monitor_for_geometry(geometry: list[int], monitors: list[MonitorSnapshot]) -> str:
        x, y, width, height = geometry
        cx, cy = x + width / 2, y + height / 2
        for monitor in monitors:
            mx, my, mw, mh = monitor.geometry
            if mx <= cx < mx + mw and my <= cy < my + mh:
                return monitor.monitor_id or monitor.name
        return (next((item for item in monitors if item.primary), monitors[0]).monitor_id if monitors else "")

    @staticmethod
    def reconcile_geometry(
        geometry: list[int], monitor_id: str,
        saved_monitors: list[MonitorSnapshot], current_monitors: list[MonitorSnapshot],
    ) -> list[int]:
        if not current_monitors:
            return geometry
        source = next((item for item in saved_monitors if monitor_id in {item.monitor_id, item.name}), None)
        target = next((item for item in current_monitors if monitor_id in {item.monitor_id, item.name}), None)
        if source is None and saved_monitors:
            x, y, width, height = geometry
            source = next((item for item in saved_monitors if item.geometry[0] <= x + width / 2 < item.geometry[0] + item.geometry[2] and item.geometry[1] <= y + height / 2 < item.geometry[1] + item.geometry[3]), saved_monitors[0])
        if target is None:
            candidates = current_monitors
            if source:
                target = min(candidates, key=lambda item: abs(item.geometry[2] / item.geometry[3] - source.geometry[2] / source.geometry[3]) + abs(item.geometry[2] - source.geometry[2]) / max(1, source.geometry[2]))
            else:
                target = next((item for item in candidates if item.primary), candidates[0])
        tx, ty, tw, th = target.geometry
        if source:
            sx, sy, sw, sh = source.geometry
            x = tx + round((geometry[0] - sx) * tw / max(1, sw))
            y = ty + round((geometry[1] - sy) * th / max(1, sh))
            width = round(geometry[2] * tw / max(1, sw))
            height = round(geometry[3] * th / max(1, sh))
        else:
            x, y, width, height = geometry
        width, height = max(64, min(tw, width)), max(64, min(th, height))
        x = max(tx, min(tx + tw - width, x))
        y = max(ty, min(ty + th - height, y))
        return [x, y, width, height]

    def enrich_content(self, session: SessionSnapshot) -> None:
        """Add observable app content before OCR; platform adapters may improve it."""
        enrich_generic_session(session)

    @staticmethod
    def restore_identity(window: WindowSnapshot) -> str:
        return window.app_id or window.executable or "\0".join(window.command)

    def plan_restore(self, session: SessionSnapshot) -> list[dict[str, object]]:
        grouped: dict[str, dict[str, object]] = {}
        for window in session.windows:
            identity = self.restore_identity(window)
            if not identity:
                continue
            item = grouped.setdefault(identity, {
                "identity": identity,
                "application": window.app_name or window.app_id or Path(window.executable).name,
                "windows": 0,
                "documents": [],
                "targets": [],
            })
            item["windows"] = int(item["windows"]) + 1
            item["documents"] = list(dict.fromkeys([
                *list(item["documents"]), *window.open_files,
            ]))[:32]
            item["targets"] = list(dict.fromkeys([
                *list(item["targets"]), *window.deep_targets,
            ]))[:32]
        return list(grouped.values())

    def launch_window(self, window: WindowSnapshot) -> bool:
        command = list(window.command)
        executable = Path(window.executable) if window.executable else None
        if command and executable and executable.is_file():
            command[0] = str(executable)
        elif executable and executable.is_file():
            command = [str(executable)]
        else:
            return False
        identity = "\n".join((window.app_id, window.app_name, window.executable)).casefold()
        supports_documents = any(token in identity for token in (
            "libreoffice", "soffice", "code", "codium", "idea", "pycharm",
            "clion", "goland", "webstorm", "rider", "obsidian",
        ))
        if supports_documents:
            command.extend(
                path for path in window.open_files
                if Path(path).is_absolute() and Path(path).is_file() and path not in command
            )
        if any(token in identity for token in ("firefox", "chrome", "chromium", "edge", "brave", "vivaldi")):
            command.extend(
                target for target in window.deep_targets
                if urllib.parse.urlparse(target).scheme in {"http", "https"} and target not in command
            )
        subprocess.Popen(
            command,
            cwd=str(Path.home()),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=os.name != "nt",
        )
        return True

    def apply_layout(self, session: SessionSnapshot) -> None:
        del session

    def reconciled_session(self, session: SessionSnapshot) -> SessionSnapshot:
        current = self.capture_monitors()
        windows = [
            replace(window, geometry=self.reconcile_geometry(
                window.geometry, window.monitor, session.monitors, current
            ))
            for window in session.windows
        ]
        return replace(session, windows=windows, monitors=current)

    def restore(
        self,
        session: SessionSnapshot,
        settle_seconds: float = 2.0,
        selected: set[str] | None = None,
    ) -> dict[str, object]:
        launched: set[str] = set()
        launched_count = 0
        actions: list[dict[str, object]] = []
        for window in session.windows:
            identity = self.restore_identity(window)
            if not identity or identity in launched:
                continue
            if selected is not None and identity not in selected:
                actions.append({"identity": identity, "state": "skipped", "reason": "not-selected"})
                continue
            launched.add(identity)
            try:
                launched_result = self.launch_window(window)
                if launched_result is not False:
                    launched_count += 1
                    actions.append({"identity": identity, "state": "launched"})
                else:
                    actions.append({"identity": identity, "state": "skipped", "reason": "not-launchable"})
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                actions.append({"identity": identity, "state": "failed", "error": str(error)[:512]})
        if launched_count:
            time.sleep(max(0.0, min(10.0, settle_seconds)))
        restored = [
            window for window in session.windows
            if selected is None or self.restore_identity(window) in selected
        ]
        try:
            self.apply_layout(replace(session, windows=restored))
            actions.append({"identity": "window-layout", "state": "completed", "windows": len(restored)})
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            actions.append({"identity": "window-layout", "state": "failed", "error": str(error)[:512]})
        restored_windows = len(restored)
        return {"applications": launched_count, "windows": restored_windows, "actions": actions}

    def diagnostics(self) -> dict[str, object]:
        return {
            "adapter": self.key,
            "desktop": self.desktop,
            "capabilities": asdict(self.capabilities),
        }
