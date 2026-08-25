"""Common adapter contracts and safe process/file helpers."""

from __future__ import annotations

import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from ..model import SessionSnapshot, WindowSnapshot
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


class PlatformAdapter(ABC):
    key = "unknown"
    desktop = "Unknown"
    capabilities = AdapterCapabilities()

    @abstractmethod
    def capture_windows(self, include_files: bool = True) -> list[WindowSnapshot]:
        raise NotImplementedError

    def capture(self, include_files: bool = True) -> SessionSnapshot:
        return SessionSnapshot(
            platform=self.key,
            desktop=self.desktop,
            windows=self.capture_windows(include_files=include_files),
            capabilities=asdict(self.capabilities),
        )

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

    def restore(
        self,
        session: SessionSnapshot,
        settle_seconds: float = 2.0,
        selected: set[str] | None = None,
    ) -> dict[str, int]:
        launched: set[str] = set()
        launched_count = 0
        for window in session.windows:
            identity = self.restore_identity(window)
            if not identity or identity in launched:
                continue
            if selected is not None and identity not in selected:
                continue
            launched.add(identity)
            self.launch_window(window)
            launched_count += 1
        if launched_count:
            time.sleep(max(0.0, min(10.0, settle_seconds)))
        restored = [
            window for window in session.windows
            if selected is None or self.restore_identity(window) in selected
        ]
        self.apply_layout(replace(session, windows=restored))
        restored_windows = len(restored)
        return {"applications": launched_count, "windows": restored_windows}

    def diagnostics(self) -> dict[str, object]:
        return {
            "adapter": self.key,
            "desktop": self.desktop,
            "capabilities": asdict(self.capabilities),
        }
