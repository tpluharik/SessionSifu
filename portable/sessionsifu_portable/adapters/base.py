"""Common adapter contracts and safe process/file helpers."""

from __future__ import annotations

import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path

from ..model import SessionSnapshot, WindowSnapshot

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


def process_details(pid: int) -> tuple[str, list[str]]:
    if pid <= 0 or psutil is None:
        return "", []
    try:
        process = psutil.Process(pid)
        return process.exe(), process.cmdline()[:64]
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


class PlatformAdapter(ABC):
    key = "unknown"
    desktop = "Unknown"
    capabilities = AdapterCapabilities()

    @abstractmethod
    def capture_windows(self) -> list[WindowSnapshot]:
        raise NotImplementedError

    def capture(self) -> SessionSnapshot:
        return SessionSnapshot(
            platform=self.key,
            desktop=self.desktop,
            windows=self.capture_windows(),
            capabilities=asdict(self.capabilities),
        )

    def launch_window(self, window: WindowSnapshot) -> None:
        command = list(window.command)
        executable = Path(window.executable) if window.executable else None
        if command and executable and executable.is_file():
            command[0] = str(executable)
        elif executable and executable.is_file():
            command = [str(executable)]
        else:
            return
        subprocess.Popen(
            command,
            cwd=str(Path.home()),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=os.name != "nt",
        )

    def apply_layout(self, session: SessionSnapshot) -> None:
        del session

    def restore(self, session: SessionSnapshot, settle_seconds: float = 2.0) -> dict[str, int]:
        launched: set[str] = set()
        launched_count = 0
        for window in session.windows:
            identity = window.app_id or window.executable or "\0".join(window.command)
            if not identity or identity in launched:
                continue
            launched.add(identity)
            self.launch_window(window)
            launched_count += 1
        if launched_count:
            time.sleep(max(0.0, min(10.0, settle_seconds)))
        self.apply_layout(session)
        return {"applications": launched_count, "windows": len(session.windows)}

    def diagnostics(self) -> dict[str, object]:
        return {
            "adapter": self.key,
            "desktop": self.desktop,
            "capabilities": asdict(self.capabilities),
        }
